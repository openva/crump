"""Tests for per-entity JSON output.

These files become a public static API on S3, so the path-safety tests matter
more than usual: an entity ID reaches the filesystem as a path component.
"""

import json

import pytest

from crumplib.atomize import (
    SHARD_DEPTH,
    Atomizer,
    UnsafeIdentifier,
    group_related,
    path_for,
    safe_id,
    shard_for,
)


class TestSafeId:
    def test_accepts_numeric_id(self):
        assert safe_id("00000307") == "00000307"

    def test_accepts_letter_prefixed_id(self):
        # Real IDs in the feed: T0836306, F0071623.
        assert safe_id("T0836306") == "T0836306"

    def test_strips_and_uppercases(self):
        assert safe_id("  t0836306 ") == "T0836306"

    @pytest.mark.parametrize(
        "value",
        ["", "   ", "../etc/passwd", "a/b", "a\\b", "ab*", "a b", ".", ".."],
    )
    def test_rejects_unsafe(self, value):
        with pytest.raises(UnsafeIdentifier):
            safe_id(value)

    def test_rejects_none(self):
        with pytest.raises(UnsafeIdentifier):
            safe_id(None)


class TestSharding:
    def test_shard_is_id_prefix(self):
        assert shard_for("00000307") == "00000307"[:SHARD_DEPTH]
        assert shard_for("T0836306") == "T0836306"[:SHARD_DEPTH]

    def test_short_id_is_padded(self):
        assert shard_for("7") == "7".ljust(SHARD_DEPTH, "_")

    def test_path_includes_shard(self):
        expected = f"out/{'00000307'[:SHARD_DEPTH]}/00000307.json"
        assert path_for("00000307", "out") == expected

    def test_depth_keeps_shards_small(self):
        """Depth 2 put 40% of all files in the '11' shard; 4 fixes that."""
        assert SHARD_DEPTH >= 4

    def test_path_rejects_traversal(self):
        with pytest.raises(UnsafeIdentifier):
            path_for("../../etc/passwd", "out")


class TestAtomizer:
    def test_writes_one_file_per_entity(self, tmp_path):
        subject = Atomizer(str(tmp_path))
        subject.write("00000307", {"id": "00000307", "name": "Test"})
        written = tmp_path / "00000307"[:SHARD_DEPTH] / "00000307.json"
        assert written.is_file()
        assert json.loads(written.read_text())["name"] == "Test"

    def test_serializes_dates(self, tmp_path):
        import datetime

        subject = Atomizer(str(tmp_path))
        subject.write("1", {"id": "1", "d": datetime.date(2024, 1, 2)})
        shard = "1".ljust(SHARD_DEPTH, "_")
        written = json.loads((tmp_path / shard / "1.json").read_text())
        assert written["d"] == "2024-01-02"

    def test_counts_written(self, tmp_path):
        subject = Atomizer(str(tmp_path))
        subject.write("00000307", {})
        subject.write("00000308", {})
        assert subject.written == 2

    def test_skips_unusable_id_without_raising(self, tmp_path):
        """A bad ID must not abort a two-million-record run."""
        subject = Atomizer(str(tmp_path))
        assert subject.write("../evil", {}) is None
        assert subject.write(None, {}) is None
        assert (subject.written, subject.skipped) == (0, 2)

    def test_shards_spread_across_directories(self, tmp_path):
        subject = Atomizer(str(tmp_path))
        ids = ("00000001", "01000002", "T0000003")
        for entity_id in ids:
            subject.write(entity_id, {})
        assert {p.name for p in tmp_path.iterdir()} == {
            i[:SHARD_DEPTH] for i in ids
        }

    def test_index_lists_every_entity(self, tmp_path):
        subject = Atomizer(str(tmp_path))
        subject.write_index(["00000002", "00000001"])
        index = json.loads((tmp_path / "index.json").read_text())
        assert index["count"] == 2
        assert index["entities"] == ["00000001", "00000002"]


class TestGroupRelated:
    def test_groups_by_key(self):
        rows = [
            {"id": "1", "last_name": "A"},
            {"id": "2", "last_name": "B"},
            {"id": "1", "last_name": "C"},
        ]
        grouped = group_related(None, "id", iter(rows))
        assert len(grouped["1"]) == 2
        assert len(grouped["2"]) == 1

    def test_drops_the_join_key(self):
        """The entity ID is already on the parent; repeating it is noise."""
        grouped = group_related(None, "id", iter([{"id": "1", "x": "y"}]))
        assert grouped["1"] == [{"x": "y"}]

    def test_keeps_key_when_asked(self):
        grouped = group_related(
            None, "id", iter([{"id": "1", "x": "y"}]), drop_key=False
        )
        assert grouped["1"] == [{"id": "1", "x": "y"}]

    def test_ignores_rows_without_a_key(self):
        grouped = group_related(None, "id", iter([{"id": "", "x": "y"}]))
        assert grouped == {}
