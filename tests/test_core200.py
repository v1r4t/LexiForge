"""Tests for lexiforge.glossary.core200 (docs/design.md §4 step 1)."""

from __future__ import annotations

import inspect
import random

import pytest

from lexiforge.glossary.core200 import (
    DEFAULT_QUOTAS,
    FICTIONAL_CAP,
    build_core200,
    freeze,
    verify_freeze,
)

BANDS = ["head", "high", "medium", "low"]


def _big_glossary():
    """360 entries across the 12 default categories; 72 fictional; a few
    declared hard-negative pairs among real terms."""
    entries = []
    for ci, cat in enumerate(DEFAULT_QUOTAS):
        for i in range(30):
            entries.append(
                {
                    "id": "%s-%03d" % (cat.upper(), i),
                    "category": cat,
                    "freq_band": BANDS[(i + ci) % len(BANDS)],
                    "fictional": (i % 5 == 4),
                }
            )
    pairs = [("UPI-000", "UPI-001"), ("CARDS-002", "CARDS-003"),
             ("KYC-005", "KYC-006")]
    by_id = {e["id"]: e for e in entries}
    for a, b in pairs:
        assert not by_id[a]["fictional"] and not by_id[b]["fictional"]
        by_id[a]["hard_negatives"] = [b]
        by_id[b]["hard_negatives"] = [a]
    return entries, pairs


def _declared_pairs(glossary):
    pairs = set()
    by_id = {e["id"]: e for e in glossary}
    for e in glossary:
        for p in e.get("hard_negatives", []):
            if p in by_id:
                pairs.add(frozenset((e["id"], p)))
    return pairs


def test_default_quotas_sum_to_200():
    assert sum(DEFAULT_QUOTAS.values()) == 200
    assert len(DEFAULT_QUOTAS) == 12


def test_exactly_200_unique_terms():
    glossary, _ = _big_glossary()
    out = build_core200(glossary, seed=0)
    assert set(out) == {"term_ids", "quotas", "glossary_hash", "seed", "built_at"}
    assert len(out["term_ids"]) == 200
    assert len(set(out["term_ids"])) == 200
    assert out["quotas"] == DEFAULT_QUOTAS
    assert out["seed"] == 0
    assert len(out["glossary_hash"]) == 64


def test_deterministic_same_seed():
    glossary, _ = _big_glossary()
    first = build_core200(glossary, seed=3)
    second = build_core200(glossary, seed=3)
    assert first["term_ids"] == second["term_ids"]
    assert first["glossary_hash"] == second["glossary_hash"]
    assert first["quotas"] == second["quotas"]


def test_glossary_order_independent():
    glossary, _ = _big_glossary()
    shuffled = list(glossary)
    random.Random(0).shuffle(shuffled)
    assert build_core200(glossary, seed=1)["term_ids"] == build_core200(
        shuffled, seed=1
    )["term_ids"]


def test_fictional_cap_holds():
    glossary, _ = _big_glossary()
    by_id = {e["id"]: e for e in glossary}
    out = build_core200(glossary, seed=0)
    n_fic = sum(1 for t in out["term_ids"] if by_id[t]["fictional"])
    assert n_fic <= FICTIONAL_CAP == 20


def test_pair_straddling_quota_boundary_never_split():
    glossary = [
        {"id": "A1", "category": "a", "freq_band": "head"},
        {"id": "A2", "category": "a", "freq_band": "high",
         "hard_negatives": ["A3"]},
        {"id": "A3", "category": "a", "freq_band": "high",
         "hard_negatives": ["A2"]},
        {"id": "A4", "category": "a", "freq_band": "low"},
    ]
    out = build_core200(glossary, quotas={"a": 2}, seed=0)
    ids = set(out["term_ids"])
    assert len(out["term_ids"]) == 2
    assert ("A2" in ids) == ("A3" in ids)  # all-or-nothing, never split


def test_all_pairs_all_or_nothing():
    glossary, _ = _big_glossary()
    out = build_core200(glossary, seed=0)
    ids = set(out["term_ids"])
    for pair in _declared_pairs(glossary):
        a, b = sorted(pair)
        assert (a in ids) == (b in ids), pair


def test_signature_is_glossary_quotas_seed_only():
    assert list(inspect.signature(build_core200).parameters) == [
        "glossary",
        "quotas",
        "seed",
    ]


def test_reference_key_rejected():
    with pytest.raises(TypeError):
        build_core200([{"id": "X", "category": "upi", "reference": "leaked"}])


def test_freeze_roundtrip_ok(tmp_path):
    glossary, _ = _big_glossary()
    payload = build_core200(glossary, seed=7)
    path = tmp_path / "core200.json"
    freeze(path, payload)
    assert verify_freeze(path) is True


def test_verify_freeze_detects_tampering(tmp_path):
    glossary, _ = _big_glossary()
    payload = build_core200(glossary, seed=7)
    path = tmp_path / "core200.json"
    freeze(path, payload)
    with open(path, "ab") as fh:
        fh.write(b" ")
    assert verify_freeze(path) is False
    sidecar = tmp_path / "core200.json.sha256"
    sidecar.unlink()
    assert verify_freeze(path) is False
    assert verify_freeze(tmp_path / "missing.json") is False
