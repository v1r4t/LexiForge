"""Tests for the phonetic hard-negative context arm.

The arm must stay canonically disjoint from the expected terms while every
candidate remains phonetically close to at least one of them. Candidates are
drawn from the full glossary, never from a reference script.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lexiforge.canon import canon
from lexiforge.contexts.hard_negative import build_hard_negative, rank_candidates
from lexiforge.select.phonetic import (
    is_hard_negative_pair,
    skeleton_similarity,
)

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_IDS = [f"F{i:04d}" for i in range(1, 9)] + ["R0005", "R0006", "R0025"]


def _glossary() -> list[dict]:
    return json.loads((ROOT / "data" / "glossary.json").read_text(encoding="utf-8"))


def _by_id(glossary: list[dict], term_id: str) -> dict:
    return next(entry for entry in glossary if entry["term_id"] == term_id)


def _surfaces(entry: dict) -> list[str]:
    return [
        entry["canonical"],
        *entry.get("scoring_aliases", []),
        *entry.get("spoken_forms", []),
    ]


def _expected_surfaces(glossary: list[dict]) -> list[str]:
    return [
        surface
        for term_id in EXPECTED_IDS
        for surface in _surfaces(_by_id(glossary, term_id))
    ]


class TestBuildHardNegative:
    def test_returns_exactly_the_budget_in_unique_surfaces(self):
        glossary = _glossary()
        result = build_hard_negative(glossary, _expected_surfaces(glossary))

        assert len(result) == 200
        assert len(set(result)) == 200
        assert len({canon(surface) for surface in result}) == 200

    def test_has_zero_canonical_overlap_with_expected_terms(self):
        glossary = _glossary()
        expected = _expected_surfaces(glossary)
        result = build_hard_negative(glossary, expected)

        expected_canon = {canon(term) for term in expected}
        returned_canon = {canon(surface) for surface in result}
        assert returned_canon.isdisjoint(expected_canon)

    def test_every_candidate_is_phonetically_close_to_an_expected_term(self):
        glossary = _glossary()
        expected = _expected_surfaces(glossary)
        result = build_hard_negative(
            glossary, expected, min_similarity=0.55
        )

        for surface in result:
            best = max(skeleton_similarity(surface, term) for term in expected)
            assert best >= 0.55, (surface, best)

    def test_repeated_calls_and_input_order_are_deterministic(self):
        glossary = _glossary()
        expected = _expected_surfaces(glossary)

        first = build_hard_negative(glossary, expected, seed=7)
        second = build_hard_negative(glossary, expected, seed=7)
        reordered = build_hard_negative(
            list(reversed(glossary)), list(reversed(expected)), seed=7
        )

        assert first == second == reordered

    def test_deterministic_across_python_hash_seeds(self):
        child = """
import json
from pathlib import Path

from lexiforge.contexts.hard_negative import build_hard_negative

root = Path.cwd()
glossary = json.loads((root / "data" / "glossary.json").read_text(encoding="utf-8"))
expected_ids = [f"F{i:04d}" for i in range(1, 9)] + ["R0005", "R0006", "R0025"]
by_id = {entry["term_id"]: entry for entry in glossary}
expected = []
for term_id in expected_ids:
    entry = by_id[term_id]
    expected.append(entry["canonical"])
    expected.extend(entry.get("scoring_aliases", []))
    expected.extend(entry.get("spoken_forms", []))
print(json.dumps(build_hard_negative(glossary, expected, seed=7)))
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(ROOT), env.get("PYTHONPATH", "")) if p
        )
        outputs = []
        for hash_seed in ("0", "1"):
            env["PYTHONHASHSEED"] = hash_seed
            proc = subprocess.run(
                [sys.executable, "-c", child],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert proc.returncode == 0, proc.stderr
            outputs.append(json.loads(proc.stdout))

        assert len(outputs[0]) == 200
        assert outputs[0] == outputs[1]

    def test_too_small_pool_raises_value_error(self):
        glossary = [
            {"term_id": "T1", "canonical": "Nach"},
            {"term_id": "T2", "canonical": "Nack"},
        ]

        with pytest.raises(ValueError, match="pool"):
            build_hard_negative(glossary, ["Nach"], budget=2)

    def test_punctuation_and_case_variants_are_deduped(self):
        glossary = [
            {"term_id": "T1", "canonical": "Nach"},
            {
                "term_id": "T2",
                "canonical": "Nack",
                "scoring_aliases": ["nack", "NACK", "Nack!", "N.A.C.K."],
            },
        ]

        ranked = rank_candidates(glossary, ["Nach"])
        result = build_hard_negative(glossary, ["Nach"], budget=1)

        assert len(ranked) == 1
        assert len(result) == 1
        assert canon(result[0]) == "nack"

    def test_same_skeleton_pairs_are_not_excluded(self):
        glossary = [
            {"term_id": "T1", "canonical": "Nach"},
            {"term_id": "T2", "canonical": "Nack"},
        ]

        # The phonetic veto calls this a hard-negative pair. It is exactly the
        # kind of candidate the arm must keep, so it cannot be an exclusion
        # filter here.
        assert is_hard_negative_pair("Nack", "Nach") is True
        assert canon(build_hard_negative(glossary, ["Nach"], budget=1)[0]) == "nack"

    def test_expected_terms_can_be_glossary_entries_or_ids(self):
        glossary = [
            {
                "term_id": "T1",
                "canonical": "Nach",
                "scoring_aliases": ["Naach"],
            },
            {"term_id": "T2", "canonical": "Nack"},
        ]

        result = build_hard_negative(glossary, [{"term_id": "T1"}], budget=1)

        assert canon(result[0]) == "nack"

    def test_empty_expected_terms_raise_value_error(self):
        glossary = [{"term_id": "T1", "canonical": "Nach"}]

        with pytest.raises(ValueError, match="expected"):
            build_hard_negative(glossary, [])


class TestRankCandidates:
    def test_returns_scored_pairs_sorted_by_descending_similarity(self):
        glossary = _glossary()
        expected = _expected_surfaces(glossary)

        ranked = rank_candidates(glossary, expected, min_similarity=0.55)

        assert ranked
        assert all(isinstance(item, tuple) and len(item) == 2 for item in ranked)
        scores = [score for score, _ in ranked]
        assert scores == sorted(scores, reverse=True)
        assert all(score >= 0.55 for score in scores)
        assert len({canon(surface) for _, surface in ranked}) == len(ranked)

    def test_min_similarity_filters_below_threshold_candidates(self):
        glossary = [
            {"term_id": "T1", "canonical": "Nach"},
            {"term_id": "T2", "canonical": "Nack"},
            {"term_id": "T3", "canonical": "Bakery"},
        ]

        ranked = rank_candidates(glossary, ["Nach"], min_similarity=0.9)

        assert [canon(surface) for _, surface in ranked] == ["nack"]
