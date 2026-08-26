"""Turning raw CSV rows into normalized records."""

from . import normalize

#: csv.DictReader collects the phantom trailing column under this key. Every
#: data row in the feed has one more field than its header, thanks to a trailing
#: comma left over from the fixed-width era.
PHANTOM_KEY = None


class RecordNormalizer:
    """Applies one FieldMap to CSV rows.

    Tracks unknown transform codes so undocumented values (like the `X` in
    ReservedName.Type) get reported once per run instead of silently passing
    through or being dropped.
    """

    def __init__(self, field_map, cache=None, jurisdictions=None):
        self.map = field_map
        self.cache = cache
        self.jurisdictions = jurisdictions
        self.unknown_codes = {}
        self._address_groups = field_map.address_groups()
        # Jurisdiction is only assigned for the principal office, per scope --
        # the `address` group, not `ra_address`.
        self._jurisdiction_fields = [
            field
            for field in field_map.derived_fields
            if field.get("derived") == "jurisdiction"
            and field.get("group") == "address"
        ]

    def normalize(self, row):
        """Convert one raw CSV row into a normalized record."""
        record = {}

        for field in self.map.sourced_fields:
            record[field["alt_name"]] = self._value(field, row)

        for field in self.map.derived_fields:
            how = field.get("derived")
            if how == "foreign_from_state":
                record[field["alt_name"]] = self._foreign(record)
            elif how in ("geocode", "jurisdiction"):
                # Filled in below, once the whole record is available.
                record.setdefault(field["alt_name"], None)

        self._geocode(record)
        self._assign_jurisdiction(record)
        return record

    def _value(self, field, row):
        """Read and coerce a single field according to its map entry."""
        raw = row.get(field["source"])
        kind = field.get("type", "A")

        if kind == "D":
            return normalize.parse_date(raw)
        if kind == "N":
            return normalize.parse_number(raw)
        if kind == "Z":
            return normalize.parse_zip(raw)
        if kind == "B":
            return normalize.parse_boolean(raw)

        text = normalize.clean_text(raw)

        # Expand the codes upstream leaves raw. Unknown codes pass through
        # unchanged rather than being dropped -- we'd rather surface real data
        # we didn't anticipate than lose it.
        transform = field.get("transform")
        if transform and text:
            if text in transform:
                return transform[text]
            key = (field["alt_name"], text)
            self.unknown_codes[key] = self.unknown_codes.get(key, 0) + 1

        return text

    def _foreign(self, record):
        """Whether the entity was formed outside Virginia.

        Replaces the old fixed-width `corp-foreign` flag, which no longer exists
        upstream; IncorpState now carries formation state directly.
        """
        state = record.get("state_formed")
        if not state:
            return None
        return normalize.abbreviate_state(state).upper() != "VA"

    def _geocode(self, record):
        """Attach coordinates for each address group that hits the cache."""
        if self.cache is None or not self.cache.available:
            return
        for group in self._address_groups.values():
            fields = group["fields"]
            coordinates = self.cache.coordinates(
                record.get(fields.get("street1"), ""),
                record.get(fields.get("street2"), ""),
                record.get(fields.get("city"), ""),
                record.get(fields.get("state"), ""),
                record.get(fields.get("zip"), ""),
            )
            if coordinates is not None:
                record[group["output"]] = coordinates

    def _assign_jurisdiction(self, record):
        """Attach the county or independent city containing the principal office.

        Needs coordinates, so it runs after geocoding -- an entity without a
        cached geocode gets no jurisdiction. That makes geocoding coverage the
        ceiling on jurisdiction coverage.
        """
        if self.jurisdictions is None or not self._jurisdiction_fields:
            return

        group = self._address_groups.get("address")
        if group is None:
            return

        area = self.jurisdictions.locate_coordinates(record.get(group["output"]))
        if area is None:
            return

        for field in self._jurisdiction_fields:
            name = field["alt_name"]
            if name == "fips":
                record[name] = area.fips
            elif name == "jurisdiction":
                record[name] = area.name
            elif name == "jurisdiction_type":
                record[name] = area.kind

    def report_unknown_codes(self):
        """Undocumented transform codes seen, most frequent first."""
        return sorted(self.unknown_codes.items(), key=lambda item: -item[1])
