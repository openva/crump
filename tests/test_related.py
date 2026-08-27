"""Tests for the on-disk related-record index.

Officers, name history, amendments and mergers used to be held in a dict, which
cost ~850 MB for the full feed -- more than the memory budget on a small
server. These guard the replacement's behaviour and its cleanup.
"""

import os

from crumplib.related import RelatedStore


class TestAddAndFetch:
    def test_groups_by_entity(self):
        with RelatedStore() as store:
            store.add_all(
                "officers",
                "id",
                [
                    {"id": "1", "last_name": "A"},
                    {"id": "1", "last_name": "B"},
                    {"id": "2", "last_name": "C"},
                ],
            )
            assert len(store.fetch("1")["officers"]) == 2
            assert len(store.fetch("2")["officers"]) == 1

    def test_returns_row_count(self):
        with RelatedStore() as store:
            assert store.add_all("officers", "id", [{"id": "1"}, {"id": "2"}]) == 2

    def test_counts_distinct_entities(self):
        with RelatedStore() as store:
            store.add_all("officers", "id", [{"id": "1"}, {"id": "1"}, {"id": "2"}])
            assert store.entities("officers") == 2

    def test_several_kinds_coexist(self):
        with RelatedStore() as store:
            store.add_all("officers", "id", [{"id": "1", "last_name": "A"}])
            store.add_all("mergers", "id", [{"id": "1", "merger_type": "s"}])
            fetched = store.fetch("1")
            assert set(fetched) == {"officers", "mergers"}

    def test_unknown_entity_returns_empty(self):
        """Most businesses have no officers or amendments on file."""
        with RelatedStore() as store:
            store.add_all("officers", "id", [{"id": "1"}])
            assert store.fetch("9") == {}

    def test_drops_the_join_key(self):
        """The entity id is on the parent; repeating it is noise."""
        with RelatedStore() as store:
            store.add_all("officers", "id", [{"id": "1", "last_name": "A"}])
            assert store.fetch("1")["officers"] == [{"last_name": "A"}]

    def test_keeps_key_when_asked(self):
        with RelatedStore() as store:
            store.add_all(
                "officers", "id", [{"id": "1", "last_name": "A"}], drop_key=False
            )
            assert store.fetch("1")["officers"][0]["id"] == "1"

    def test_ignores_rows_without_a_key(self):
        with RelatedStore() as store:
            store.add_all("officers", "id", [{"id": "", "last_name": "A"}])
            assert store.entities("officers") == 0

    def test_preserves_row_order_within_an_entity(self):
        with RelatedStore() as store:
            store.add_all(
                "officers",
                "id",
                [
                    {"id": "1", "last_name": "First"},
                    {"id": "1", "last_name": "Second"},
                ],
            )
            names = [r["last_name"] for r in store.fetch("1")["officers"]]
            assert names == ["First", "Second"]

    def test_serializes_dates(self):
        import datetime

        with RelatedStore() as store:
            store.add_all(
                "amendments",
                "id",
                [{"id": "1", "amendment_date": datetime.date(2024, 1, 2)}],
            )
            record = store.fetch("1")["amendments"][0]
            assert record["amendment_date"] == "2024-01-02"

    def test_crosses_the_insert_batch_boundary(self):
        """More rows than BATCH_SIZE must all survive."""
        from crumplib.related import BATCH_SIZE

        count = BATCH_SIZE + 250
        with RelatedStore() as store:
            stored = store.add_all(
                "officers",
                "id",
                ({"id": "1", "n": str(i)} for i in range(count)),
            )
            assert stored == count
            assert len(store.fetch("1")["officers"]) == count


class TestLifecycle:
    def test_temporary_file_is_removed_on_close(self):
        store = RelatedStore()
        path = store.path
        assert os.path.exists(path)
        store.close()
        assert not os.path.exists(path)

    def test_close_is_idempotent(self):
        store = RelatedStore()
        store.close()
        store.close()

    def test_keep_preserves_the_file(self):
        store = RelatedStore(keep=True)
        path = store.path
        store.close()
        assert os.path.exists(path)
        os.remove(path)

    def test_context_manager_cleans_up(self):
        with RelatedStore() as store:
            path = store.path
        assert not os.path.exists(path)

    def test_explicit_path_is_left_alone(self, tmp_path):
        target = tmp_path / "related.db"
        store = RelatedStore(str(target))
        store.close()
        assert target.exists()

    def test_fetch_indexes_lazily(self):
        """fetch() builds the index if the caller forgot to."""
        with RelatedStore() as store:
            store.add_all("officers", "id", [{"id": "1", "last_name": "A"}])
            assert store.fetch("1")["officers"]
