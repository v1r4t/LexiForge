"""Tests for the committed-data consistency checker (P23, design §11).

The checker is read-only and runs in CI before pytest. It must pass on the
current tree even while P08/P14 artifacts are still landing, so the fixture
below is a minimal *consistent* repository and every failure test mutates a
single artifact.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts import check_data_consistency

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _core200_bytes(term_ids: list[str], *, newline: str = "\n") -> bytes:
    return json.dumps({"term_ids": term_ids}, indent=2).replace("\n", newline).encode("utf-8")


def _write_core200(root: Path, term_ids: list[str], *, newline: str = "\n") -> None:
    payload = _core200_bytes(term_ids, newline=newline)
    (root / "data" / "core200.json").write_bytes(payload)
    # The committed convention hashes the LF-normalised bytes.
    digest = hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()
    _write_text(root / "data" / "core200.json.sha256", digest + "\n")


def make_consistent_tree(root: Path) -> Path:
    """Create a minimal tree where every check should pass."""
    _write_json(
        root / "data" / "glossary.json",
        [{"term_id": "R0001"}, {"term_id": "F0001"}],
    )
    assignment = {
        str(i): {"real": ["R0001"], "fictional": ["F0001"]} for i in range(20)
    }
    _write_json(root / "data" / "assignment.json", assignment)

    for i in range(20):
        call_id = f"c{i:02d}"
        _write_json(
            root / "data" / "scripts" / f"{call_id}.json",
            {
                "call_id": call_id,
                "turns": [{"idx": 1, "glossary_terms": ["R0001"]}],
                "expected_real": ["R0001"],
                "expected_fictional": ["F0001"],
            },
        )

    _write_core200(root, [f"T{i:03d}" for i in range(200)])

    _write_text(root / "docs" / "design.md", "# Design\n")
    _write_text(root / "docs" / "runbook.md", "Run `make test`.\n")
    _write_text(
        root / "README.md",
        "# LexiForge\n\n- Design: [`docs/design.md`](docs/design.md)\n",
    )
    _write_text(
        root / "Makefile",
        ".PHONY: test lint\n\ntest:\n\tpython -m pytest\n\nlint:\n\truff check .\n",
    )

    gold = [
        {"id": "acronym", "text": "Use NACH.", "expected_spans": [
            {"start": 4, "end": 8, "surface": "NACH"}
        ]},
        {"id": "plain", "text": "UPI failed", "expected_spans": [
            {"start": 0, "end": 3, "surface": "UPI"}
        ]},
    ]
    _write_text(
        root / "tests" / "gold" / "matcher_gold.jsonl",
        "".join(json.dumps(case) + "\n" for case in gold),
    )
    return root


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    return make_consistent_tree(tmp_path)


def _errors(report: dict) -> str:
    return "\n".join(report["errors"])


def test_clean_tree_passes(tree: Path) -> None:
    report = check_data_consistency.check_all(tree)

    assert report["ok"] is True
    assert report["errors"] == []
    assert check_data_consistency.main([str(tree)]) == 0


def test_broken_script_id_is_an_error(tree: Path) -> None:
    script = tree / "data" / "scripts" / "c00.json"
    data = json.loads(script.read_text(encoding="utf-8"))
    data["turns"][0]["glossary_terms"] = ["MISSING"]
    _write_json(script, data)

    report = check_data_consistency.check_all(tree)

    assert report["ok"] is False
    assert "MISSING" in _errors(report)
    assert check_data_consistency.main([str(tree)]) == 1


def test_core200_sha_mismatch_is_an_error(tree: Path) -> None:
    core = tree / "data" / "core200.json"
    core.write_bytes(core.read_bytes() + b" ")

    report = check_data_consistency.check_all(tree)

    assert report["ok"] is False
    assert "sha256" in _errors(report)


def test_core200_sha_ignores_crlf_checkouts(tree: Path) -> None:
    # Windows checkouts rewrite LF to CRLF; the committed hash is over LF.
    _write_core200(tree, [f"T{i:03d}" for i in range(200)], newline="\r\n")

    report = check_data_consistency.check_all(tree)

    assert report["ok"] is True, _errors(report)


def test_duplicate_call_id_is_an_error(tree: Path) -> None:
    duplicate = tree / "data" / "scripts" / "c00-copy.json"
    _write_json(
        duplicate,
        {
            "call_id": "c00",
            "turns": [],
            "expected_real": [],
            "expected_fictional": [],
        },
    )

    report = check_data_consistency.check_all(tree)

    assert report["ok"] is False
    assert "duplicate" in _errors(report).lower()
    assert "c00" in _errors(report)


def test_missing_assignment_key_is_an_error(tree: Path) -> None:
    path = tree / "data" / "assignment.json"
    assignment = json.loads(path.read_text(encoding="utf-8"))
    del assignment["19"]
    _write_json(path, assignment)

    report = check_data_consistency.check_all(tree)

    assert report["ok"] is False
    assert "19" in _errors(report)


def test_missing_readme_linked_doc_is_an_error(tree: Path) -> None:
    readme = tree / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "- Gone: [doc](docs/gone.md)\n",
        encoding="utf-8",
    )

    report = check_data_consistency.check_all(tree)

    assert report["ok"] is False
    assert "docs/gone.md" in _errors(report)


def test_runbook_target_missing_from_makefile_is_an_error(tree: Path) -> None:
    runbook = tree / "docs" / "runbook.md"
    runbook.write_text(
        runbook.read_text(encoding="utf-8") + "\nRun `make report-page`.\n",
        encoding="utf-8",
    )

    report = check_data_consistency.check_all(tree)

    assert report["ok"] is False
    assert "report-page" in _errors(report)


def test_phony_target_without_rule_is_an_error(tree: Path) -> None:
    makefile = tree / "Makefile"
    makefile.write_text(
        ".PHONY: test lint ghost\n\ntest:\n\tpython -m pytest\n\nlint:\n\truff check .\n",
        encoding="utf-8",
    )

    report = check_data_consistency.check_all(tree)

    assert report["ok"] is False
    assert "ghost" in _errors(report)


def test_duplicate_gold_id_is_an_error(tree: Path) -> None:
    gold = tree / "tests" / "gold" / "matcher_gold.jsonl"
    line = gold.read_text(encoding="utf-8").splitlines(keepends=True)[0]
    gold.write_text(gold.read_text(encoding="utf-8") + line, encoding="utf-8")

    report = check_data_consistency.check_all(tree)

    assert report["ok"] is False
    assert "duplicate" in _errors(report).lower()


def test_missing_scripts_directory_is_a_warning(tree: Path) -> None:
    shutil.rmtree(tree / "data" / "scripts")

    report = check_data_consistency.check_all(tree)

    assert report["ok"] is True
    assert any("data/scripts" in warning for warning in report["warnings"])


def test_json_output_is_ascii_and_parsable(tree: Path, capsys) -> None:
    readme = tree / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "- Missing: [doc](docs/na\u00efve.md)\n",
        encoding="utf-8",
    )

    assert check_data_consistency.main(["--json", str(tree)]) == 1
    out = capsys.readouterr().out

    parsed = json.loads(out)
    assert parsed["ok"] is False
    assert out.isascii()


def test_repository_tree_is_consistent() -> None:
    report = check_data_consistency.check_all(REPO_ROOT)

    assert report["ok"] is True, _errors(report)
    assert report["errors"] == []
