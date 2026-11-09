"""Tests for the hand-labelled matcher gold set and its evaluator (T3, P05)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from eval_matcher_gold import (  # noqa: E402
    GOLD_PATH,
    STRATA,
    THRESHOLD,
    evaluate,
    evaluate_by_stratum,
    main,
)

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


def test_gold_set_has_at_least_forty_five_unique_cases():
    cases = load_cases()
    assert len(cases) >= 45
    assert len({case["id"] for case in cases}) == len(cases)


def test_at_least_fifteen_cases_are_stratum_tagged():
    tagged = [case for case in load_cases() if "stratum" in case]
    assert len(tagged) >= 15
    assert {case["stratum"] for case in tagged} == set(STRATA)
    for stratum in STRATA:
        assert sum(1 for case in tagged if case["stratum"] == stratum) >= 3


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


def test_evaluate_by_stratum_reports_every_stratum_at_threshold():
    result = evaluate_by_stratum(GOLD_PATH)
    assert set(result) == {"core", *STRATA}
    for name, metrics in result.items():
        assert metrics["cases"] > 0, name
        for metric in ("precision", "recall", "f1"):
            assert metrics[metric] >= THRESHOLD, (name, metric)


def test_evaluate_by_stratum_counts_add_up_to_overall():
    overall = evaluate(GOLD_PATH)
    by_stratum = evaluate_by_stratum(GOLD_PATH)
    for key in ("tp", "fp", "fn"):
        assert sum(metrics[key] for metrics in by_stratum.values()) == overall[key]


def test_negative_stratum_expects_zero_spans():
    negatives = [case for case in load_cases() if case.get("stratum") == "negative"]
    assert negatives
    for case in negatives:
        assert case["expected_spans"] == [], case["id"]
        assert find_spans(case["text"], case["glossary"]) == [], case["id"]


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
    # false positive. F1 alone would stay high, so the gate checks all three
    # metrics and precision's drop below 0.98 must fail the CLI.
    assert result["fn"] == 0
    assert result["fp"] == 1
    assert result["precision"] < THRESHOLD
    assert main([str(tmp_path / "dropped.jsonl")]) == 1
    assert dropped["surface"]


def test_cli_by_stratum_fails_when_a_stratum_span_is_dropped(tmp_path, capsys):
    cases = json.loads(json.dumps(load_cases()))
    tagged = next(
        case
        for case in cases
        if case.get("stratum") == "transliteration" and case["expected_spans"]
    )
    tagged["expected_spans"].pop()
    path = write_cases(tmp_path / "dropped_stratum.jsonl", cases)

    by_stratum = evaluate_by_stratum(path)
    assert by_stratum["transliteration"]["fp"] >= 1
    assert main([str(path), "--by-stratum"]) == 1
    assert '"transliteration"' in capsys.readouterr().out


def test_unknown_stratum_is_rejected(tmp_path):
    cases = json.loads(json.dumps(load_cases()))
    cases[0]["stratum"] = "acronim"
    path = write_cases(tmp_path / "typo.jsonl", cases)

    with pytest.raises(ValueError, match="acronim"):
        evaluate(path)
    with pytest.raises(ValueError, match="acronim"):
        evaluate_by_stratum(path)
