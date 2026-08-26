"""Assigning Virginia businesses to the city or county they sit in.

Virginia is unusual: its 38 independent cities are not part of any county, so a
business is in *either* a county *or* a city, never both. The two can also share
a name -- Richmond city (51760) and Richmond County (51159) are different
places, 60 miles apart.

This cannot be answered from the address. A mailing address of "Charlottesville"
falls inside Charlottesville city only about 46% of the time; the rest are in
surrounding Albemarle County. "Richmond" splits across Richmond city,
Chesterfield County, and Henrico County. Only the coordinates settle it, so
jurisdiction is assigned by testing a geocoded point against actual boundaries.

Boundaries come from the Census Bureau's TIGERweb service (2023 vintage),
trimmed and stored in `boundaries/`. Virginia's jurisdiction lines effectively
never move, so a pinned vintage is fine and keeps results reproducible.
"""

import gzip
import json
import os

#: Shipped with the repo so lookups work offline and reproducibly.
DEFAULT_BOUNDARY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "boundaries",
    "va_jurisdictions.geojson.gz",
)

#: Virginia's state FIPS code. County FIPS are always this plus three digits.
VIRGINIA_FIPS = "51"


class Jurisdiction:
    """One county or independent city."""

    __slots__ = ("fips", "name", "kind", "bbox", "rings")

    def __init__(self, fips, name, kind, rings):
        self.fips = fips
        self.name = name
        self.kind = kind
        self.rings = rings
        outer = rings[0]
        xs = [point[0] for point in outer]
        ys = [point[1] for point in outer]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))

    def __repr__(self):
        return f"<Jurisdiction {self.fips} {self.name}>"


def _point_in_ring(x, y, ring):
    """Ray-casting point-in-polygon test for a single ring."""
    inside = False
    count = len(ring)
    j = count - 1
    for i in range(count):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


class JurisdictionIndex:
    """Point-in-polygon lookup over Virginia's counties and cities.

    Deliberately pure-Python: the alternative is a geospatial stack (GEOS,
    shapely, fiona) that would dwarf the rest of Crump's dependencies for one
    lookup. A bounding-box prefilter makes it fast enough -- roughly 2,500
    lookups a second, so a few minutes for the whole dataset.
    """

    def __init__(self, path=None):
        self.path = path or DEFAULT_BOUNDARY_FILE
        self.areas = []
        self._load()

    def _load(self):
        opener = gzip.open if self.path.endswith(".gz") else open
        with opener(self.path, "rt", encoding="utf-8") as handle:
            data = json.load(handle)

        for feature in data.get("features", []):
            properties = feature["properties"]
            geometry = feature["geometry"]
            # MultiPolygon jurisdictions (islands, detached parcels) become one
            # entry per part, all sharing the same FIPS code.
            if geometry["type"] == "MultiPolygon":
                parts = geometry["coordinates"]
            else:
                parts = [geometry["coordinates"]]
            for rings in parts:
                self.areas.append(
                    Jurisdiction(
                        properties["fips"],
                        properties["name"],
                        properties["type"],
                        rings,
                    )
                )

    def __len__(self):
        return len({area.fips for area in self.areas})

    def locate(self, longitude, latitude):
        """Return the Jurisdiction containing a point, or None.

        Takes longitude first, matching the GeoJSON order Crump stores
        coordinates in.
        """
        if longitude is None or latitude is None:
            return None

        for area in self.areas:
            min_x, min_y, max_x, max_y = area.bbox
            if not (min_x <= longitude <= max_x and min_y <= latitude <= max_y):
                continue
            rings = area.rings
            if not _point_in_ring(longitude, latitude, rings[0]):
                continue
            # Interior rings are holes; a point inside one is outside the area.
            if any(_point_in_ring(longitude, latitude, hole) for hole in rings[1:]):
                continue
            return area
        return None

    def locate_coordinates(self, coordinates):
        """Locate from a stored [longitude, latitude] pair."""
        if not coordinates or len(coordinates) < 2:
            return None
        return self.locate(coordinates[0], coordinates[1])
