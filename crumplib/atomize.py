"""Writing one JSON file per entity, for serving a static API from S3.

The output is a flat namespace keyed by entity ID, sharded into subdirectories.
Sharding matters: S3 itself is happy with millions of keys under one prefix, but
`aws s3 sync`, `ls`, and most filesystems are not, and 2 million files in a
single directory makes the tree unusable for the humans who have to operate it.

Entity IDs are unique across all six entity types -- verified across the full
feed -- so a single namespace is safe and callers don't need to know whether an
ID belongs to an LLC or a corporation.
"""

import csv
import json
import os

from .output import json_default

#: Characters an entity ID may contain. IDs are digits with an optional leading
#: letter (e.g. '00000307', 'T0836306', 'F0071623'), but we validate rather than
#: trust, since these become filesystem paths.
_SAFE_ID = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

#: How many leading characters of the ID name the shard directory.
#:
#: Four, not two. Entity IDs cluster hard by issue era: at depth 2 the '11'
#: shard alone held 849,148 of 2,093,343 files -- 40% of everything in one
#: directory, which is exactly the problem sharding is meant to solve. Measured
#: over the full feed:
#:
#:     depth 2:     31 shards, largest 869,397 files
#:     depth 3:    223 shards, largest  89,029 files
#:     depth 4:  2,136 shards, largest   9,110 files
#:
#: Depth 4 keeps every shard small enough to list and sync comfortably.
SHARD_DEPTH = 4


class UnsafeIdentifier(ValueError):
    """An entity ID that cannot be used as a path component."""


def safe_id(entity_id):
    """Validate an entity ID for use in a path. Raises on anything suspect."""
    cleaned = (entity_id or "").strip().upper()
    if not cleaned:
        raise UnsafeIdentifier("empty entity ID")
    if not set(cleaned) <= _SAFE_ID:
        raise UnsafeIdentifier(f"unsafe entity ID: {entity_id!r}")
    return cleaned


def shard_for(entity_id):
    """The shard directory name for an ID, e.g. '00000307' -> '00'."""
    cleaned = safe_id(entity_id)
    return cleaned[:SHARD_DEPTH].ljust(SHARD_DEPTH, "_")


def path_for(entity_id, root):
    """Full path of the JSON file for one entity."""
    cleaned = safe_id(entity_id)
    return os.path.join(root, shard_for(cleaned), cleaned + ".json")


class Atomizer:
    """Writes one JSON file per entity, sharded by ID prefix.

    Writes are content-aware: a file whose contents already match is left
    alone, mtime included. That matters because `aws s3 sync` decides what to
    upload by comparing size and modification time, so rewriting an unchanged
    file makes it look newer and forces a pointless upload. Only about 0.5% of
    entities change status in a given week, so rewriting all 2 million meant
    re-uploading the entire API to publish a few thousand changes.

    Skipping the write is also *faster* than doing it -- avoiding the disk
    flush more than pays for the read -- so this costs nothing in the steady
    state.

    Entities are written as they stream past. Related records (officers, name
    history, and so on) are attached before the record arrives here.
    """

    def __init__(
        self, root, indent=None, always_write=False, deferred=None, track_ids=False
    ):
        self.root = root
        self.indent = indent
        #: Set to bypass the content check, e.g. to force a full rewrite.
        self.always_write = always_write
        #: Entity ids known to appear on more than one source row. Only these
        #: need buffering; everything else can be written the moment it
        #: arrives. Pass `None` to buffer everything, which is correct but
        #: needs ~2.2 GB for the full feed.
        self.deferred = deferred
        #: Only collected when --prune needs them: retaining every id costs
        #: ~170 MB for the full feed, which matters on a small server.
        self.track_ids = track_ids
        self.written = 0
        self.unchanged = 0
        self.skipped = 0
        self.ids = set()
        self._made = set()
        #: Final content for deferred entities only, held until flush().
        self._pending = {}

    def _ensure_shard(self, shard):
        if shard not in self._made:
            os.makedirs(os.path.join(self.root, shard), exist_ok=True)
            self._made.add(shard)

    def write(self, entity_id, record):
        """Write an entity's JSON file, or defer it if the entity repeats.

        The SCC ships several rows for one entity when registered-agent or
        merger history differs, and the last row is its real content. Writing
        an intermediate row would put the wrong content on disk -- and worse,
        which row won varied between runs, so those files oscillated and
        re-uploaded every week forever.

        Buffering every entity would fix that but costs ~2.2 GB for the full
        feed. Since only ~1.8% of entities repeat, `deferred` names just those
        and the other 98% are written straight through.
        """
        try:
            cleaned = safe_id(entity_id)
        except UnsafeIdentifier:
            self.skipped += 1
            return None

        if self.track_ids:
            self.ids.add(cleaned)
        payload = json.dumps(record, default=json_default, indent=self.indent)

        if self.deferred is None or cleaned in self.deferred:
            self._pending[cleaned] = payload
        else:
            self._write(cleaned, payload)
        return path_for(cleaned, self.root)

    def _write(self, entity_id, payload):
        """Write one entity, skipping the write if nothing changed."""
        path = path_for(entity_id, self.root)
        if not self.always_write and self._read(path) == payload:
            self.unchanged += 1
            return
        self._ensure_shard(shard_for(entity_id))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
        self.written += 1

    def flush(self):
        """Write every pending entity whose content differs from disk.

        Unchanged files are left completely alone, mtime included, so
        `aws s3 sync` skips them: it decides what to upload by comparing size
        and modification time, and rewriting an unchanged file makes it look
        newer. Only ~0.5% of entities change status in a week, so rewriting all
        two million meant re-uploading the whole API to publish a few thousand
        changes.
        """
        for entity_id, payload in self._pending.items():
            self._write(entity_id, payload)
        self._pending.clear()

    def _read(self, path):
        """The file's current contents, or None if absent or unreadable."""
        try:
            with open(path, encoding="utf-8") as handle:
                return handle.read()
        except (FileNotFoundError, NotADirectoryError):
            return None
        except OSError:
            # Unreadable for any other reason: treat as absent and rewrite.
            return None

    def write_index(self, entity_ids, name="index.json"):
        """Write a manifest of every entity ID, for consumers that need a list."""
        os.makedirs(self.root, exist_ok=True)
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {"count": len(entity_ids), "entities": sorted(entity_ids)},
                handle,
                default=json_default,
            )
        return path


def stale_files(root, current_ids):
    """Entity files on disk that are no longer in the feed.

    Returns paths for IDs absent from `current_ids`. These are entities the SCC
    has stopped publishing -- typically long-terminated ones purged from the
    bulk export.
    """
    stale = []
    if not os.path.isdir(root):
        return stale
    for shard in os.listdir(root):
        shard_path = os.path.join(root, shard)
        if not os.path.isdir(shard_path):
            continue
        for name in os.listdir(shard_path):
            if not name.endswith(".json"):
                continue
            if name[: -len(".json")] not in current_ids:
                stale.append(os.path.join(shard_path, name))
    return stale


def prune(root, current_ids):
    """Delete entity files no longer in the feed. Returns the count removed.

    Only safe to call after a complete run: with a partial one, most of the
    corpus looks stale and this would delete the API.
    """
    removed = 0
    for path in stale_files(root, current_ids):
        try:
            os.remove(path)
            removed += 1
        except OSError:
            continue
    return removed


def repeated_ids(paths, id_column=0):
    """Entity ids appearing on more than one row across the given CSVs.

    A cheap first pass so `Atomizer` knows which entities need buffering. Reads
    only the first column and holds ids, not records: about 5 seconds and ~70 MB
    transiently for the full feed, versus ~2.2 GB to buffer every record.

    Returns just the repeated ids -- roughly 1.8% of the feed, a couple of
    megabytes -- and discards the full id set before returning.
    """
    # Holding every id costs ~170 MB on the full feed. Hash them into fixed-width
    # ints instead: same duplicate detection, a fraction of the memory, and the
    # occasional hash collision only means an entity is buffered unnecessarily --
    # which is harmless, since buffering is the safe behaviour.
    seen = set()
    repeated = set()
    for path in paths:
        try:
            handle = open(path, encoding="utf-8", errors="replace", newline="")
        except OSError:
            continue
        with handle:
            reader = csv.reader(handle)
            next(reader, None)  # header
            for row in reader:
                if not row:
                    continue
                entity_id = row[id_column].strip().lstrip("\t").strip()
                if not entity_id:
                    continue
                fingerprint = hash(entity_id)
                if fingerprint in seen:
                    repeated.add(entity_id)
                else:
                    seen.add(fingerprint)
    return repeated
