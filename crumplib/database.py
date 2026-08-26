"""Loading normalized records into SQLite.

The schema is derived from the YAML field maps rather than hand-written, so
adding a field to a map is enough -- there is no second place to update.

Map types translate to SQLite as follows:

    A  text     TEXT
    D  date     TEXT, ISO 8601 (SQLite has no date type; ISO strings sort and
                compare correctly, and work with its date functions)
    N  number   INTEGER
    Z  ZIP      TEXT (leading zeros matter, and Canadian postcodes appear)
    B  boolean  INTEGER, 0/1 (SQLite has no boolean type)

`coordinates` fields are stored as two REAL columns -- `<name>_latitude` and
`<name>_longitude` -- rather than a JSON array, so they can be queried and
indexed. A bounding-box query is the common case and it needs real numbers.
"""

import csv
import json
import os
import sqlite3

from .maps import CSV_FILENAMES

# Officer and name-history rows carry long free-text fields; the stdlib default
# of 131,072 is not enough for the widest of them.
csv.field_size_limit(1 << 24)

#: Map field type -> SQLite column type.
SQL_TYPES = {
    "A": "TEXT",
    "D": "TEXT",
    "N": "INTEGER",
    "Z": "TEXT",
    "B": "INTEGER",
}

#: Maps whose rows describe entities.
#:
#: Note these are NOT uniquely keyed by id. The SCC ships multiple rows per
#: entity when registered-agent or merger history differs -- 1,723 of 17,950
#: corp entities in a 20,000-row sample, varying in `agent_date` and `merged`.
#: An `id` PRIMARY KEY would silently keep only the last row of each group, so
#: id is indexed rather than made unique.
ENTITY_TABLES = ("corp", "llc", "lp", "gp", "bt", "psa")

#: Columns worth an index on every table that has them. Chosen for the queries
#: this data actually gets asked: look up an entity, find entities in a place,
#: find recently-changed records.
INDEXED_COLUMNS = (
    "id",
    "name",
    "city",
    "state",
    "zip",
    "status",
    "state_formed",
    "status_date",
    "agent_name",
)


def is_coordinate_field(field):
    """Whether a map field holds a [longitude, latitude] pair."""
    return field.get("derived") == "geocode"


def columns_for(field_map):
    """The SQLite columns for a map, as (name, type) pairs.

    Coordinate fields expand into two REAL columns.
    """
    columns = []
    for field in field_map.fields:
        name = field["alt_name"]
        if is_coordinate_field(field):
            columns.append((name + "_latitude", "REAL"))
            columns.append((name + "_longitude", "REAL"))
            continue
        columns.append((name, SQL_TYPES.get(field.get("type", "A"), "TEXT")))
    return columns


def create_table_sql(stem, field_map):
    """The CREATE TABLE statement for one map."""
    definitions = [f'"{name}" {sql_type}' for name, sql_type in columns_for(field_map)]
    body = ",\n    ".join(definitions)
    return f'CREATE TABLE IF NOT EXISTS "{stem}" (\n    {body}\n)'


def index_statements(stem, field_map):
    """CREATE INDEX statements for the columns worth indexing."""
    names = {name for name, _ in columns_for(field_map)}
    statements = []
    for column in INDEXED_COLUMNS:
        if column not in names:
            continue
        statements.append(
            f'CREATE INDEX IF NOT EXISTS "{stem}_{column}" ON "{stem}" ("{column}")'
        )
    # Coordinates are queried as a bounding box, so index them together.
    for field in field_map.fields:
        if not is_coordinate_field(field):
            continue
        base = field["alt_name"]
        statements.append(
            f'CREATE INDEX IF NOT EXISTS "{stem}_{base}" '
            f'ON "{stem}" ("{base}_latitude", "{base}_longitude")'
        )
    return statements


def _coerce(value, sql_type):
    """Convert a CSV cell to the value SQLite should store."""
    if value is None or value == "":
        return None
    if sql_type == "INTEGER":
        # Booleans arrive as the strings written by the CSV writer.
        if value == "true":
            return 1
        if value == "false":
            return 0
        try:
            return int(value)
        except ValueError:
            return None
    if sql_type == "REAL":
        try:
            return float(value)
        except ValueError:
            return None
    return value


def row_values(row, field_map):
    """Flatten one CSV row into the values for its table's columns."""
    values = []
    for field in field_map.fields:
        name = field["alt_name"]
        if is_coordinate_field(field):
            latitude = longitude = None
            raw = row.get(name)
            if raw:
                try:
                    # The CSV writer serializes the pair as a JSON array.
                    longitude, latitude = json.loads(raw)[:2]
                except (ValueError, TypeError):
                    latitude = longitude = None
            values.append(latitude)
            values.append(longitude)
            continue
        sql_type = SQL_TYPES.get(field.get("type", "A"), "TEXT")
        values.append(_coerce(row.get(name), sql_type))
    return values


def insert_sql(stem, field_map):
    """The INSERT statement for one map."""
    columns = columns_for(field_map)
    names = ", ".join(f'"{name}"' for name, _ in columns)
    placeholders = ", ".join("?" for _ in columns)
    # A plain INSERT: there is no unique key to conflict on, and every source
    # row is meaningful. Repeatability comes from dropping the table first.
    return f'INSERT INTO "{stem}" ({names}) VALUES ({placeholders})'


class Loader:
    """Loads normalized CSV into a SQLite database."""

    def __init__(self, path, maps, batch_size=10000):
        self.path = path
        self.maps = maps
        self.batch_size = batch_size
        self.connection = sqlite3.connect(path)
        self._tune()

    def _tune(self):
        """Settings that matter when inserting millions of rows.

        These trade crash-durability for speed, which is the right trade for a
        rebuildable derived artifact -- if the load fails we re-run it.
        """
        self.connection.execute("PRAGMA journal_mode = OFF")
        self.connection.execute("PRAGMA synchronous = OFF")
        self.connection.execute("PRAGMA cache_size = -64000")
        self.connection.execute("PRAGMA temp_store = MEMORY")

    def create_schema(self, stems=None):
        """Create the tables, without indexes."""
        for stem in stems or sorted(self.maps):
            self.connection.execute(create_table_sql(stem, self.maps[stem]))
        self.connection.commit()

    def drop(self, stem):
        """Drop a table, so a load starts clean rather than merging."""
        self.connection.execute(f'DROP TABLE IF EXISTS "{stem}"')
        self.connection.commit()

    def load_csv(self, stem, path, progress=None):
        """Load one normalized CSV into its table. Returns rows inserted."""
        field_map = self.maps[stem]
        statement = insert_sql(stem, field_map)
        inserted = 0
        batch = []

        with open(path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                batch.append(row_values(row, field_map))
                if len(batch) >= self.batch_size:
                    self.connection.executemany(statement, batch)
                    inserted += len(batch)
                    batch = []
                    if progress:
                        progress(inserted)
            if batch:
                self.connection.executemany(statement, batch)
                inserted += len(batch)

        self.connection.commit()
        return inserted

    def create_indexes(self, stems=None, progress=None):
        """Build indexes. Deliberately after loading -- indexing as you insert
        is markedly slower than indexing once at the end.
        """
        for stem in stems or sorted(self.maps):
            for statement in index_statements(stem, self.maps[stem]):
                if progress:
                    progress(stem)
                self.connection.execute(statement)
        self.connection.commit()

    def analyze(self):
        """Collect statistics so the query planner makes good choices."""
        self.connection.execute("ANALYZE")
        self.connection.commit()

    def vacuum(self):
        """Compact the file. Worth it for something we are about to upload."""
        # VACUUM cannot run inside a transaction.
        self.connection.isolation_level = None
        self.connection.execute("VACUUM")
        self.connection.isolation_level = ""

    def row_counts(self):
        """Rows per table, for reporting."""
        counts = {}
        for stem in sorted(self.maps):
            try:
                counts[stem] = self.connection.execute(
                    f'SELECT COUNT(*) FROM "{stem}"'
                ).fetchone()[0]
            except sqlite3.OperationalError:
                continue
        return counts

    def close(self):
        self.connection.close()


def csv_path_for(stem, directory):
    """Where `crump` writes the normalized CSV for a map."""
    return os.path.join(directory, stem + ".csv")


def available_stems(maps, directory):
    """Map stems whose normalized CSV exists on disk."""
    return [
        stem
        for stem in sorted(maps)
        if stem in CSV_FILENAMES and os.path.isfile(csv_path_for(stem, directory))
    ]
