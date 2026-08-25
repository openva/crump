"""Writing one JSON file per entity, for serving a static API from S3.

The output is a flat namespace keyed by entity ID, sharded into subdirectories.
Sharding matters: S3 itself is happy with millions of keys under one prefix, but
`aws s3 sync`, `ls`, and most filesystems are not, and 2 million files in a
single directory makes the tree unusable for the humans who have to operate it.

Entity IDs are unique across all six entity types -- verified across the full
feed -- so a single namespace is safe and callers don't need to know whether an
ID belongs to an LLC or a corporation.
"""

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

    Entities are written as they stream past. Related records (officers, name
    history, and so on) are attached by `attach`, which is why atomizing runs
    after the main pass rather than during it.
    """

    def __init__(self, root, indent=None):
        self.root = root
        self.indent = indent
        self.written = 0
        self.skipped = 0
        self._made = set()

    def _ensure_shard(self, shard):
        if shard not in self._made:
            os.makedirs(os.path.join(self.root, shard), exist_ok=True)
            self._made.add(shard)

    def write(self, entity_id, record):
        """Write one entity's JSON file. Returns the path, or None if skipped."""
        try:
            cleaned = safe_id(entity_id)
        except UnsafeIdentifier:
            self.skipped += 1
            return None

        self._ensure_shard(shard_for(cleaned))
        path = path_for(cleaned, self.root)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, default=json_default, indent=self.indent)
        self.written += 1
        return path

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


def group_related(path, key_field, reader, drop_key=True):
    """Index a related-record CSV by entity ID.

    Returns {entity_id: [record, ...]}. Held in memory because the related
    files are small next to the entity files -- Officer.csv is the largest at
    1.2M rows -- and one pass beats re-scanning per entity.
    """
    grouped = {}
    for record in reader:
        entity_id = record.get(key_field)
        if not entity_id:
            continue
        if drop_key:
            record = {k: v for k, v in record.items() if k != key_field}
        grouped.setdefault(entity_id, []).append(record)
    return grouped
