from __future__ import annotations

from lexiforge.select.bm25 import BM25Index, selector_recall_decomposition


def test_exact_token_match_ranks_correctly():
    glossary = [
        {"id": "NEFT", "canonical": "NEFT", "aliases": ["NEFT"]},
        {"id": "UPI", "canonical": "UPI", "aliases": ["UPI"]},
        {"id": "IFSC", "canonical": "IFSC", "aliases": ["IFSC"]},
    ]
    idx = BM25Index(glossary)
    # query with exact token for NEFT
    results = idx.select(["NEFT transfer"], budget=200)
    assert results[0] == "NEFT", results


def test_garbled_token_yields_no_hit():
    # Baseline weakness: garbled token yields no hit (asserted deliberately)
    glossary = [
        {"id": "NEFT", "canonical": "NEFT"},
        {"id": "UPI", "canonical": "UPI"},
    ]
    idx = BM25Index(glossary)
    results = idx.select(["N3FT tr4nsfr"], budget=200)
    # garbled forms don't match canonical tokens
    assert "NEFT" not in results


def test_decomposition_arithmetic_on_hand_built_example():
    # Hand-built example
    pass1_errors = [
        {"term_id": "E1"},  # absent from glossary
        {"term_id": "E2"},  # in glossary, not in candidates
        {"term_id": "E3"},  # in glossary, in candidates, not in top200 selected
        {"term_id": "E4"},  # in glossary, in candidates, in top200 selected
    ]
    glossary_ids = ["E2", "E3", "E4", "G1"]
    candidate_ids = ["E3", "E4", "G1"]  # E2 not in candidates
    selected = ["E4", "G1"]  # top200 contains E4 but not E3

    res = selector_recall_decomposition(pass1_errors, selected, glossary_ids, candidate_ids)
    # coverage: errors absent from glossary / total errors = 1/4 = 0.25 (E1 absent)
    assert abs(res["coverage"] - 0.25) < 1e-9
    # retrieval: of rest in glossary (E2,E3,E4 = 3), share entering candidate set = (E3,E4)/3 = 2/3
    assert abs(res["retrieval"] - 2.0 / 3.0) < 1e-9
    # ranking: of those in candidates (E3,E4 = 2), share inside top200 = (E4)/2 = 0.5
    assert abs(res["ranking"] - 0.5) < 1e-9
