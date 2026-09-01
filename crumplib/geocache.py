"""Lookups against the SQLite cache of geocoded addresses.

The cache (`addresses.db`, 564,848 rows geocoded 2014-2015) was built when the
SCC feed shipped uppercase addresses with USPS state abbreviations and 5-digit
ZIPs. The CSV feed ships mixed case, spelled-out state names, and ZIP+4, so a
naive lookup misses every single row. `address_key` reproduces the original
hash input; `normalize.abbreviate_state` and the ZIP5 truncation here are what
make the cache reusable at all.
"""

import hashlib
import sqlite3

from . import normalize


def address_key(street_1, street_2, city, state, zip_code):
    """Build the exact string the cached MD5 hashes were computed over.

    This is a compatibility contract, not a design choice -- the format is
    fixed by 564,848 existing rows. Changing it silently invalidates the cache.

    Original Python 2 recipe (crump:372):
        md5(street_1 + "," + street_2 + "," + city + "," + state + "," + zip)

    Normalization applied to match how the cache was originally keyed:
      * uppercase (the old feed was uppercase; the CSV feed is mixed case)
      * USPS abbreviation (the old feed abbreviated; the CSV spells states out)
      * ZIP truncated to 5 digits (the old feed was mostly 5-digit)
    """
    parts = [
        normalize.clean_text(street_1).upper(),
        normalize.clean_text(street_2).upper(),
        normalize.clean_text(city).upper(),
        normalize.abbreviate_state(state).upper(),
        normalize.parse_zip(zip_code).split("-")[0],
    ]
    return ",".join(parts)


def address_hash(street_1, street_2, city, state, zip_code):
    """MD5 of the address key, matching the hashes stored in addresses.db."""
    key = address_key(street_1, street_2, city, state, zip_code)
    return hashlib.md5(key.encode("utf-8")).hexdigest()


class GeocodeCache:
    """Read-only lookups against addresses.db.

    `preload` pulls every hash into a set to skip a SQL round trip per lookup.
    It is off by default: the set costs over 100 MB once the cache passes a
    million rows, which is real money on a small server, and SQLite's own page
    cache makes the indexed lookup fast enough without it.
    """

    def __init__(self, path="addresses.db", preload=False):
        self.path = path
        self._connection = None
        self._hashes = None
        self.hits = 0
        self.misses = 0
        try:
            self._connection = sqlite3.connect(path)
        except sqlite3.Error:
            self._connection = None
            return
        if not self._table_exists():
            self._connection.close()
            self._connection = None
            return
        if preload:
            self._hashes = {
                row[0]
                for row in self._connection.execute(
                    "SELECT address_hash FROM addresses"
                )
            }

    @property
    def available(self):
        """Whether the cache is usable. Geocoding is optional, not fatal."""
        return self._connection is not None

    def _table_exists(self):
        cursor = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='addresses'"
        )
        return cursor.fetchone() is not None

    def __len__(self):
        if self._hashes is not None:
            return len(self._hashes)
        if not self.available:
            return 0
        return self._connection.execute("SELECT COUNT(*) FROM addresses").fetchone()[0]

    def coordinates(self, street_1, street_2, city, state, zip_code):
        """Return [longitude, latitude] for an address, or None if uncached.

        GeoJSON order (longitude first), matching what the JSON output needs.
        """
        if not self.available:
            return None

        digest = address_hash(street_1, street_2, city, state, zip_code)

        # Cheap membership test first when preloaded, to skip the query.
        if self._hashes is not None and digest not in self._hashes:
            self.misses += 1
            return None

        row = self._connection.execute(
            "SELECT latitude, longitude FROM addresses WHERE address_hash = ?",
            (digest,),
        ).fetchone()
        if row is None or row[0] is None or row[1] is None:
            self.misses += 1
            return None

        self.hits += 1
        return [row[1], row[0]]

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None
