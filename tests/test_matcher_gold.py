"""Tests for the hand-labelled matcher gold set and its evaluator (T3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from eval_matcher_gold import GOLD_PATH, THRESHOLD, evaluate, main  # noqa: E402

from lexiforge.score.match import find_spans  # noqa: E402


def load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in GOLD_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def as_span(span: dict) -> dict:
    return {
        "term_id": span["term_id"],
        "start": span["start"],
        "end": span["end"],
        "surface": span["surface"],
    }


def test_gold_set_has_exactly_thirty_unique_cases():
    cases = load_cases()
    assert len(cases) == 30
    assert len({case["id"] for case in cases}) == 30


def test_expected_surfaces_index_raw_text():
    for case in load_cases():
        for span in case["expected_spans"]:
            assert case["text"][span["start"] : span["end"]] == span["surface"], case["id"]


def test_every_expected_span_matches_find_spans():
    for case in load_cases():
        predicted = [as_span(span) for span in find_spans(case["text"], case["glossary"])]
        expected = [as_span(span) for span in case["expected_spans"]]
        assert predicted == expected, case["id"]


def test_evaluate_scores_gold_set_at_full_marks():
    result = evaluate(GOLD_PATH)
    assert result["precision"] >= THRESHOLD
    assert result["recall"] >= THRESHOLD
    assert result["f1"] >= THRESHOLD
    assert result["tp"] == sum(len(case["expected_spans"]) for case in load_cases())
    assert result["fp"] == 0
    assert result["fn"] == 0


def test_cli_exits_zero_on_gold_set(capsys):
    assert main([str(GOLD_PATH)]) == 0
    assert '"f1"' in capsys.readouterr().out


def write_cases(path: Path, cases: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases),
        encoding="utf-8",
    )
    return path


def test_cli_exits_nonzero_when_a_span_is_dropped(tmp_path):
    cases = json.loads(json.dumps(load_cases()))
    dropped = cases[0]["expected_spans"].pop()

    result = evaluate(write_cases(tmp_path / "dropped.jsonl", cases))

    # The matcher still finds the span, so dropping the label shows up as a
    # false positive. F1 alone would stay at 0.981, so the gate checks all
    # three metrics and precision's drop below 0.98 must fail the CLI.
    assert result["fn"] == 0
    assert result["fp"] == 1
    assert result["precision"] < THRESHOLD
    assert main([str(tmp_path / "dropped.jsonl")]) == 1
    assert dropped["surface"]
