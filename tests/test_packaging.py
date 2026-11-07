"""Packaging smoke tests.

These run against the source tree and do not build a wheel: every subpackage
must import, and the version the package reports must match ``pyproject.toml``.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import pkgutil
import re
from pathlib import Path

import pytest

import lexiforge

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _project_field(field: str) -> str:
    """Return a quoted field from the ``[project]`` table of pyproject.toml."""
    text = PYPROJECT.read_text(encoding="utf-8")
    project = re.split(r"^\[project\]\s*$", text, maxsplit=1, flags=re.MULTILINE)[1]
    project = re.split(r"^\[", project, maxsplit=1, flags=re.MULTILINE)[0]
    match = re.search(rf'^{field}\s*=\s*"([^"]+)"', project, re.MULTILINE)
    assert match is not None, f"{field} is missing from [project]"
    return match.group(1)


def test_every_subpackage_imports() -> None:
    modules = [
        info.name for info in pkgutil.walk_packages(lexiforge.__path__, prefix="lexiforge.")
    ]
    for module in modules:
        importlib.import_module(module)

    on_disk = {
        path.name
        for path in (ROOT / "lexiforge").iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    discovered = {module.split(".")[1] for module in modules if module.count(".") == 1}
    assert on_disk <= discovered


def test_version_matches_pyproject() -> None:
    assert lexiforge.__version__ == _project_field("version")


def test_installed_metadata_matches_pyproject() -> None:
    try:
        installed = importlib.metadata.version("lexiforge")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("lexiforge is not installed in this environment")
    assert installed == _project_field("version")


def test_wheel_filename_format_is_derivable() -> None:
    name = re.sub(r"[-_.]+", "_", _project_field("name"))
    version = _project_field("version")

    # PEP 440 release segment; the built wheel is a pure-Python one.
    assert re.fullmatch(r"\d+(?:\.\d+)+(?:[A-Za-z0-9.+!-]*)?", version)
    filename = f"{name}-{version}-py3-none-any.whl"
    assert re.fullmatch(r"[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-py3-none-any\.whl", filename)
