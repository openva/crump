"""Loading and applying the YAML field maps in table_maps/.

Each map file corresponds to one upstream CSV: table_maps/corp.yaml describes
Corp.csv. A map is a list of field entries; see plan.md for the full schema.
"""

import os

import yaml

#: Maps `table_maps/<stem>.yaml` to the upstream CSV filename.
CSV_FILENAMES = {
    "corp": "Corp.csv",
    "llc": "LLC.csv",
    "lp": "LP.csv",
    "gp": "GP.csv",
    "bt": "BT.csv",
    "psa": "PSA.csv",
    "amendment": "Amendment.csv",
    "merger": "Merger.csv",
    "officer": "Officer.csv",
    "namehistory": "NameHistory.csv",
    "reservedname": "ReservedName.csv",
}


class FieldMap:
    """One YAML map: the field list for a single upstream CSV."""

    def __init__(self, stem, fields):
        self.stem = stem
        self.fields = fields
        self.csv_name = CSV_FILENAMES.get(stem)

    @property
    def output_names(self):
        """Emitted column names, in map order. Drives CSV header order."""
        return [field["alt_name"] for field in self.fields]

    @property
    def sourced_fields(self):
        """Fields read directly from the CSV."""
        return [field for field in self.fields if "source" in field]

    @property
    def derived_fields(self):
        """Fields computed rather than read (geocoding, foreign flag)."""
        return [field for field in self.fields if "source" not in field]

    def groups(self):
        """Map each `group` name to its member fields.

        Used to find address clusters generically, rather than hardcoding which
        files have addresses the way the old code did.
        """
        grouped = {}
        for field in self.fields:
            if "group" in field:
                grouped.setdefault(field["group"], []).append(field)
        return grouped

    def address_groups(self):
        """Groups that hold a geocodable address.

        A group qualifies when it has a `derived: geocode` member -- that entry
        also names the output field, so nothing here is hardcoded.
        """
        found = {}
        for name, members in self.groups().items():
            target = next(
                (f for f in members if f.get("derived") == "geocode"), None
            )
            if target is None:
                continue
            by_role = {}
            for member in members:
                source = member.get("source", "")
                role = _address_role(source)
                if role:
                    by_role[role] = member["alt_name"]
            if len(by_role) >= 4:
                found[name] = {
                    "output": target["alt_name"],
                    "fields": by_role,
                }
        return found


def _address_role(source):
    """Classify an upstream column as part of an address, e.g. RA-City -> city."""
    bare = source.replace("RA-", "").lower()
    if bare in ("street1", "street2", "city", "state", "zip"):
        return bare
    return None


def load_maps(directory="table_maps"):
    """Load every YAML map in a directory, keyed by file stem."""
    maps = {}
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".yaml"):
            continue
        stem = filename[: -len(".yaml")]
        with open(os.path.join(directory, filename), encoding="utf-8") as handle:
            fields = yaml.safe_load(handle)
        maps[stem] = FieldMap(stem, fields)
    return maps
