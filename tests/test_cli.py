"""Tests for CLI commands.

These exist because the CLI previously shipped two commands that could not run
(missing optimiser method, non-cp1252-safe output). Every command must be
invoked, not just imported.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lexiforge.cli import app

runner = CliRunner()

GLOSSARY = [
    {"term_id": "R1", "canonical": "UPI", "scoring_aliases": ["UPI"]},
    {"term_id": "R2", "canonical": "NEFT", "scoring_aliases": ["NEFT"]},
    {"term_id": "R3", "canonical": "Zorbix", "scoring_aliases": ["Zorbix"]},
]


def _write(path: Path, payload) -> Path:
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8",
    )
    return path


def test_info_exits_cleanly():
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0, result.output
    assert "LexiForge" in result.output
    assert "\u2713" not in result.output  # ASCII only


def test_canon_prints_key():
    result = runner.invoke(app, ["canon", "NEFT"])
    assert result.exit_code == 0
    assert "neft" in result.output


def test_validate_accepts_good_config(tmp_path: Path):
    path = _write(tmp_path / "cfg.json", {"model": "prisma-v3.0", "language": "hi"})
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_validate_rejects_bad_config(tmp_path: Path):
    path = _write(tmp_path / "cfg.json", {"language": 5})
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_optimize_writes_selection(tmp_path: Path):
    glossary = _write(tmp_path / "glossary.json", GLOSSARY)
    out = tmp_path / "context.json"
    result = runner.invoke(
        app,
        [
            "optimize",
            "--glossary",
            str(glossary),
            "--hypothesis",
            "mera NEFT transfer fail ho gaya",
            "--max-terms",
            "2",
            "--call-type",
            "upi_failed",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["selected"], payload
    assert payload["budget"] == 2
    assert "selected" in result.output


def test_optimize_missing_glossary_fails_cleanly(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "optimize",
            "--glossary",
            str(tmp_path / "nope.json"),
            "--hypothesis",
            "text",
        ],
    )
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_export_web_command_reports_missing_transcripts(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "export-web",
            "--transcripts",
            str(tmp_path / "missing"),
            "--refs",
            str(tmp_path / "missing"),
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 1
    assert "FAIL" in result.output
