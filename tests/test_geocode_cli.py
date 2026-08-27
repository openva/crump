"""Tests for the geocoder's command-line behaviour.

`geocode` is a script rather than a module, so it is loaded by executing the
part above `parse_args` -- enough to reach the constants and helpers without
running the tool.
"""

import pathlib
import re

GEOCODE = pathlib.Path(__file__).resolve().parent.parent / "geocode"


def geocode_namespace():
    """The script's constants and helpers, without running it.

    `geocode` is a script, not an importable module. Executing it under a name
    other than __main__ skips the entry-point guard, so nothing runs.
    """
    namespace = {"__name__": "geocode_under_test"}
    exec(compile(GEOCODE.read_text(), str(GEOCODE), "exec"), namespace)
    return namespace


class TestProgressKey:
    def test_documents_every_symbol_the_tool_emits(self):
        """A symbol printed but not in the key would be unexplained."""
        source = GEOCODE.read_text()
        emitted = set(re.findall(r'_tick\(options, "(.)"', source))
        documented = {symbol for symbol, _ in geocode_namespace()["PROGRESS_KEY"]}
        assert emitted <= documented, f"undocumented: {emitted - documented}"

    def test_documents_no_symbols_that_are_never_emitted(self):
        source = GEOCODE.read_text()
        emitted = set(re.findall(r'_tick\(options, "(.)"', source))
        documented = {symbol for symbol, _ in geocode_namespace()["PROGRESS_KEY"]}
        assert documented <= emitted, f"never emitted: {documented - emitted}"

    def test_every_symbol_is_a_single_character(self):
        """They are printed inline, one per address."""
        for symbol, _ in geocode_namespace()["PROGRESS_KEY"]:
            assert len(symbol) == 1

    def test_symbols_are_unique(self):
        key = geocode_namespace()["PROGRESS_KEY"]
        assert len({symbol for symbol, _ in key}) == len(key)

    def test_descriptions_are_terse(self):
        """The whole key has to fit on one terminal line."""
        key = geocode_namespace()["PROGRESS_KEY"]
        rendered = "  ".join(f"{s} {m}" for s, m in key)
        # Must fit an 80-column terminal without wrapping. This is the actual
        # constraint, not a bound fitted to whatever the string happens to be.
        assert len(rendered) <= 80, f"{len(rendered)} chars will wrap"
        for _, meaning in key:
            assert meaning
            assert len(meaning) <= 16

    def test_prints_the_key(self, capsys):
        geocode_namespace()["print_progress_key"]()
        printed = capsys.readouterr().out
        for symbol, meaning in geocode_namespace()["PROGRESS_KEY"]:
            assert f"{symbol} {meaning}" in printed

    def test_printed_line_fits_eighty_columns(self, capsys):
        geocode_namespace()["print_progress_key"]()
        for line in capsys.readouterr().out.splitlines():
            assert len(line) <= 80, f"{len(line)} chars will wrap"


class TestHaltMessage:
    """When geocoding gives up, it has to say why.

    A bare count is not actionable: DNS failure, connection timeout and HTTP
    503 all look identical as a row of `!` characters.
    """

    def message(self, error, url="https://example.test/geocode"):
        return geocode_namespace()["halt_message"](10, error, url)

    def test_reports_the_error_text(self):
        error = ConnectionError("Failed to resolve 'nowhere.invalid'")
        assert "Failed to resolve 'nowhere.invalid'" in self.message(error)

    def test_reports_the_error_type(self):
        """Distinguishes a timeout from a refused connection at a glance."""
        assert "ConnectionError" in self.message(ConnectionError("boom"))
        assert "TimeoutError" in self.message(TimeoutError("slow"))

    def test_names_the_service(self):
        """Which of the two geocoders failed."""
        rendered = self.message(ConnectionError("x"), url="https://vgin.test/q")
        assert "https://vgin.test/q" in rendered

    def test_reports_the_count(self):
        assert "10 consecutive API errors" in self.message(ConnectionError("x"))

    def test_survives_an_error_with_no_message(self):
        assert "Stopping" in self.message(ConnectionError())

    def test_is_multiline_and_labelled(self):
        lines = self.message(ConnectionError("boom")).strip().splitlines()
        assert len(lines) == 4
        assert any(line.strip().startswith("Service:") for line in lines)
        assert any(line.strip().startswith("Last error:") for line in lines)


class TestHaltSites:
    def test_every_halt_reports_the_last_error(self):
        """Both serial loops must use halt_message, not a bare count."""
        source = GEOCODE.read_text()
        halts = source.count("consecutive_errors >= MAX_CONSECUTIVE_ERRORS")
        # Every halt site calls it; the extra occurrence is the definition.
        calls = source.count("halt_message(") - source.count("def halt_message(")
        assert halts == calls, "a halt site is not reporting the last error"
        assert halts == 2

    def test_last_error_is_captured_wherever_it_is_counted(self):
        source = GEOCODE.read_text()
        assert source.count("consecutive_errors += 1") == source.count(
            "last_error = error"
        )
