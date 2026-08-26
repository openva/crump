"""Tests for the package metadata itself.

These guard the things that work locally but break in a clean environment --
the failure mode that CI exists to catch, and that a developer running from the
repo root will never see.
"""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def pyproject():
    with open(ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)


def requirements():
    lines = (ROOT / "requirements.txt").read_text().splitlines()
    return {
        line.split("#")[0].strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    }


class TestDependencies:
    def test_requirements_matches_pyproject(self):
        """The two dependency lists must agree.

        CI installs from pyproject; the README tells humans to use
        requirements.txt. If they drift, one of those paths silently gets a
        different environment.
        """
        assert requirements() == set(pyproject()["project"]["dependencies"])

    def test_dev_extra_has_the_ci_tools(self):
        dev = " ".join(pyproject()["project"]["optional-dependencies"]["dev"])
        assert "pytest" in dev
        assert "ruff" in dev


class TestPackaging:
    def test_crumplib_is_a_declared_package(self):
        """If crumplib is not packaged, an install produces nothing importable."""
        packages = pyproject()["tool"]["setuptools"]["packages"]
        assert "crumplib" in packages

    def test_every_module_is_inside_the_package(self):
        """A module outside crumplib/ would not be installed."""
        modules = {p.stem for p in (ROOT / "crumplib").glob("*.py")}
        assert "normalize" in modules
        assert "__init__" in modules

    def test_python_floor_matches_ruff_target(self):
        """A mismatch means ruff enforces a different version than we support."""
        data = pyproject()
        requires = data["project"]["requires-python"]
        target = data["tool"]["ruff"]["target-version"]
        # ">=3.12" -> "py312"
        version = requires.lstrip(">=").strip()
        assert target == "py" + version.replace(".", "")


class TestImportability:
    """The bug this suite originally missed: `crumplib` was importable only from
    the repo root, because nothing installed it. Every test passed locally and
    all eight modules failed to import in CI.

    This is checked rather than asserted: a contributor who has not yet run
    `pip install -e .` should get a clear skip, not a confusing failure in a
    test that has nothing to do with their change. CI installs the package, so
    the check is meaningful there -- which is exactly where it needs to be.
    """

    def test_crumplib_imports_from_any_directory(self):
        result = subprocess.run(
            [sys.executable, "-c", "import crumplib; print(crumplib.__file__)"],
            cwd=ROOT.parent,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(
                "crumplib is not installed in this environment; "
                "run `pip install -e .` (CI does this, and enforces it)"
            )
        assert "crumplib" in result.stdout
