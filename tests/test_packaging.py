"""Packaging smoke tests.

These run against the source tree and do not require an installed wheel: every
subpackage must import, and the version the package reports must match
``pyproject.toml``.

P25 (Phase 6 — engineering hardening) extends them so that wheel and package
discovery stays glob-based: ``include = ["lexiforge*"]`` must pick up new
subpackages such as ``lexiforge.study`` (P14) and report modules such as
``lexiforge.report.provenance`` (P17) without a hand-maintained allowlist.
"""

from __future__ import annotations

import ast
import importlib
import importlib.metadata
import importlib.util
import pkgutil
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import setuptools

import lexiforge

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _table_body(name: str) -> str:
    """Return the body of a TOML table from pyproject.toml."""
    text = PYPROJECT.read_text(encoding="utf-8")
    pattern = rf"^\[{re.escape(name)}\]\s*$(.*?)(?=^\[|\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    assert match is not None, f"[{name}] is missing from pyproject.toml"
    return match.group(1)


def _project_field(field: str) -> str:
    """Return a quoted field from the ``[project]`` table of pyproject.toml."""
    text = PYPROJECT.read_text(encoding="utf-8")
    project = re.split(r"^\[project\]\s*$", text, maxsplit=1, flags=re.MULTILINE)[1]
    project = re.split(r"^\[", project, maxsplit=1, flags=re.MULTILINE)[0]
    match = re.search(rf'^{field}\s*=\s*"([^"]+)"', project, re.MULTILINE)
    assert match is not None, f"{field} is missing from [project]"
    return match.group(1)


def _include_globs() -> list[str]:
    """Return the ``packages.find`` include globs from pyproject.toml."""
    body = _table_body("tool.setuptools.packages.find")
    match = re.search(r"^include\s*=\s*\[([^\]]*)\]", body, re.MULTILINE)
    assert match is not None, "packages.find.include is missing"
    return re.findall(r'"([^"]+)"', match.group(1))


def _on_disk_packages() -> set[str]:
    """Return every importable package under ``lexiforge/``."""
    return {
        ".".join(init.parent.relative_to(ROOT).parts)
        for init in (ROOT / "lexiforge").rglob("__init__.py")
    }


def _optional_import(module: str) -> None:
    """Import ``module`` when its dependency has landed; skip otherwise."""
    try:
        spec = importlib.util.find_spec(module)
    except ModuleNotFoundError:  # parent package absent (P14/P17 not merged yet)
        spec = None
    if spec is None:
        pytest.skip(f"{module} is not present in this checkout")
    importlib.import_module(module)


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


def test_project_metadata_is_pep440_consistent() -> None:
    version = _project_field("version")
    name = _project_field("name")

    # PEP 440 release segment; the distribution name is a valid project slug.
    assert re.fullmatch(r"\d+(?:\.\d+)+(?:[A-Za-z0-9.+!-]*)?", version)
    assert re.fullmatch(r"[a-z][a-z0-9-]*", name.lower())
    assert name.lower() == "lexiforge"


def test_package_discovery_is_glob_based_without_allowlist() -> None:
    """One glob covers every subpackage; no hand-maintained package list."""
    assert _include_globs() == ["lexiforge*"]

    body = _table_body("tool.setuptools.packages.find")
    assert not re.search(r"^\s*packages\s*=", body, re.MULTILINE), "allowlist found"
    assert not re.search(r"^\s*exclude\s*=", body, re.MULTILINE), "exclude list found"


def test_discovery_covers_every_on_disk_package() -> None:
    found = set(setuptools.find_packages(where=str(ROOT), include=_include_globs()))
    assert _on_disk_packages() <= found


def test_discovery_covers_new_subpackages_without_allowlist(tmp_path: Path) -> None:
    """A synthetic P14/P17 tree is discovered by the configured globs alone."""
    for package in ("lexiforge", "lexiforge/study", "lexiforge/report", "lexiforge/newphase"):
        directory = tmp_path / package
        directory.mkdir(parents=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")

    found = set(setuptools.find_packages(where=str(tmp_path), include=_include_globs()))
    assert {"lexiforge.study", "lexiforge.report", "lexiforge.newphase"} <= found


@pytest.mark.parametrize(
    "module",
    ["lexiforge.study", "lexiforge.report.provenance"],
)
def test_new_modules_import_when_present(module: str) -> None:
    """Importable from the source tree once the owning worker has merged."""
    _optional_import(module)


def test_console_entry_point_resolves() -> None:
    body = _table_body("project.scripts")
    match = re.search(r'^lexiforge\s*=\s*"([^"]+)"', body, re.MULTILINE)
    assert match is not None, "lexiforge console script is missing"

    module_name, _, attribute = match.group(1).partition(":")
    assert module_name and attribute
    entry_point = getattr(importlib.import_module(module_name), attribute)
    assert callable(entry_point)


def test_package_modules_do_not_import_tests_or_scripts() -> None:
    forbidden = {"pytest", "scripts"}
    offenders: list[str] = []

    for path in (ROOT / "lexiforge").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            for root in sorted(roots & forbidden):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} imports {root}")

    assert not offenders, offenders


def test_wheel_contains_study_and_report_modules(tmp_path: Path) -> None:
    """``pip wheel`` ships study and report modules via the configured globs."""
    if importlib.util.find_spec("pip") is None:
        pytest.skip("pip is not available in this environment")

    staging = tmp_path / "staging"
    shutil.copytree(
        ROOT / "lexiforge",
        staging / "lexiforge",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(PYPROJECT, staging / "pyproject.toml")

    # P14 and P17 are separate workers. Stub their files when absent so this
    # check exercises those package paths on every branch; when present the
    # real modules are the ones packaged.
    study_init = staging / "lexiforge" / "study" / "__init__.py"
    study_init.parent.mkdir(exist_ok=True)
    if not study_init.exists():
        study_init.write_text('"""Study helpers."""\n', encoding="utf-8")
    provenance = staging / "lexiforge" / "report" / "provenance.py"
    if not provenance.exists():
        provenance.write_text('"""Provenance helpers."""\n', encoding="utf-8")

    wheel_dir = tmp_path / "wheel"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(staging),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())

    expected = {
        path.relative_to(staging).as_posix()
        for path in (staging / "lexiforge").rglob("*.py")
    }
    assert not expected - names, sorted(expected - names)
    assert not {name for name in names if name.startswith(("tests/", "scripts/"))}
