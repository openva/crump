"""Tests for per-locality business lists.

These files go to municipal licensure departments, so the filename must be
unambiguous and the contents must not silently mix localities.
"""

import csv

import pytest

from crumplib.localities import (
    COLUMNS,
    ENTITY_STEMS,
    LocalityWriter,
    filename_for,
    row_for,
)


class TestFilename:
    def test_basic(self):
        assert filename_for("51003", "Albemarle County") == (
            "51003-Albemarle-County.csv"
        )

    def test_independent_city_keeps_its_suffix(self):
        assert filename_for("51760", "Richmond city") == "51760-Richmond-city.csv"

    def test_county_and_city_of_the_same_name_differ(self):
        """Fairfax, Franklin, Richmond and Roanoke are each both a county and
        a city. Without the suffix the two files would look identical.
        """
        county = filename_for("51059", "Fairfax County")
        city = filename_for("51600", "Fairfax city")
        assert county != city
        assert "County" in county
        assert "city" in city

    def test_spaces_become_hyphens(self):
        assert filename_for("51097", "King and Queen County") == (
            "51097-King-and-Queen-County.csv"
        )

    def test_punctuation_is_stripped(self):
        assert filename_for("51001", "O'Brien County.") == ("51001-O-Brien-County.csv")

    def test_fips_leads_so_files_sort_stably(self):
        names = [
            filename_for("51003", "Albemarle County"),
            filename_for("51001", "Accomack County"),
        ]
        assert sorted(names)[0].startswith("51001")


class TestRowFor:
    def _record(self, **overrides):
        record = {
            "id": "11683582",
            "name": "Test Company LLC",
            "status": "ACTIVE",
            "status_reason": "Active and In Good Standing",
            "status_date": "2024-04-15",
            "incorporation_date": "2020-01-01",
            "street_1": "1 Main St",
            "street_2": "",
            "city": "Richmond",
            "state": "Virginia",
            "zip": "23219",
            "coordinates": [-77.436, 37.5407],
            "fips": "51760",
            "jurisdiction": "Richmond city",
        }
        record.update(overrides)
        return record

    def test_has_every_column(self):
        row = row_for(self._record(), "llc")
        assert set(row) == set(COLUMNS)

    def test_entity_type_is_recorded(self):
        """All six types share a file, so the reader needs to tell them apart."""
        assert row_for(self._record(), "llc")["entity_type"] == "llc"
        assert row_for(self._record(), "corp")["entity_type"] == "corp"

    def test_splits_coordinates(self):
        row = row_for(self._record(), "llc")
        assert row["latitude"] == "37.540700"
        assert row["longitude"] == "-77.436000"

    def test_missing_coordinates_are_blank(self):
        row = row_for(self._record(coordinates=None), "llc")
        assert row["latitude"] == ""
        assert row["longitude"] == ""

    def test_dates_render_as_iso(self):
        import datetime

        row = row_for(self._record(status_date=datetime.date(2024, 4, 15)), "llc")
        assert row["status_date"] == "2024-04-15"

    def test_none_becomes_empty_string(self):
        row = row_for(self._record(status_reason=None, street_2=None), "llc")
        assert row["status_reason"] == ""
        assert row["street_2"] == ""

    def test_excludes_registered_agent(self):
        """An agent is usually a law firm at an unrelated address."""
        assert not any(column.startswith("agent") for column in COLUMNS)


class TestLocalityWriter:
    def _record(self, fips, jurisdiction, **overrides):
        record = {
            "id": "1",
            "name": "Test",
            "status": "ACTIVE",
            "status_reason": "",
            "status_date": "",
            "incorporation_date": "",
            "street_1": "1 Main St",
            "street_2": "",
            "city": "Richmond",
            "state": "Virginia",
            "zip": "23219",
            "coordinates": [-77.4, 37.5],
            "fips": fips,
            "jurisdiction": jurisdiction,
        }
        record.update(overrides)
        return record

    def test_writes_one_file_per_locality(self, tmp_path):
        writer = LocalityWriter(str(tmp_path))
        writer.write(self._record("51760", "Richmond city"), "corp")
        writer.write(self._record("51059", "Fairfax County"), "llc")
        writer.close()
        assert {p.name for p in tmp_path.iterdir()} == {
            "51760-Richmond-city.csv",
            "51059-Fairfax-County.csv",
        }

    def test_appends_to_the_same_locality(self, tmp_path):
        writer = LocalityWriter(str(tmp_path))
        for _ in range(3):
            writer.write(self._record("51760", "Richmond city"), "corp")
        writer.close()
        rows = list(
            csv.DictReader(open(tmp_path / "51760-Richmond-city.csv", newline=""))
        )
        assert len(rows) == 3

    def test_merges_entity_types_into_one_file(self, tmp_path):
        writer = LocalityWriter(str(tmp_path))
        writer.write(self._record("51760", "Richmond city"), "corp")
        writer.write(self._record("51760", "Richmond city"), "llc")
        writer.close()
        rows = list(
            csv.DictReader(open(tmp_path / "51760-Richmond-city.csv", newline=""))
        )
        assert {r["entity_type"] for r in rows} == {"corp", "llc"}

    def test_header_is_written_once(self, tmp_path):
        writer = LocalityWriter(str(tmp_path))
        writer.write(self._record("51760", "Richmond city"), "corp")
        writer.write(self._record("51760", "Richmond city"), "corp")
        writer.close()
        text = (tmp_path / "51760-Richmond-city.csv").read_text()
        assert text.count("entity_type") == 1

    def test_skips_records_without_a_jurisdiction(self, tmp_path):
        """Ungeocoded or out-of-state businesses have no locality file."""
        writer = LocalityWriter(str(tmp_path))
        assert writer.write(self._record(None, None), "corp") is False
        writer.close()
        assert list(tmp_path.iterdir()) == []
        assert writer.skipped == 1

    def test_counts_per_locality(self, tmp_path):
        writer = LocalityWriter(str(tmp_path))
        writer.write(self._record("51760", "Richmond city"), "corp")
        writer.write(self._record("51760", "Richmond city"), "llc")
        writer.write(self._record("51059", "Fairfax County"), "corp")
        counts = writer.counts()
        writer.close()
        assert counts["51760"] == ("Richmond city", 2)
        assert counts["51059"] == ("Fairfax County", 1)

    def test_all_statuses_are_included(self, tmp_path):
        """Terminated entities are kept; the status column lets a clerk filter."""
        writer = LocalityWriter(str(tmp_path))
        writer.write(self._record("51760", "Richmond city", status="ACTIVE"), "corp")
        writer.write(self._record("51760", "Richmond city", status="INACTIVE"), "corp")
        writer.close()
        rows = list(
            csv.DictReader(open(tmp_path / "51760-Richmond-city.csv", newline=""))
        )
        assert {r["status"] for r in rows} == {"ACTIVE", "INACTIVE"}


class TestEntityStems:
    def test_covers_all_six_business_types(self):
        assert set(ENTITY_STEMS) == {"corp", "llc", "lp", "gp", "bt", "psa"}

    @pytest.mark.parametrize("stem", ["officer", "merger", "reservedname"])
    def test_excludes_non_entity_files(self, stem):
        assert stem not in ENTITY_STEMS
