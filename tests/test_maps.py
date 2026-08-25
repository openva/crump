"""Tests for the YAML field maps.

These guard the map/CSV contract: if the SCC changes a column name, the
coverage test below is what tells us.
"""

import pytest

from crumplib.maps import CSV_FILENAMES, load_maps


@pytest.fixture(scope="module")
def maps():
    return load_maps("table_maps")


class TestMapIntegrity:
    def test_all_expected_maps_present(self, maps):
        assert set(maps) == set(CSV_FILENAMES)

    def test_every_entry_has_alt_name_and_description(self, maps):
        for stem, field_map in maps.items():
            for field in field_map.fields:
                assert "alt_name" in field, f"{stem}: missing alt_name"
                assert "description" in field, (
                    f"{stem}: {field['alt_name']} missing description"
                )

    def test_output_names_are_unique(self, maps):
        for stem, field_map in maps.items():
            names = field_map.output_names
            assert len(names) == len(set(names)), f"{stem} has duplicates"

    def test_no_legacy_fixed_width_keys(self, maps):
        """start/length/table_id belonged to the fixed-width era."""
        for stem, field_map in maps.items():
            for field in field_map.fields:
                for dead in ("start", "length", "table_id", "name"):
                    assert dead not in field, (
                        f"{stem}: {field['alt_name']} still has {dead}"
                    )

    def test_types_are_known(self, maps):
        for field_map in maps.values():
            for field in field_map.fields:
                assert field.get("type", "A") in ("A", "N", "D", "Z", "B")

    def test_derived_fields_declare_how(self, maps):
        for stem, field_map in maps.items():
            for field in field_map.derived_fields:
                assert field.get("derived") in (
                    "geocode",
                    "foreign_from_state",
                ), f"{stem}: {field['alt_name']}"

    def test_transform_keys_are_strings(self, maps):
        """Unquoted numeric YAML keys load as ints and never match CSV text."""
        for stem, field_map in maps.items():
            for field in field_map.fields:
                for key in field.get("transform", {}):
                    assert isinstance(key, str), (
                        f"{stem}: {field['alt_name']} transform key "
                        f"{key!r} is not a string"
                    )


class TestAddressGroups:
    def test_entity_maps_have_two_address_groups(self, maps):
        for stem in ("corp", "llc", "lp", "gp", "bt", "psa"):
            groups = maps[stem].address_groups()
            assert set(groups) == {"address", "ra_address"}, stem

    def test_group_names_its_output_field(self, maps):
        groups = maps["corp"].address_groups()
        assert groups["address"]["output"] == "coordinates"
        assert groups["ra_address"]["output"] == "agent_coordinates"

    def test_group_maps_all_address_roles(self, maps):
        fields = maps["corp"].address_groups()["address"]["fields"]
        assert set(fields) == {"street1", "street2", "city", "state", "zip"}

    def test_officer_has_no_address_group(self, maps):
        assert maps["officer"].address_groups() == {}

    def test_reservedname_has_requestor_address(self, maps):
        assert set(maps["reservedname"].address_groups()) == {"address"}
