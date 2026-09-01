"""Tests for per-entity JSON output.

These files become a public static API on S3, so the path-safety tests matter
more than usual: an entity ID reaches the filesystem as a path component.
"""

import json
import os

import pytest

from crumplib.atomize import (
    SHARD_DEPTH,
    Atomizer,
    UnsafeIdentifier,
    path_for,
    prune,
    safe_id,
    shard_for,
    stale_files,
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
        subject.flush()
        written = tmp_path / "00000307"[:SHARD_DEPTH] / "00000307.json"
        assert written.is_file()
        assert json.loads(written.read_text())["name"] == "Test"

    def test_serializes_dates(self, tmp_path):
        import datetime

        subject = Atomizer(str(tmp_path))
        subject.write("1", {"id": "1", "d": datetime.date(2024, 1, 2)})
        subject.flush()
        shard = "1".ljust(SHARD_DEPTH, "_")
        written = json.loads((tmp_path / shard / "1.json").read_text())
        assert written["d"] == "2024-01-02"

    def test_counts_written(self, tmp_path):
        subject = Atomizer(str(tmp_path))
        subject.write("00000307", {})
        subject.write("00000308", {})
        subject.flush()
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
        subject.flush()
        assert {p.name for p in tmp_path.iterdir()} == {i[:SHARD_DEPTH] for i in ids}

    def test_index_lists_every_entity(self, tmp_path):
        subject = Atomizer(str(tmp_path))
        subject.write_index(["00000002", "00000001"])
        index = json.loads((tmp_path / "index.json").read_text())
        assert index["count"] == 2
        assert index["entities"] == ["00000001", "00000002"]


class TestContentAwareWrites:
    """Unchanged files must not be touched.

    `aws s3 sync` decides what to upload by comparing size and modification
    time. Rewriting an unchanged file makes it look newer, which forced a
    re-upload of all two million files to publish a few thousand changes.
    """

    def test_unchanged_file_is_not_rewritten(self, tmp_path):
        record = {"id": "00000307", "status": "ACTIVE"}
        first = Atomizer(str(tmp_path))
        first.write("00000307", record)
        first.flush()
        path = tmp_path / "00000307"[:SHARD_DEPTH] / "00000307.json"
        before = path.stat().st_mtime_ns

        second = Atomizer(str(tmp_path))
        second.write("00000307", record)
        second.flush()

        assert path.stat().st_mtime_ns == before
        assert (second.written, second.unchanged) == (0, 1)

    def test_changed_file_is_rewritten(self, tmp_path):
        first = Atomizer(str(tmp_path))
        first.write("00000307", {"id": "00000307", "status": "ACTIVE"})
        first.flush()

        second = Atomizer(str(tmp_path))
        second.write("00000307", {"id": "00000307", "status": "VOIDED"})
        second.flush()

        assert (second.written, second.unchanged) == (1, 0)
        path = tmp_path / "00000307"[:SHARD_DEPTH] / "00000307.json"
        assert "VOIDED" in path.read_text()

    def test_repeated_rows_settle_on_the_last_one(self, tmp_path):
        """The SCC ships several rows per entity; the last is its content.

        Writing as rows arrived let an intermediate row reach disk, and which
        one won varied between runs -- so 460 files flipped back and forth on
        every run and re-uploaded forever.
        """
        subject = Atomizer(str(tmp_path))
        subject.write("00000307", {"id": "00000307", "merged": "S"})
        subject.write("00000307", {"id": "00000307", "merged": "N"})
        subject.flush()
        path = tmp_path / "00000307"[:SHARD_DEPTH] / "00000307.json"
        assert json.loads(path.read_text())["merged"] == "N"
        assert subject.written == 1

    def test_repeated_rows_are_stable_across_runs(self, tmp_path):
        """The regression that mattered: no oscillation between runs."""
        rows = [
            {"id": "00000307", "merged": "S"},
            {"id": "00000307", "merged": "N"},
        ]
        first = Atomizer(str(tmp_path))
        for row in rows:
            first.write("00000307", row)
        first.flush()

        second = Atomizer(str(tmp_path))
        for row in rows:
            second.write("00000307", row)
        second.flush()
        assert (second.written, second.unchanged) == (0, 1)

    def test_force_rewrite_ignores_the_content_check(self, tmp_path):
        record = {"id": "00000307", "status": "ACTIVE"}
        first = Atomizer(str(tmp_path))
        first.write("00000307", record)
        first.flush()

        forced = Atomizer(str(tmp_path), always_write=True)
        forced.write("00000307", record)
        forced.flush()
        assert (forced.written, forced.unchanged) == (1, 0)

    def test_ids_are_tracked_for_pruning(self, tmp_path):
        """Opt-in: retaining every id costs ~170 MB on the full feed."""
        subject = Atomizer(str(tmp_path), track_ids=True)
        subject.write("00000307", {})
        subject.write("00000308", {})
        assert subject.ids == {"00000307", "00000308"}

    def test_ids_are_not_tracked_by_default(self, tmp_path):
        subject = Atomizer(str(tmp_path))
        subject.write("00000307", {})
        assert subject.ids == set()


class TestPruning:
    def _populate(self, tmp_path, ids):
        subject = Atomizer(str(tmp_path))
        for entity_id in ids:
            subject.write(entity_id, {"id": entity_id})
        subject.flush()
        return subject

    def test_finds_files_no_longer_in_the_feed(self, tmp_path):
        self._populate(tmp_path, ["00000001", "00000002", "00000003"])
        stale = stale_files(str(tmp_path), {"00000001", "00000002"})
        assert [os.path.basename(p) for p in stale] == ["00000003.json"]

    def test_nothing_stale_when_all_present(self, tmp_path):
        ids = {"00000001", "00000002"}
        self._populate(tmp_path, sorted(ids))
        assert stale_files(str(tmp_path), ids) == []

    def test_prune_removes_only_the_stale(self, tmp_path):
        self._populate(tmp_path, ["00000001", "00000002", "00000003"])
        assert prune(str(tmp_path), {"00000001", "00000002"}) == 1
        remaining = {name for _, _, files in os.walk(tmp_path) for name in files}
        assert remaining == {"00000001.json", "00000002.json"}

    def test_missing_directory_is_not_an_error(self, tmp_path):
        assert stale_files(str(tmp_path / "nope"), set()) == []
        assert prune(str(tmp_path / "nope"), set()) == 0

    def test_ignores_non_json_files(self, tmp_path):
        self._populate(tmp_path, ["00000001"])
        (tmp_path / "index.txt").write_text("not an entity")
        assert stale_files(str(tmp_path), {"00000001"}) == []
