"""Batch geocoding via the Census Bureau's bulk endpoint.

The Census geocoder accepts a CSV of up to 10,000 addresses per request and
answers in seconds, which is the only practical way to work through the ~1.36
million addresses the cache does not cover. One-at-a-time geocoding at the
polite 1 req/sec rate would take about sixteen days.

Measured on real SCC addresses: 1,000 addresses in 4.1 seconds, 82% matched
(after filtering PO boxes, which never match). Serially that same batch would
have taken ~17 minutes.

The catch is match quality. The service returns `Non_Exact` matches that can
name a *different* street than the one asked for -- `1 W Nationwide Blvd`
coming back as `1 E NATIONWIDE BLVD`. Measured at 1.2% of matches. Since these
results get cached and served as a business's location, `directional_conflict`
rejects them rather than storing a plausible-looking wrong answer.
"""

import csv
import io
import re

import requests

BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"

#: The service's documented ceiling.
MAX_BATCH_SIZE = 10000

#: Column order the service requires, with no header row:
#: Unique ID, Street address, City, State, ZIP
INPUT_COLUMNS = ("id", "street", "city", "state", "zip")

#: Directional words and their canonical abbreviations.
_DIRECTIONALS = {
    "N": "N",
    "S": "S",
    "E": "E",
    "W": "W",
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NE": "NE",
    "NW": "NW",
    "SE": "SE",
    "SW": "SW",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
}


class BatchError(Exception):
    """The batch request failed."""


def _directionals(address):
    """The directionals named in an address's street portion."""
    street = address.split(",")[0].upper()
    return {
        _DIRECTIONALS[token]
        for token in re.findall(r"[A-Z]+", street)
        if token in _DIRECTIONALS
    }


def directional_conflict(requested, matched):
    """Whether a match contradicts the requested address's directional.

    `1 W Nationwide Blvd` matching `1 E NATIONWIDE BLVD` is a different place,
    not a normalization. Only flags genuine disagreement: an address that gains
    a directional it did not have ('SECOND AVENUE NORTH' -> '2ND AVE N') is the
    geocoder disambiguating, which is fine.
    """
    wanted = _directionals(requested)
    found = _directionals(matched)
    if not wanted or not found:
        return False
    return not (wanted & found)


def write_batch(rows, handle):
    """Write addresses as the CSV the service expects: no header, five columns."""
    writer = csv.writer(handle)
    count = 0
    for row in rows:
        writer.writerow(
            [
                row["id"],
                row["street"],
                row["city"],
                row["state"],
                row["zip"],
            ]
        )
        count += 1
    return count


def parse_response(text, reject_directional_conflicts=True):
    """Parse the returned CSV into results keyed by the ID we submitted.

    Returns (matches, rejected), where `matches` maps id -> result dict and
    `rejected` maps id -> the reason it was not usable. Unmatched addresses come
    back with only three columns, so row width has to be checked before
    indexing -- the old single-address code would have raised IndexError here.
    """
    matches = {}
    rejected = {}

    for row in csv.reader(io.StringIO(text)):
        if len(row) < 3:
            continue
        identifier, requested, status = row[0], row[1], row[2]

        if status != "Match":
            # 'No_Match' or 'Tie' (an ambiguous address the service won't pick
            # between). Both are failures, but worth distinguishing.
            rejected[identifier] = status.lower()
            continue

        if len(row) < 6:
            rejected[identifier] = "match missing coordinates"
            continue

        quality, matched_address, coordinates = row[3], row[4], row[5]

        if reject_directional_conflicts and directional_conflict(
            requested, matched_address
        ):
            rejected[identifier] = "directional conflict"
            continue

        try:
            longitude, latitude = (float(part) for part in coordinates.split(","))
        except ValueError:
            rejected[identifier] = "unparseable coordinates"
            continue

        matches[identifier] = {
            "address": matched_address,
            "latitude": latitude,
            "longitude": longitude,
            "quality": quality.lower(),
            "source": "Census",
        }

    return matches, rejected


def geocode_batch(
    rows,
    session=None,
    timeout=600,
    benchmark="Public_AR_Current",
    reject_directional_conflicts=True,
):
    """Geocode up to MAX_BATCH_SIZE addresses in one request.

    `rows` is an iterable of dicts with the keys in INPUT_COLUMNS. The `id` of
    each is echoed back by the service, so use the address hash and the results
    drop straight into the cache.
    """
    rows = list(rows)
    if not rows:
        return {}, {}
    if len(rows) > MAX_BATCH_SIZE:
        raise BatchError(
            f"batch of {len(rows)} exceeds the service limit of {MAX_BATCH_SIZE}"
        )

    buffer = io.StringIO()
    write_batch(rows, buffer)

    session = session or requests.Session()
    try:
        response = session.post(
            BATCH_URL,
            files={"addressFile": ("addresses.csv", buffer.getvalue(), "text/csv")},
            data={"benchmark": benchmark},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise BatchError(f"batch request failed: {error}") from error

    return parse_response(
        response.text,
        reject_directional_conflicts=reject_directional_conflicts,
    )


def chunked(items, size=MAX_BATCH_SIZE):
    """Yield lists of at most `size` items."""
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
