"""Tests for the oracle-200 and oracle-minimal control arms (design §2, §5).

``oracle-minimal`` is the spoken terms only; ``oracle-200`` is those terms
followed by seeded, canonically disjoint padding to an exact budget. The arm
is a positive control, so it must contain every spoken term, carry no true
term in its padding, and reproduce byte-identically in a fresh process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lexiforge.canon import canon
from lexiforge.contexts.oracle import build_oracle_200, build_oracle_minimal

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_IDS = ["F0001", "F0002", "F0003", "R0005", "R0006", "R0025"]


def _glossary() -> list[dict]:
    return json.loads((ROOT / "data" / "glossary.json").read_text(encoding="utf-8"))


def _by_id(glossary: list[dict], term_id: str) -> dict:
    return next(entry for entry in glossary if entry["term_id"] == term_id)


def _expected_surfaces(glossary: list[dict]) -> list[str]:
    return [_by_id(glossary, term_id)["canonical"] for term_id in EXPECTED_IDS]


def _canon_set(items: list[str]) -> set[str]:
    return {canon(item) for item in items}


class TestBuildOracle200:
    def test_returns_exactly_the_budget_in_unique_canon_surfaces(self):
        glossary = _glossary()
        result = build_oracle_200(_expected_surfaces(glossary), glossary)

        assert len(result) == 200
        assert len(_canon_set(result)) == 200

    def test_respects_a_smaller_budget(self):
        glossary = _glossary()
        expected = _expected_surfaces(glossary)

        result = build_oracle_200(expected, glossary, budget=10)

        assert len(result) == 10
        assert len(_canon_set(result)) == 10

    def test_spoken_terms_are_present_and_first_in_input_order(self):
        glossary = _glossary()
        expected = _expected_surfaces(glossary)

        result = build_oracle_200(expected, glossary)

        assert result[: len(expected)] == expected
        assert _canon_set(expected) <= _canon_set(result)

    def test_glossary_ids_resolve_to_their_canonical_surfaces(self):
        glossary = _glossary()

        result = build_oracle_200(EXPECTED_IDS, glossary)
        expected = _expected_surfaces(glossary)

        assert result[: len(expected)] == expected

    def test_padding_is_canonically_disjoint_from_every_expected_term(self):
        glossary = _glossary()
        expected = _expected_surfaces(glossary)

        result = build_oracle_200(expected, glossary)

        assert _canon_set(result[len(expected) :]).isdisjoint(
            _canon_set(expected)
        )

    def test_padding_never_repeats_an_expected_alias(self):
        glossary = [
            {
                "term_id": "T1",
                "canonical": "NirSathi",
                "scoring_aliases": ["Nir Sathi"],
            },
            {"term_id": "T2", "canonical": "Nir Sathi"},
            {"term_id": "T3", "canonical": "NEFT"},
        ]

        # "Nir Sathi" is a pad candidate with its own canon key, but it is an
        # alias of the expected entry, not a non-true term.
        result = build_oracle_200(["T1"], glossary, budget=2)

        assert result[0] == "NirSathi"
        assert _canon_set(result[1:]).isdisjoint(
            {"nirsathi", canon("Nir Sathi")}
        )

    def test_glossary_permutation_does_not_change_the_result(self):
        glossary = _glossary()
        expected = _expected_surfaces(glossary)

        first = build_oracle_200(expected, glossary, seed=7)
        second = build_oracle_200(expected, list(reversed(glossary)), seed=7)

        assert first == second

    def test_seed_changes_padding_but_never_the_spoken_prefix(self):
        glossary = _glossary()
        expected = _expected_surfaces(glossary)

        zero = build_oracle_200(expected, glossary, seed=0)
        one = build_oracle_200(expected, glossary, seed=1)

        assert zero[: len(expected)] == one[: len(expected)] == expected
        assert zero[len(expected) :] != one[len(expected) :]

    def test_small_glossary_raises_instead_of_shrinking_the_arm(self):
        glossary = [
            {"term_id": "T1", "canonical": "NEFT"},
            {"term_id": "T2", "canonical": "UPI"},
        ]

        with pytest.raises(ValueError, match="padding"):
            build_oracle_200(["NEFT"], glossary, budget=3)

    def test_expected_terms_larger_than_budget_raise(self):
        glossary = _glossary()

        with pytest.raises(ValueError, match="budget"):
            build_oracle_200(EXPECTED_IDS, glossary, budget=2)

    def test_empty_expected_terms_raise(self):
        with pytest.raises(ValueError, match="expected"):
            build_oracle_200([], _glossary())

    def test_non_int_budget_raises(self):
        with pytest.raises(TypeError):
            build_oracle_200(["NEFT"], _glossary(), budget=2.5)

    def test_deterministic_across_python_hash_seeds(self):
        child = """
import json
from pathlib import Path

from lexiforge.contexts.oracle import build_oracle_200, build_oracle_minimal

root = Path.cwd()
glossary = json.loads((root / "data" / "glossary.json").read_text(encoding="utf-8"))
ids = ["F0001", "F0002", "F0003", "R0005", "R0006", "R0025"]
print(json.dumps({
    "padded": build_oracle_200(ids, glossary, seed=7),
    "minimal": build_oracle_minimal(["NEFT", "UPI", "NEFT"]),
}, ensure_ascii=True))
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
            outputs.append(proc.stdout)

        assert len(json.loads(outputs[0])["padded"]) == 200
        assert outputs[0] == outputs[1]


class TestBuildOracleMinimal:
    def test_returns_only_the_spoken_terms(self):
        assert build_oracle_minimal(["NEFT", "UPI", "KYC"]) == [
            "NEFT",
            "UPI",
            "KYC",
        ]

    def test_dedupes_by_canonical_key_keeping_first_spelling(self):
        result = build_oracle_minimal(["UPI", "upi", "NEFT", "neft"])

        assert result == ["UPI", "NEFT"]

    def test_accepts_glossary_style_entries(self):
        result = build_oracle_minimal(
            [{"term_id": "T1", "canonical": "NEFT"}, "NEFT", "BBPS"]
        )

        assert result == ["NEFT", "BBPS"]

    def test_empty_expected_terms_raise(self):
        with pytest.raises(ValueError, match="expected"):
            build_oracle_minimal([])
