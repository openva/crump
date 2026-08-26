"""Tests for loading normalized records into SQLite.

The schema is derived from the field maps, so these tests mostly guard that
derivation -- and the two things that silently corrupt data if wrong: reserved
words in column names, and collapsing legitimately-repeated rows.
"""

import csv
import sqlite3

import pytest

from crumplib import database
from crumplib.maps import load_maps


@pytest.fixture(scope="module")
def maps():
    return load_maps("table_maps")


class TestSchema:
    def test_every_map_yields_a_create_statement(self, maps):
        for stem, field_map in maps.items():
            sql = database.create_table_sql(stem, field_map)
            assert sql.startswith("CREATE TABLE")
            assert f'"{stem}"' in sql

    def test_coordinates_become_two_real_columns(self, maps):
        names = dict(database.columns_for(maps["corp"]))
        assert names["coordinates_latitude"] == "REAL"
        assert names["coordinates_longitude"] == "REAL"
        assert "coordinates" not in names

    def test_both_address_groups_get_coordinate_columns(self, maps):
        names = dict(database.columns_for(maps["corp"]))
        assert "agent_coordinates_latitude" in names
        assert "agent_coordinates_longitude" in names

    def test_map_types_become_sql_types(self, maps):
        names = dict(database.columns_for(maps["corp"]))
        assert names["name"] == "TEXT"  # A
        assert names["status_date"] == "TEXT"  # D, ISO 8601
        assert names["total_shares"] == "INTEGER"  # N
        assert names["zip"] == "TEXT"  # Z, leading zeros matter
        assert names["foreign"] == "INTEGER"  # B

    def test_reserved_words_are_quoted(self, maps):
        """`foreign` is SQL-reserved; an unquoted column name is a syntax error."""
        sql = database.create_table_sql("corp", maps["corp"])
        assert '"foreign"' in sql

    def test_no_primary_key_on_entity_tables(self, maps):
        """The SCC repeats entity ids with differing agent/merger history.

        A PRIMARY KEY on id would silently keep only the last of each group.
        """
        sql = database.create_table_sql("corp", maps["corp"])
        assert "PRIMARY KEY" not in sql

    def test_insert_does_not_replace(self, maps):
        """OR REPLACE would collapse those same legitimate duplicates."""
        assert "OR REPLACE" not in database.insert_sql("corp", maps["corp"])

    def test_schema_is_valid_sql(self, maps):
        """Execute every CREATE against a real database."""
        db = sqlite3.connect(":memory:")
        for stem, field_map in maps.items():
            db.execute(database.create_table_sql(stem, field_map))
        db.close()


class TestIndexes:
    def test_id_is_indexed(self, maps):
        statements = database.index_statements("corp", maps["corp"])
        assert any('"corp_id"' in s for s in statements)

    def test_coordinates_get_a_composite_index(self, maps):
        statements = database.index_statements("corp", maps["corp"])
        composite = [s for s in statements if "corp_coordinates" in s]
        assert composite
        assert "coordinates_latitude" in composite[0]
        assert "coordinates_longitude" in composite[0]

    def test_skips_columns_a_table_lacks(self, maps):
        """officer has no city column, so no city index."""
        statements = database.index_statements("officer", maps["officer"])
        assert not any("city" in s for s in statements)

    def test_indexes_are_valid_sql(self, maps):
        db = sqlite3.connect(":memory:")
        for stem, field_map in maps.items():
            db.execute(database.create_table_sql(stem, field_map))
            for statement in database.index_statements(stem, field_map):
                db.execute(statement)
        db.close()


class TestCoercion:
    @pytest.mark.parametrize(
        "value,sql_type,expected",
        [
            ("", "TEXT", None),
            (None, "TEXT", None),
            ("Test", "TEXT", "Test"),
            ("5000", "INTEGER", 5000),
            ("true", "INTEGER", 1),
            ("false", "INTEGER", 0),
            ("nonsense", "INTEGER", None),
            ("37.5", "REAL", 37.5),
            ("nonsense", "REAL", None),
            ("23219", "TEXT", "23219"),
        ],
    )
    def test_coerce(self, value, sql_type, expected):
        assert database._coerce(value, sql_type) == expected

    def test_leading_zeros_survive_in_zip(self):
        """A ZIP stored as INTEGER would lose its leading zero."""
        assert database._coerce("02134", "TEXT") == "02134"


class TestRowValues:
    def test_splits_coordinates_into_lat_lon(self, maps):
        row = {
            name: "" for name, _ in [(f["alt_name"], None) for f in maps["corp"].fields]
        }
        row["coordinates"] = "[-77.4, 37.5]"
        values = database.row_values(row, maps["corp"])
        columns = [name for name, _ in database.columns_for(maps["corp"])]
        latitude = values[columns.index("coordinates_latitude")]
        longitude = values[columns.index("coordinates_longitude")]
        assert (latitude, longitude) == (37.5, -77.4)

    def test_missing_coordinates_are_null(self, maps):
        row = {"coordinates": ""}
        values = database.row_values(row, maps["corp"])
        columns = [name for name, _ in database.columns_for(maps["corp"])]
        assert values[columns.index("coordinates_latitude")] is None

    def test_malformed_coordinates_do_not_raise(self, maps):
        row = {"coordinates": "not json"}
        values = database.row_values(row, maps["corp"])
        columns = [name for name, _ in database.columns_for(maps["corp"])]
        assert values[columns.index("coordinates_latitude")] is None

    def test_value_count_matches_column_count(self, maps):
        for stem, field_map in maps.items():
            values = database.row_values({}, field_map)
            assert len(values) == len(database.columns_for(field_map)), stem


class TestLoader:
    def _write_csv(self, path, field_map, rows):
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=field_map.output_names, extrasaction="ignore"
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_loads_rows(self, tmp_path, maps):
        source = tmp_path / "corp.csv"
        self._write_csv(
            source,
            maps["corp"],
            [
                {"id": "1", "name": "One", "total_shares": "100"},
                {"id": "2", "name": "Two", "total_shares": "200"},
            ],
        )
        loader = database.Loader(str(tmp_path / "t.db"), maps)
        loader.create_schema(["corp"])
        assert loader.load_csv("corp", str(source)) == 2
        rows = loader.connection.execute(
            "SELECT name, total_shares FROM corp ORDER BY id"
        ).fetchall()
        assert rows == [("One", 100), ("Two", 200)]
        loader.close()

    def test_keeps_repeated_ids(self, tmp_path, maps):
        """The SCC's repeated entity rows must all survive the load."""
        source = tmp_path / "corp.csv"
        self._write_csv(
            source,
            maps["corp"],
            [
                {"id": "1", "name": "One", "agent_date": "2021-01-01"},
                {"id": "1", "name": "One", "agent_date": "2023-01-01"},
            ],
        )
        loader = database.Loader(str(tmp_path / "t.db"), maps)
        loader.create_schema(["corp"])
        loader.load_csv("corp", str(source))
        count = loader.connection.execute(
            "SELECT COUNT(*) FROM corp WHERE id = '1'"
        ).fetchone()[0]
        assert count == 2
        loader.close()

    def test_drop_makes_reloading_repeatable(self, tmp_path, maps):
        source = tmp_path / "corp.csv"
        self._write_csv(source, maps["corp"], [{"id": "1", "name": "One"}])
        path = str(tmp_path / "t.db")
        for _ in range(3):
            loader = database.Loader(path, maps)
            loader.drop("corp")
            loader.create_schema(["corp"])
            loader.load_csv("corp", str(source))
            count = loader.connection.execute("SELECT COUNT(*) FROM corp").fetchone()[0]
            loader.close()
        assert count == 1

    def test_reserved_word_column_is_queryable(self, tmp_path, maps):
        source = tmp_path / "corp.csv"
        self._write_csv(
            source,
            maps["corp"],
            [
                {"id": "1", "name": "One", "foreign": "true"},
            ],
        )
        loader = database.Loader(str(tmp_path / "t.db"), maps)
        loader.create_schema(["corp"])
        loader.load_csv("corp", str(source))
        value = loader.connection.execute('SELECT "foreign" FROM corp').fetchone()[0]
        assert value == 1
        loader.close()

    def test_row_counts(self, tmp_path, maps):
        source = tmp_path / "corp.csv"
        self._write_csv(source, maps["corp"], [{"id": "1", "name": "One"}])
        loader = database.Loader(str(tmp_path / "t.db"), maps)
        loader.create_schema(["corp"])
        loader.load_csv("corp", str(source))
        assert loader.row_counts()["corp"] == 1
        loader.close()


class TestAvailableStems:
    def test_finds_only_existing_csvs(self, tmp_path, maps):
        (tmp_path / "corp.csv").write_text("id\n")
        (tmp_path / "llc.csv").write_text("id\n")
        assert database.available_stems(maps, str(tmp_path)) == ["corp", "llc"]

    def test_empty_when_nothing_present(self, tmp_path, maps):
        assert database.available_stems(maps, str(tmp_path)) == []
