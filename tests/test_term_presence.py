"""Tests for the term-present-anywhere sensitivity metric (task P03).

The metric is descriptive-only. H1 (real-term recall) and H2 (insertions)
remain the frozen confirmatory definitions in docs/preregistration.md section 3.
"""

from __future__ import annotations

import copy

import pytest

from lexiforge.score.match import score_file
from lexiforge.score.presence import presence_score


def glossary() -> list[dict]:
    return [
        {"id": "NEFT", "aliases": ["NEFT"]},
        {"id": "UPI", "aliases": ["UPI"]},
    ]


def test_reordered_utterance_is_present_but_not_strictly_aligned():
    result = presence_score("pay NEFT with UPI now", "now UPI with NEFT pay", glossary())

    # Token alignment sees two insertions and two misses, so strict recall is 0.
    assert result["strict"] == 0.0
    # Presence ignores position: both reference terms are somewhere in the
    # hypothesis, so the sensitivity metric is perfect.
    assert result["anywhere"] == 1.0


def test_repeats_are_counted_per_occurrence():
    result = presence_score("NEFT and NEFT", "NEFT", glossary())

    assert result["anywhere"] == 0.5
    assert result["by_term"]["NEFT"] == {
        "reference": 2,
        "hypothesis": 1,
        "strict_hits": 1,
        "anywhere_hits": 1,
        "strict": 0.5,
        "anywhere": 0.5,
    }


def test_suffix_is_not_a_token_boundary_hit():
    result = presence_score("NEFT", "NEFTAA", glossary())

    assert result["strict"] == 0.0
    assert result["anywhere"] == 0.0
    assert result["by_term"]["NEFT"]["hypothesis"] == 0


def test_empty_hypothesis_has_zero_presence():
    result = presence_score("pay NEFT by UPI", "", glossary())

    assert result["strict"] == 0.0
    assert result["anywhere"] == 0.0
    assert result["by_term"]["NEFT"]["reference"] == 1
    assert result["by_term"]["NEFT"]["hypothesis"] == 0


def test_hypothesis_only_term_is_reported_but_outside_denominator():
    result = presence_score("pay NEFT", "pay NEFT UPI", glossary())

    assert result["strict"] == 1.0
    assert result["anywhere"] == 1.0
    assert result["by_term"]["UPI"] == {
        "reference": 0,
        "hypothesis": 1,
        "strict_hits": 0,
        "anywhere_hits": 0,
        "strict": None,
        "anywhere": None,
    }


def test_no_reference_terms_yields_none_rates():
    result = presence_score("pay the bill", "pay the bill", glossary())

    assert result["strict"] is None
    assert result["anywhere"] is None
    assert result["by_term"] == {}


def test_empty_glossary_is_handled():
    result = presence_score("pay NEFT", "pay NEFT", [])

    assert result["strict"] is None
    assert result["anywhere"] is None
    assert result["by_term"] == {}


@pytest.mark.parametrize(
    ("reference", "hypothesis"),
    [
        ("pay NEFT by UPI", "pay NEFT by UPI"),
        ("pay NEFT by UPI", "pay UPI by NEFT"),
        ("NEFT and NEFT", "NEFT"),
        ("NEFT UPI KYC", "UPI KYC IFSC"),
        ("pay NEFT", "pay NEFT UPI"),
    ],
)
def test_strict_matches_the_frozen_score_file(reference, hypothesis):
    counts = score_file(reference, hypothesis, glossary())
    expected = counts["hits"] / counts["n_reference_occurrences"]

    assert presence_score(reference, hypothesis, glossary())["strict"] == expected


def test_glossary_is_not_mutated_and_calls_are_deterministic():
    terms = glossary()
    before = copy.deepcopy(terms)

    first = presence_score("pay NEFT by UPI", "pay UPI by NEFT", terms)
    second = presence_score("pay NEFT by UPI", "pay UPI by NEFT", terms)

    assert terms == before
    assert first == second
    assert set(first) == {"strict", "anywhere", "by_term"}
