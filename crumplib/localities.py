"""Per-locality CSV files, one per Virginia county and independent city.

Built for municipal business-licensure departments, who need to see which
businesses are registered with the state at an address inside their locality --
and can then check that list against their own license rolls.

One file per locality, named `<FIPS>-<Locality>.csv`. The FIPS code leads so the
files sort into a stable, unambiguous order, and the locality name follows for
human readability. The name keeps its `County` / `city` suffix because four
names -- Fairfax, Franklin, Richmond, Roanoke -- belong to both a county and an
independent city, and dropping the suffix would put two indistinguishable names
in a directory listing.

All six entity types are merged into each file, which is why `entity_type` is a
column: an LLC and a stock corporation are both businesses that may owe a
license, but a reader still needs to tell them apart.
"""

import csv
import os
import re

#: Columns written to each locality file, in order.
#:
#: Deliberately narrow: this is a working list for a licensure clerk, not a full
#: dump. Registered agents and officers are excluded -- an agent is usually a
#: law firm or a registered-agent service at an unrelated address, which would
#: mislead rather than help.
COLUMNS = (
    "id",
    "entity_type",
    "name",
    "status",
    "status_reason",
    "status_date",
    "incorporation_date",
    "street_1",
    "street_2",
    "city",
    "state",
    "zip",
    "latitude",
    "longitude",
)

#: Maps whose rows are businesses that may owe a local licence.
ENTITY_STEMS = ("corp", "llc", "lp", "gp", "bt", "psa")

#: Anything not safe in a filename on any platform we might write to.
_UNSAFE = re.compile(r"[^A-Za-z0-9]+")


def filename_for(fips, name):
    """Build the locality filename, e.g. '51059-Fairfax-County.csv'.

    Spaces and punctuation become hyphens so the files are safe to serve over
    HTTP and to handle on any filesystem: 'King and Queen County' becomes
    '51097-King-and-Queen-County.csv'.
    """
    slug = _UNSAFE.sub("-", name).strip("-")
    return f"{fips}-{slug}.csv"


def row_for(record, entity_type):
    """Flatten a normalized record into a locality-file row."""
    coordinates = record.get("coordinates") or []
    latitude = longitude = None
    if len(coordinates) >= 2:
        longitude, latitude = coordinates[0], coordinates[1]

    return {
        "id": record.get("id") or "",
        "entity_type": entity_type,
        "name": record.get("name") or "",
        "status": record.get("status") or "",
        "status_reason": record.get("status_reason") or "",
        "status_date": _text(record.get("status_date")),
        "incorporation_date": _text(record.get("incorporation_date")),
        "street_1": record.get("street_1") or "",
        "street_2": record.get("street_2") or "",
        "city": record.get("city") or "",
        "state": record.get("state") or "",
        "zip": record.get("zip") or "",
        "latitude": "" if latitude is None else f"{latitude:.6f}",
        "longitude": "" if longitude is None else f"{longitude:.6f}",
    }


def _text(value):
    """Dates arrive as date objects; everything else is already a string."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class LocalityWriter:
    """Writes per-locality CSVs, opening each file on first use.

    Files stay open for the duration: there are only 133 localities, well under
    any file-descriptor limit, and reopening per row would be far slower.
    Records arrive interleaved across entity types, so append-as-you-go is the
    only single-pass option.
    """

    def __init__(self, directory):
        self.directory = directory
        self.written = 0
        self.skipped = 0
        self._files = {}
        self._writers = {}
        self._counts = {}
        self._names = {}
        os.makedirs(directory, exist_ok=True)

    def _writer_for(self, fips, name):
        if fips not in self._writers:
            path = os.path.join(self.directory, filename_for(fips, name))
            handle = open(path, "w", encoding="utf-8", newline="")
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            self._files[fips] = handle
            self._writers[fips] = writer
            self._counts[fips] = 0
            self._names[fips] = name
        return self._writers[fips]

    def write(self, record, entity_type):
        """Write one business to its locality's file, if it has one."""
        fips = record.get("fips")
        if not fips:
            # No jurisdiction: either not geocoded, or outside Virginia.
            self.skipped += 1
            return False

        writer = self._writer_for(fips, record.get("jurisdiction") or fips)
        writer.writerow(row_for(record, entity_type))
        self._counts[fips] += 1
        self.written += 1
        return True

    def counts(self):
        """Rows written per locality, as {fips: (name, count)}."""
        return {
            fips: (self._names[fips], count) for fips, count in self._counts.items()
        }

    def close(self):
        for handle in self._files.values():
            handle.close()
        self._files.clear()
        self._writers.clear()
