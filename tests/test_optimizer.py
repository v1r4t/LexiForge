"""Tests for the vocabulary optimiser (real selector, no stubs)."""

from __future__ import annotations

import pytest

from lexiforge.optimizer import VocabularyOptimizer, to_selector_glossary

GLOSSARY = [
    {"term_id": "R1", "canonical": "UPI", "scoring_aliases": ["UPI", "u p i"]},
    {"term_id": "R2", "canonical": "NEFT", "scoring_aliases": ["NEFT"]},
    {"term_id": "R3", "canonical": "KYC", "scoring_aliases": ["KYC"]},
    {"term_id": "F1", "canonical": "Zorbix Card", "scoring_aliases": ["Zorbix Card"]},
]

# Several spelling variants of the hypothesis so more than one term clears the
# selector's tau threshold; a two-term glossary would only ever yield one.
RICH_GLOSSARY = [
    {"term_id": "R1", "canonical": "UPI", "scoring_aliases": ["UPI"]},
    {"term_id": "R2", "canonical": "NEFT", "scoring_aliases": ["NEFT"]},
    {"term_id": "R2b", "canonical": "NEFT transfer", "scoring_aliases": ["NEFT transfer"]},
    {"term_id": "R4", "canonical": "transfer", "scoring_aliases": ["transfer"]},
    {"term_id": "R5", "canonical": "fail", "scoring_aliases": ["fail"]},
    {"term_id": "F1", "canonical": "Zorbix Card", "scoring_aliases": ["Zorbix Card"]},
]

HYPOTHESIS = "mera NEFT transfer fail ho gaya"


def test_adapter_preserves_ids_and_aliases():
    adapted = to_selector_glossary(GLOSSARY)
    assert [e["id"] for e in adapted] == ["R1", "R2", "R3", "F1"]
    assert "UPI" in adapted[0]["aliases"]
    assert "u p i" in adapted[0]["aliases"]


def test_optimize_context_partitions_the_glossary():
    opt = VocabularyOptimizer()
    result = opt.optimize_context(
        HYPOTHESIS, glossary=RICH_GLOSSARY, call_type="upi_failed", max_terms=3
    )
    selected = result["selected"]
    assert 1 <= len(selected) <= 3
    assert len(selected) + len(result["left_out"]) == len(RICH_GLOSSARY)
    assert result["budget"] == 3
    assert result["metrics"]["glossary_size"] == len(RICH_GLOSSARY)


def test_selected_terms_carry_real_scores_not_placeholders():
    opt = VocabularyOptimizer()
    result = opt.optimize_context(HYPOTHESIS, glossary=RICH_GLOSSARY, max_terms=4)
    scores = [term["score"] for term in result["selected"]]
    assert all(isinstance(score, float) for score in scores)
    assert max(scores) > 0.0
    # The stub this replaced reported a constant 0.8 for everything.
    assert 0.8 not in scores or len(set(scores)) > 1


def test_most_relevant_term_ranks_first():
    opt = VocabularyOptimizer()
    result = opt.optimize_context(HYPOTHESIS, glossary=RICH_GLOSSARY, max_terms=4)
    assert result["selected"][0]["term_id"] in {"R2", "R2b"}


def test_unknown_glossary_shape_is_accepted_directly():
    selector_form = [{"id": "X1", "aliases": ["Zeta Pay"]}]
    opt = VocabularyOptimizer()
    result = opt.optimize_context("Zeta Pay se payment", glossary=selector_form, max_terms=1)
    assert result["selected"][0]["term_id"] == "X1"


def test_empty_glossary_raises():
    with pytest.raises(ValueError, match="glossary is empty"):
        VocabularyOptimizer().optimize_context("text", glossary=[], max_terms=5)


def test_budget_must_be_positive():
    with pytest.raises(ValueError, match="max_terms"):
        VocabularyOptimizer().optimize_context(HYPOTHESIS, glossary=GLOSSARY, max_terms=0)


def test_optimize_for_call_wrapper_still_works():
    opt = VocabularyOptimizer(RICH_GLOSSARY)
    result = opt.optimize_for_call(
        {"call_type": "upi_failed", "topic": "UPI failure"},
        current_list=["UPI"],
        budget=2,
        pass1_hypotheses=[HYPOTHESIS],
    )
    assert result.budget == 2
    assert result.selected
    assert result.mean_score > 0.0
