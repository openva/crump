"""Tests for the geocoded-address cache.

The address hash is a compatibility contract with 564,848 rows of existing
cached data. If these tests fail, the cache has been invalidated.
"""

import sqlite3

import pytest

from crumplib import geocache


class TestAddressKey:
    def test_known_hash_from_production_cache(self):
        """The characterization case: this hash exists in addresses.db.

        Reproducing it proves the Python 3 port preserved the Python 2 byte
        encoding.
        """
        digest = geocache.address_hash(
            "6628 ELECTRONIC DR", "", "SPRINGFIELD", "VA", "22151"
        )
        assert digest == "e85df274dcf6ba70be4a9ecd32c0596d"

    def test_csv_feed_form_hashes_identically(self):
        """Mixed case + spelled-out state + ZIP+4 must reach the same hash.

        This normalization is what lifts the cache hit rate from 0% to ~38%.
        """
        cached_form = geocache.address_hash(
            "6628 ELECTRONIC DR", "", "SPRINGFIELD", "VA", "22151"
        )
        feed_form = geocache.address_hash(
            "6628 Electronic Dr", "", "Springfield", "Virginia", "22151-4141"
        )
        assert feed_form == cached_form

    def test_key_format_is_comma_joined(self):
        assert geocache.address_key(
            "1 Main St", "", "Richmond", "Virginia", "23219"
        ) == "1 MAIN ST,,RICHMOND,VA,23219"

    def test_padding_does_not_change_hash(self):
        assert geocache.address_hash(
            "  1 Main St  ", "", " Richmond ", "Virginia ", " 23219 "
        ) == geocache.address_hash("1 Main St", "", "Richmond", "VA", "23219")


@pytest.fixture
def cache(tmp_path):
    """A small cache with one known address."""
    path = tmp_path / "addresses.db"
    db = sqlite3.connect(str(path))
    db.execute(
        "CREATE TABLE addresses (address_hash TEXT PRIMARY KEY NOT NULL, "
        "address_cleaned TEXT, latitude REAL, longitude REAL, date INTEGER, "
        "source TEXT)"
    )
    db.execute(
        "INSERT INTO addresses VALUES (?, ?, ?, ?, ?, ?)",
        (
            geocache.address_hash("1 Main St", "", "Richmond", "VA", "23219"),
            "1 MAIN ST, RICHMOND, VA, 23219",
            37.5,
            -77.4,
            0,
            "VGIN",
        ),
    )
    db.commit()
    db.close()
    return str(path)


class TestGeocodeCache:
    def test_returns_geojson_order(self, cache):
        """Coordinates come back [longitude, latitude], per GeoJSON."""
        found = geocache.GeocodeCache(cache).coordinates(
            "1 Main St", "", "Richmond", "VA", "23219"
        )
        assert found == [-77.4, 37.5]

    def test_matches_across_feed_formatting(self, cache):
        found = geocache.GeocodeCache(cache).coordinates(
            "1 main st", "", "Richmond", "Virginia", "23219-0000"
        )
        assert found == [-77.4, 37.5]

    def test_miss_returns_none(self, cache):
        assert geocache.GeocodeCache(cache).coordinates(
            "999 Nowhere Ln", "", "Richmond", "VA", "23219"
        ) is None

    def test_counts_hits_and_misses(self, cache):
        subject = geocache.GeocodeCache(cache)
        subject.coordinates("1 Main St", "", "Richmond", "VA", "23219")
        subject.coordinates("2 Main St", "", "Richmond", "VA", "23219")
        assert (subject.hits, subject.misses) == (1, 1)

    def test_missing_file_is_not_fatal(self, tmp_path):
        """Geocoding is optional; an absent cache must not crash the run."""
        subject = geocache.GeocodeCache(str(tmp_path / "nope.db"))
        assert subject.available is False
        assert subject.coordinates("1 Main St", "", "R", "VA", "1") is None

    def test_len_reports_row_count(self, cache):
        assert len(geocache.GeocodeCache(cache)) == 1
