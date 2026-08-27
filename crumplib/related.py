"""On-disk index of related records, for attaching to entity documents.

Officers, name history, amendments and mergers are keyed by entity ID and need
to be looked up as each entity streams past. Holding them in a dict is the
obvious approach and what Crump used to do, but the four files total nearly two
million rows and cost about 850 MB -- more than the whole memory budget on a
small server.

So they go into a temporary SQLite database instead. Inserts are batched and the
index is built after loading, which keeps the write phase fast; lookups are then
a single indexed query per entity. Peak memory stays flat regardless of how many
related records there are.

The database is temporary and deleted on close. It is a cache, not an output --
`db_load` builds the durable one.
"""

import json
import os
import sqlite3
import tempfile

from .output import json_default

#: Rows per INSERT batch. Large enough to amortize the statement overhead,
#: small enough that the batch itself stays trivial in memory.
BATCH_SIZE = 10000


class RelatedStore:
    """Related records keyed by entity ID, held on disk.

    Records are stored as serialized JSON rather than columns: the four related
    types have different shapes, and this layer only ever hands them back
    whole. That keeps one table for everything and avoids a schema per type.
    """

    def __init__(self, path=None, keep=False):
        #: Where the temporary database lives. A caller can pass a path to
        #: inspect it; otherwise it is created in the system temp directory.
        self._temporary = path is None
        if self._temporary:
            handle, path = tempfile.mkstemp(prefix="crump-related-", suffix=".db")
            os.close(handle)
        self.path = path
        self.keep = keep
        self.counts = {}

        self._connection = sqlite3.connect(self.path)
        # This database is disposable: if the run dies we rebuild it, so
        # durability guarantees are pure cost here.
        self._connection.execute("PRAGMA journal_mode = OFF")
        self._connection.execute("PRAGMA synchronous = OFF")
        self._connection.execute("PRAGMA temp_store = MEMORY")
        self._connection.execute(
            "CREATE TABLE related ("
            "  entity_id TEXT NOT NULL,"
            "  kind TEXT NOT NULL,"
            "  payload TEXT NOT NULL"
            ")"
        )
        self._indexed = False

    def add_all(self, kind, key_field, records, drop_key=True):
        """Load one related type. Returns the number of rows stored.

        `records` is an iterable of normalized records, so an atomized officer
        looks exactly like a row in officer.csv.
        """
        batch = []
        stored = 0
        entities = set()

        for record in records:
            entity_id = record.get(key_field)
            if not entity_id:
                continue
            if drop_key:
                # The entity ID is already on the parent document; repeating it
                # on every nested record is noise.
                record = {k: v for k, v in record.items() if k != key_field}
            batch.append(
                (
                    entity_id,
                    kind,
                    json.dumps(record, default=json_default),
                )
            )
            entities.add(entity_id)
            if len(batch) >= BATCH_SIZE:
                self._insert(batch)
                stored += len(batch)
                batch = []

        if batch:
            self._insert(batch)
            stored += len(batch)

        self._connection.commit()
        self.counts[kind] = len(entities)
        self._indexed = False
        return stored

    def _insert(self, batch):
        self._connection.executemany("INSERT INTO related VALUES (?, ?, ?)", batch)

    def index(self):
        """Build the lookup index. Deliberately after loading, not during."""
        if self._indexed:
            return
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS related_entity ON related (entity_id, kind)"
        )
        self._connection.commit()
        self._indexed = True

    def entities(self, kind):
        """How many distinct entities have records of this type."""
        return self.counts.get(kind, 0)

    def fetch(self, entity_id):
        """All related records for one entity, as {kind: [record, ...]}.

        Returns an empty dict when the entity has none, which is the common
        case -- most businesses have no officers or amendments on file.
        """
        self.index()
        grouped = {}
        for kind, payload in self._connection.execute(
            "SELECT kind, payload FROM related WHERE entity_id = ?",
            (entity_id,),
        ):
            grouped.setdefault(kind, []).append(json.loads(payload))
        return grouped

    def close(self):
        """Close and delete the temporary database."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._temporary and not self.keep:
            try:
                os.remove(self.path)
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()
        return False
