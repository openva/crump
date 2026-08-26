"""Tests for Census batch geocoding.

Response fixtures are real output from the Census batch API, captured while
geocoding SCC addresses.
"""

import io

import pytest

from crumplib import batch


class TestDirectionalConflict:
    def test_opposite_directions_conflict(self):
        """The case that motivated this guard: W matching E."""
        assert batch.directional_conflict(
            "204 W Washington St, Lexington, VA, 24450",
            "204 E WASHINGTON ST, LEXINGTON, VA, 24450",
        )

    def test_diagonal_opposites_conflict(self):
        assert batch.directional_conflict(
            "310 4th St NE, Charlottesville, VA",
            "310 4TH ST SE, CHARLOTTESVILLE, VA",
        )

    def test_spelled_out_matching_abbreviation_is_fine(self):
        assert not batch.directional_conflict(
            "265 EAST QUEENS DRIVE, WILLIAMSBURG, VA",
            "265 E QUEENS DR, WILLIAMSBURG, VA",
        )

    def test_added_directional_is_fine(self):
        """The geocoder disambiguating, not contradicting."""
        assert not batch.directional_conflict(
            "2424 Garden of the Gods Rd, Colorado Springs, CO",
            "2424 W GARDEN OF THE GODS RD, COLORADO SPRINGS, CO",
        )

    def test_no_directionals_is_fine(self):
        assert not batch.directional_conflict(
            "1290 Enterprise Dr, Lynchburg, VA",
            "1290 ENTERPRISE DR, LYNCHBURG, VA",
        )

    def test_only_the_street_portion_counts(self):
        """A city named West Something must not trip the check."""
        assert not batch.directional_conflict(
            "100 Main St, West Point, VA",
            "100 MAIN ST, WEST POINT, VA",
        )


class TestWriteBatch:
    def test_writes_five_columns_without_a_header(self):
        buffer = io.StringIO()
        count = batch.write_batch(
            [
                {
                    "id": "abc",
                    "street": "1 Main St",
                    "city": "Richmond",
                    "state": "VA",
                    "zip": "23219",
                }
            ],
            buffer,
        )
        assert count == 1
        assert buffer.getvalue().strip() == "abc,1 Main St,Richmond,VA,23219"

    def test_quotes_fields_containing_commas(self):
        buffer = io.StringIO()
        batch.write_batch(
            [
                {
                    "id": "1",
                    "street": "1 Main St, Ste 2",
                    "city": "Richmond",
                    "state": "VA",
                    "zip": "23219",
                }
            ],
            buffer,
        )
        assert '"1 Main St, Ste 2"' in buffer.getvalue()


class TestParseResponse:
    MATCH = (
        '"h1","1290 Enterprise Dr, Lynchburg, VA, 24502","Match","Exact",'
        '"1290 ENTERPRISE DR, LYNCHBURG, VA, 24502",'
        '"-79.241848851276,37.351958970746","62743304","R"'
    )
    NO_MATCH = '"h2","PO BOX 5005, ASHLAND, VA, 23005","No_Match"'
    TIE = '"h3","1850 WILLIAM PENN WAY, LANCASTER, PA, 17605","Tie"'
    CONFLICT = (
        '"h4","204 W Washington St, Lexington, VA, 24450","Match","Non_Exact",'
        '"204 E WASHINGTON ST, LEXINGTON, VA, 24450",'
        '"-79.439908264062,37.783870087549","63109356","R"'
    )

    def test_parses_a_match(self):
        matches, rejected = batch.parse_response(self.MATCH)
        assert not rejected
        assert matches["h1"]["latitude"] == pytest.approx(37.351958970746)
        assert matches["h1"]["longitude"] == pytest.approx(-79.241848851276)
        assert matches["h1"]["source"] == "Census"
        assert matches["h1"]["quality"] == "exact"

    def test_no_match_is_rejected_with_a_reason(self):
        """Unmatched rows have only three columns; indexing further would raise."""
        matches, rejected = batch.parse_response(self.NO_MATCH)
        assert matches == {}
        assert rejected["h2"] == "no_match"

    def test_tie_is_rejected(self):
        matches, rejected = batch.parse_response(self.TIE)
        assert matches == {}
        assert rejected["h3"] == "tie"

    def test_directional_conflict_rejected_by_default(self):
        matches, rejected = batch.parse_response(self.CONFLICT)
        assert matches == {}
        assert rejected["h4"] == "directional conflict"

    def test_directional_conflict_can_be_allowed(self):
        matches, _ = batch.parse_response(
            self.CONFLICT, reject_directional_conflicts=False
        )
        assert "h4" in matches

    def test_mixed_response(self):
        text = "\n".join([self.MATCH, self.NO_MATCH, self.TIE, self.CONFLICT])
        matches, rejected = batch.parse_response(text)
        assert set(matches) == {"h1"}
        assert set(rejected) == {"h2", "h3", "h4"}

    def test_ignores_blank_lines(self):
        matches, rejected = batch.parse_response(f"\n{self.MATCH}\n\n")
        assert len(matches) == 1

    def test_unparseable_coordinates_rejected(self):
        row = (
            '"h5","1 Main St, Richmond, VA, 23219","Match","Exact",'
            '"1 MAIN ST, RICHMOND, VA, 23219","not,numbers","1","R"'
        )
        matches, rejected = batch.parse_response(row)
        assert matches == {}
        assert rejected["h5"] == "unparseable coordinates"


class TestChunked:
    def test_splits_into_batches(self):
        assert [len(c) for c in batch.chunked(range(25), 10)] == [10, 10, 5]

    def test_exact_multiple(self):
        assert [len(c) for c in batch.chunked(range(20), 10)] == [10, 10]

    def test_empty(self):
        assert list(batch.chunked([], 10)) == []


class TestGeocodeBatch:
    def test_empty_input_makes_no_request(self):
        assert batch.geocode_batch([]) == ({}, {})

    def test_rejects_oversized_batch(self):
        rows = [
            {"id": str(i), "street": "x", "city": "", "state": "", "zip": ""}
            for i in range(batch.MAX_BATCH_SIZE + 1)
        ]
        with pytest.raises(batch.BatchError, match="exceeds the service limit"):
            batch.geocode_batch(rows)
