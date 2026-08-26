"""Field-level normalization for the SCC CSV feed.

The SCC replaced its fixed-width `cisbemon.txt` with a ZIP of CSVs, but the CSVs
carry a lot of fixed-width residue: every value is space-padded, EntityID has a
literal tab glued to the front, and each data row has a phantom trailing column.
Everything here exists to undo that.
"""

import calendar
import datetime
import re

# Interior runs of whitespace, left over from fixed-width padding.
_INTERIOR_WHITESPACE = re.compile(r"\s{2,}")

# Dates arrive already ISO-formatted; we only validate and null out sentinels.
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

# The feed uses 9999-* to mean "no date". The old fixed-width format used
# 0000-00-00 and 9999-99-99; accept all of them.
_NULL_DATE_YEARS = (9999,)

# US ZIP: five digits, optionally +4. Canadian postcodes also appear.
_ZIP5 = re.compile(r"^\d{5}$")
_ZIP9 = re.compile(r"^\d{5}-\d{4}$")
_ZIP9_UNSEPARATED = re.compile(r"^(\d{5})(\d{4})$")

#: Upstream spells states out in full; the geocode cache is keyed on USPS
#: abbreviations, so normalizing here is what makes the cache reusable.
STATE_ABBREVIATIONS = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    # Territories and common non-state values that appear in the feed.
    "puerto rico": "PR",
    "guam": "GU",
    "virgin islands": "VI",
    "american samoa": "AS",
    "northern mariana islands": "MP",
}


def clean_text(value):
    """Strip fixed-width padding and collapse interior whitespace runs.

    Also strips the literal tab the SCC prefixes to EntityID to force Excel to
    treat it as text.
    """
    if value is None:
        return ""
    return _INTERIOR_WHITESPACE.sub(" ", value.replace("\t", " ")).strip()


def parse_date(value):
    """Return a `datetime.date`, or None for blank and sentinel dates.

    The CSV feed already emits ISO `YYYY-MM-DD`, so unlike the old fixed-width
    code this does no reformatting -- it validates and rejects sentinels.
    Out-of-range components (month 13, day 32) are coerced rather than dropped,
    since a wrong-but-close date is more useful than a null for these records.
    """
    text = clean_text(value)
    if not text:
        return None

    match = _ISO_DATE.match(text)
    if not match:
        return None

    year, month, day = (int(part) for part in match.groups())

    # Sentinel values meaning "no date" -- 9999-12-31 dominates the feed.
    if year in _NULL_DATE_YEARS or year == 0:
        return None
    if month == 0 and day == 0:
        return None

    try:
        return datetime.date(year, month, day)
    except ValueError:
        pass

    # Coerce nonsense components into range rather than discarding the record.
    month = min(max(month, 1), 12)
    last_day = _days_in_month(year, month)
    day = min(max(day, 1), last_day)
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _days_in_month(year, month):
    """Days in a month. Uses calendar.monthrange, not the old itermonthdays()
    trick, which only worked because max() happened to ignore its zero padding.
    """
    return calendar.monthrange(year, month)[1]


def parse_zip(value):
    """Normalize a ZIP code, or return '' when there's nothing usable.

    The feed mostly ships `99999-9999` already hyphenated, so this validates and
    passes through rather than reformatting. Canadian postcodes are preserved
    as-is. All-zero values become ''.
    """
    text = clean_text(value).upper().replace(" ", "")
    if not text or set(text) <= {"0", "-"}:
        return ""

    if _ZIP5.match(text):
        return text

    if _ZIP9.match(text):
        # A +4 of 0000 carries no information; the feed uses it as a filler.
        return text[:5] if text.endswith("-0000") else text

    unseparated = _ZIP9_UNSEPARATED.match(text)
    if unseparated:
        five, plus_four = unseparated.groups()
        # A +4 of 0000 carries no information.
        return five if plus_four == "0000" else f"{five}-{plus_four}"

    # Canadian postcodes and anything else unrecognized pass through, so we
    # don't silently discard real data we simply didn't anticipate.
    return text


def parse_number(value):
    """Parse a numeric field to int, or None when absent.

    Upstream ships share counts as float strings ('5000.0'), which is why the
    old `int(value)` raised ValueError on every row.
    """
    text = clean_text(value)
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    # 99999999999 follows the feed's convention of all-9s meaning null.
    if number >= 99999999999:
        return None
    return int(number)


def parse_boolean(value):
    """Parse the feed's boolean-ish flags. Returns None when indeterminate."""
    text = clean_text(value).upper()
    if text in ("Y", "YES", "T", "TRUE", "1", "S"):
        return True
    if text in ("N", "NO", "F", "FALSE", "0"):
        return False
    return None


def abbreviate_state(value):
    """Convert a full state name to its USPS abbreviation.

    The geocode cache was built when the feed used abbreviations; the CSV feed
    spells them out. Normalizing here is what lifts the cache hit rate from 0%.
    Unrecognized values pass through cleaned but unchanged.
    """
    text = clean_text(value)
    if not text:
        return ""
    if len(text) == 2:
        return text.upper()
    return STATE_ABBREVIATIONS.get(text.lower(), text)
