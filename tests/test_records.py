"""Tests for turning raw CSV rows into normalized records."""

import datetime

import pytest

from crumplib.maps import load_maps
from crumplib.records import RecordNormalizer


@pytest.fixture(scope="module")
def maps():
    return load_maps("table_maps")


def raw_corp_row(**overrides):
    """A Corp.csv row with the feed's padding, as csv.DictReader yields it."""
    row = {
        "EntityID": "\t11683582  ",
        "Name": "New Kent Civic League",
        "Status": "INACTIVE  ",
        "StatusReason": "Void - Office Correct",
        "Status Date": "2024-04-15",
        "Duration": "9999-12-31",
        "IncorpDate": "          ",
        "IncorpState": "VA        ",
        "IndustryCode": "          ",
        "Street1": "1 Main St ",
        "Street2": "          ",
        "City": "Richmond  ",
        "State": "Virginia  ",
        "Zip": "23219-0000",
        "PrinOffEffDate": "          ",
        "RA-Name": "          ",
        "RA-Street1": "          ",
        "RA-Street2": "          ",
        "RA-City": "          ",
        "RA-State": "          ",
        "RA-Zip": "          ",
        "RA-EffDate": "",
        "RA-Status": "Active    ",
        "RA-Loc": "          ",
        "StockInd": "S         ",
        "TotalShares": "5000.0    ",
        "MergerInd": "          ",
        "AssessInd": "0         ",
        "Stock1": "Class A   ",
    }
    row.update(overrides)
    return row


class TestCorpNormalization:
    def test_strips_tab_and_padding_from_id(self, maps):
        record = RecordNormalizer(maps["corp"]).normalize(raw_corp_row())
        assert record["id"] == "11683582"

    def test_parses_date(self, maps):
        record = RecordNormalizer(maps["corp"]).normalize(raw_corp_row())
        assert record["status_date"] == datetime.date(2024, 4, 15)

    def test_null_sentinel_date_becomes_none(self, maps):
        record = RecordNormalizer(maps["corp"]).normalize(raw_corp_row())
        assert record["expiration_date"] is None

    def test_float_share_count_becomes_int(self, maps):
        record = RecordNormalizer(maps["corp"]).normalize(raw_corp_row())
        assert record["total_shares"] == 5000

    def test_zip_plus_four_of_zeros_is_trimmed(self, maps):
        record = RecordNormalizer(maps["corp"]).normalize(raw_corp_row())
        assert record["zip"] == "23219"

    def test_derives_foreign_false_for_virginia(self, maps):
        record = RecordNormalizer(maps["corp"]).normalize(raw_corp_row())
        assert record["foreign"] is False

    def test_derives_foreign_true_for_delaware(self, maps):
        record = RecordNormalizer(maps["corp"]).normalize(
            raw_corp_row(IncorpState="DE        ")
        )
        assert record["foreign"] is True

    def test_expands_stock_indicator(self, maps):
        record = RecordNormalizer(maps["corp"]).normalize(raw_corp_row())
        assert record["stock_ind"] == "stock"

    def test_emits_every_mapped_column(self, maps):
        record = RecordNormalizer(maps["corp"]).normalize(raw_corp_row())
        assert set(record) == set(maps["corp"].output_names)

    def test_no_coordinates_without_a_cache(self, maps):
        record = RecordNormalizer(maps["corp"]).normalize(raw_corp_row())
        assert record["coordinates"] is None


class TestTransforms:
    def test_namehistory_expands_numeric_codes(self, maps):
        normalizer = RecordNormalizer(maps["namehistory"])
        record = normalizer.normalize(
            {
                "EntityID": "\t02610707  ",
                "NameStatus": "70",
                "NameEffDate": "1999-01-01",
                "EntityName": "OLD NAME INC",
            }
        )
        assert record["name_status"] == "old name"

    def test_reservedname_expands_status(self, maps):
        normalizer = RecordNormalizer(maps["reservedname"])
        record = normalizer.normalize(
            {
                "ResNumber": "\t11023050  ",
                "Type": "C",
                "Status": "61",
                "Name": "Test",
                "ExpireDate": "2026-01-01",
                "Requestor": "Someone",
                "Street1": "",
                "Street2": "",
                "City": "",
                "State": "",
                "Zip": "",
            }
        )
        assert record["status"] == "reserved"
        assert record["entity_type"] == "corporate"

    def test_merger_expands_type(self, maps):
        normalizer = RecordNormalizer(maps["merger"])
        record = normalizer.normalize(
            {
                "EntityID": "\t00428862  ",
                "MergerType": "S",
                "EffDate": "2000-01-01",
                "SurvivorID": "",
                "ForeignName": "",
            }
        )
        assert record["merger_type"] == "survivor"

    def test_unknown_code_passes_through_and_is_recorded(self, maps):
        """The undocumented 'X' in ReservedName.Type must survive, not vanish."""
        normalizer = RecordNormalizer(maps["reservedname"])
        record = normalizer.normalize(
            {
                "ResNumber": "\t1  ",
                "Type": "X",
                "Status": "61",
                "Name": "Test",
                "ExpireDate": "",
                "Requestor": "",
                "Street1": "",
                "Street2": "",
                "City": "",
                "State": "",
                "Zip": "",
            }
        )
        assert record["entity_type"] == "X"
        assert ("entity_type", "X") in normalizer.unknown_codes


class TestJurisdiction:
    """Jurisdiction assignment through the record pipeline."""

    def _normalizer(self, maps, coordinates):
        """A normalizer whose geocode cache always returns one point."""

        class StubCache:
            available = True

            def coordinates(self, *args):
                return coordinates

        from crumplib.jurisdiction import JurisdictionIndex

        return RecordNormalizer(
            maps["corp"], StubCache(), jurisdictions=JurisdictionIndex()
        )

    def test_assigns_fips_from_coordinates(self, maps):
        normalizer = self._normalizer(maps, [-77.4360, 37.5407])
        record = normalizer.normalize(raw_corp_row())
        assert record["fips"] == "51760"
        assert record["jurisdiction"] == "Richmond city"
        assert record["jurisdiction_type"] == "city"

    def test_county_is_distinguished_from_city(self, maps):
        normalizer = self._normalizer(maps, [-77.1043, 38.8462])
        record = normalizer.normalize(raw_corp_row())
        assert record["jurisdiction_type"] == "county"

    def test_outside_virginia_leaves_fips_null(self, maps):
        normalizer = self._normalizer(maps, [-100.0, 40.0])
        record = normalizer.normalize(raw_corp_row())
        assert record["fips"] is None
        assert record["jurisdiction"] is None

    def test_no_coordinates_means_no_fips(self, maps):
        """Geocoding coverage is the ceiling on jurisdiction coverage."""
        normalizer = self._normalizer(maps, None)
        record = normalizer.normalize(raw_corp_row())
        assert record["fips"] is None

    def test_absent_index_leaves_fields_null(self, maps):
        """Without -j, the columns exist but stay empty."""
        record = RecordNormalizer(maps["corp"]).normalize(raw_corp_row())
        assert record["fips"] is None
        assert "fips" in record

    def test_registered_agent_address_is_not_assigned(self, maps):
        """Scope is the principal office only; there is no agent_fips column."""
        assert "agent_fips" not in maps["corp"].output_names
