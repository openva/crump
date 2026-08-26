"""Writing normalized records as CSV and JSON.

The old code hand-assembled JSON by writing an opening bracket, appending
`,\n` after each record, then seeking backwards to truncate the trailing comma.
That is illegal on a text-mode file in Python 3 and fragile regardless, so
JsonArrayWriter tracks whether it has written anything and emits the separator
*before* each record instead.
"""

import csv
import datetime
import json


def json_default(value):
    """Serialize dates as ISO strings; everything else is already JSON-safe."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value)!r}")


class CsvWriter:
    """Writes records as CSV, with dates rendered ISO and None as empty."""

    def __init__(self, path, field_names):
        self.field_names = field_names
        self._handle = open(path, "w", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(
            self._handle, fieldnames=field_names, extrasaction="ignore"
        )
        self._writer.writeheader()

    def write(self, record):
        self._writer.writerow(
            {name: _flatten(record.get(name)) for name in self.field_names}
        )

    def close(self):
        self._handle.close()


def _flatten(value):
    """Render a value for a CSV cell."""
    if value is None:
        return ""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


class JsonArrayWriter:
    """Writes records as a single JSON array, streaming."""

    def __init__(self, path):
        self._handle = open(path, "w", encoding="utf-8")
        self._handle.write("[\n")
        self._written = 0

    def write(self, record):
        if self._written:
            self._handle.write(",\n")
        json.dump(record, self._handle, default=json_default)
        self._written += 1

    def close(self):
        self._handle.write("\n]\n")
        self._handle.close()


class JsonLinesWriter:
    """Writes one JSON object per line.

    Preferable to a single array for files this size: consumers can stream it,
    and appending doesn't require rewriting a closing bracket.
    """

    def __init__(self, path):
        self._handle = open(path, "w", encoding="utf-8")

    def write(self, record):
        json.dump(record, self._handle, default=json_default)
        self._handle.write("\n")

    def close(self):
        self._handle.close()
