"""Tests for field normalization.

The cases here are drawn from the actual SCC feed, not invented -- each one
corresponds to a quirk verified against Corp.csv (see plan.md, Phase 0).
"""

import datetime

import pytest

from crumplib import normalize


class TestCleanText:
    def test_strips_fixed_width_padding(self):
        assert normalize.clean_text("INACTIVE  ") == "INACTIVE"

    def test_strips_leading_tab_on_entity_id(self):
        # The SCC prefixes EntityID with a literal tab to force Excel to treat
        # it as text.
        assert normalize.clean_text("\t11683582  ") == "11683582"

    def test_collapses_interior_whitespace(self):
        assert normalize.clean_text("FOO    BAR") == "FOO BAR"

    def test_handles_none(self):
        assert normalize.clean_text(None) == ""


class TestParseDate:
    def test_parses_iso_date(self):
        assert normalize.parse_date("2024-04-15") == datetime.date(2024, 4, 15)

    def test_null_sentinel_is_none(self):
        # 9999-12-31 dominates the Duration column.
        assert normalize.parse_date("9999-12-31") is None

    def test_legacy_sentinels_are_none(self):
        assert normalize.parse_date("0000-00-00") is None
        assert normalize.parse_date("9999-99-99") is None

    def test_blank_is_none(self):
        assert normalize.parse_date("") is None
        assert normalize.parse_date("          ") is None

    def test_malformed_is_none_not_mangled(self):
        # The old code sliced these into '--' and '0--0' and passed them on.
        assert normalize.parse_date("0") is None
        assert normalize.parse_date("garbage") is None

    def test_coerces_out_of_range_month(self):
        assert normalize.parse_date("2024-13-01") == datetime.date(2024, 12, 1)

    def test_coerces_out_of_range_day(self):
        # February 30th clamps to the 29th in a leap year.
        assert normalize.parse_date("2024-02-30") == datetime.date(2024, 2, 29)

    def test_leap_year_boundary(self):
        assert normalize.parse_date("2023-02-29") == datetime.date(2023, 2, 28)


class TestDaysInMonth:
    @pytest.mark.parametrize(
        "year,month,expected",
        [
            (2017, 2, 28),
            (2024, 2, 29),
            (2024, 1, 31),
            (2024, 4, 30),
            (2024, 12, 31),
        ],
    )
    def test_days_in_month(self, year, month, expected):
        assert normalize._days_in_month(year, month) == expected


class TestParseZip:
    def test_five_digit_passes_through(self):
        assert normalize.parse_zip("23219") == "23219"

    def test_hyphenated_nine_passes_through(self):
        assert normalize.parse_zip("23219-1234") == "23219-1234"

    def test_unseparated_nine_gets_hyphen(self):
        assert normalize.parse_zip("232191234") == "23219-1234"

    def test_all_zero_becomes_empty(self):
        # The old code turned this into '-'.
        assert normalize.parse_zip("000000000") == ""
        assert normalize.parse_zip("00000") == ""

    def test_empty_plus_four_is_dropped(self):
        assert normalize.parse_zip("232190000") == "23219"

    def test_empty_plus_four_is_dropped_when_hyphenated(self):
        # The feed ships '23219-0000' as filler; the +4 carries no information.
        assert normalize.parse_zip("23219-0000") == "23219"

    def test_canadian_postcode_survives(self):
        assert normalize.parse_zip("M9J9B9") == "M9J9B9"

    def test_blank(self):
        assert normalize.parse_zip("   ") == ""


class TestParseNumber:
    def test_float_string_from_feed(self):
        # TotalShares arrives as '5000.0'; the old int() raised ValueError.
        assert normalize.parse_number("5000.0") == 5000

    def test_zero(self):
        assert normalize.parse_number("0.0") == 0

    def test_blank_is_none(self):
        assert normalize.parse_number("") is None

    def test_all_nines_is_none(self):
        assert normalize.parse_number("99999999999") is None

    def test_non_numeric_is_none(self):
        assert normalize.parse_number("none") is None

    def test_strips_padding(self):
        assert normalize.parse_number("  1000.0   ") == 1000


class TestParseBoolean:
    @pytest.mark.parametrize("value", ["Y", "yes", "T", "true", "1", "S"])
    def test_true_values(self, value):
        assert normalize.parse_boolean(value) is True

    @pytest.mark.parametrize("value", ["N", "no", "F", "false", "0"])
    def test_false_values(self, value):
        assert normalize.parse_boolean(value) is False

    def test_indeterminate(self):
        assert normalize.parse_boolean("") is None
        assert normalize.parse_boolean("maybe") is None


class TestAbbreviateState:
    def test_full_name_to_abbreviation(self):
        # This is what makes the geocode cache reusable.
        assert normalize.abbreviate_state("Virginia") == "VA"
        assert normalize.abbreviate_state("North Carolina") == "NC"

    def test_already_abbreviated(self):
        assert normalize.abbreviate_state("VA") == "VA"
        assert normalize.abbreviate_state("va") == "VA"

    def test_unknown_passes_through(self):
        assert normalize.abbreviate_state("Ontario") == "Ontario"

    def test_blank(self):
        assert normalize.abbreviate_state("") == ""

    def test_all_fifty_states_plus_dc(self):
        assert len(normalize.STATE_ABBREVIATIONS) >= 51
