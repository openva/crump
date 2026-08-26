"""Tests for assigning businesses to Virginia counties and independent cities.

The coordinates below are real points checked against the shipped boundary
file. Virginia's jurisdiction lines effectively never move, so these are stable
fixtures rather than brittle ones.
"""

import pytest

from crumplib.jurisdiction import (
    VIRGINIA_FIPS,
    JurisdictionIndex,
    _point_in_ring,
)


@pytest.fixture(scope="module")
def index():
    return JurisdictionIndex()


class TestPointInRing:
    SQUARE = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]

    def test_inside(self):
        assert _point_in_ring(5, 5, self.SQUARE)

    def test_outside(self):
        assert not _point_in_ring(15, 5, self.SQUARE)

    def test_outside_on_the_other_axis(self):
        assert not _point_in_ring(5, 15, self.SQUARE)

    def test_concave_shape(self):
        """A C-shape: the notch is outside even though it is within the bbox."""
        shape = [
            (0, 0),
            (0, 10),
            (10, 10),
            (10, 7),
            (3, 7),
            (3, 3),
            (10, 3),
            (10, 0),
            (0, 0),
        ]
        assert _point_in_ring(1, 5, shape)
        assert not _point_in_ring(7, 5, shape)


class TestBoundaryData:
    def test_has_every_virginia_jurisdiction(self, index):
        """95 counties plus 38 independent cities."""
        assert len(index) == 133

    def test_county_and_city_counts(self, index):
        kinds = {}
        for area in index.areas:
            kinds.setdefault(area.kind, set()).add(area.fips)
        assert len(kinds["county"]) == 95
        assert len(kinds["city"]) == 38

    def test_every_fips_is_virginia(self, index):
        for area in index.areas:
            assert area.fips.startswith(VIRGINIA_FIPS)

    def test_fips_are_five_digits(self, index):
        for area in index.areas:
            assert len(area.fips) == 5
            assert area.fips.isdigit()


class TestLocate:
    def test_richmond_city(self, index):
        area = index.locate(-77.4360, 37.5407)
        assert area.fips == "51760"
        assert area.kind == "city"

    def test_richmond_county_is_a_different_place(self, index):
        """Richmond city (51760) and Richmond County (51159) are 60 miles apart.

        This is why the address field cannot answer the question.
        """
        city = index.locate(-77.4360, 37.5407)
        county = index.locate(-76.7300, 37.9400)
        assert city.fips == "51760"
        assert county.fips != city.fips
        assert "Richmond" in city.name

    def test_arlington_county(self, index):
        area = index.locate(-77.1043, 38.8462)
        assert area.fips == "51013"
        assert area.kind == "county"

    def test_norfolk_city(self, index):
        area = index.locate(-76.2859, 36.8508)
        assert area.fips == "51710"
        assert area.kind == "city"

    def test_outside_virginia_is_none(self, index):
        assert index.locate(-100.0, 40.0) is None

    def test_atlantic_ocean_is_none(self, index):
        assert index.locate(-70.0, 36.0) is None

    def test_none_coordinates(self, index):
        assert index.locate(None, None) is None
        assert index.locate(-77.4, None) is None


class TestLocateCoordinates:
    def test_accepts_stored_geojson_pair(self, index):
        """Crump stores [longitude, latitude], per GeoJSON."""
        area = index.locate_coordinates([-77.4360, 37.5407])
        assert area.fips == "51760"

    def test_empty_is_none(self, index):
        assert index.locate_coordinates(None) is None
        assert index.locate_coordinates([]) is None

    def test_malformed_pair_is_none(self, index):
        assert index.locate_coordinates([-77.4]) is None
