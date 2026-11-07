"""Tests for the five experiment arms (design §2).

Arms differ only in the keyterm list attached to the same audio, model and
format. Every arm except ``baseline`` must carry exactly ``budget`` canonical
surfaces, and the same inputs must produce the same lists in a fresh
interpreter regardless of ``PYTHONHASHSEED``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lexiforge.canon import CANON_VERSION, canon
from lexiforge.contexts.arms import ARMS, build_arm_configs, build_arms
from lexiforge.optimizer.vocab import to_selector_glossary
from lexiforge.select.ranker import select

ROOT = Path(__file__).resolve().parents[1]

CATEGORY_TERMS = {
    "payments": [
        "UPI",
        "IMPS",
        "NEFT",
        "RTGS",
        "VPA",
        "BHIM",
        "AutoPay",
        "e-mandate",
        "UPI Lite",
        "payment link",
    ],
    "cards": [
        "credit card",
        "debit card",
        "CVV",
        "card PIN",
        "expiry date",
        "issuer bank",
        "card network",
        "chargeback",
        "card statement",
        "contactless",
    ],
    "loans": [
        "EMI",
        "loan tenure",
        "principal",
        "interest rate",
        "foreclosure",
        "moratorium",
        "disbursal",
        "sanction letter",
        "co-applicant",
        "prepayment",
    ],
    "insurance": [
        "policy",
        "premium",
        "claim",
        "rider",
        "deductible",
        "nominee",
        "cover",
        "renewal",
        "endowment",
        "annuity",
    ],
    "kyc": [
        "Aadhaar",
        "PAN",
        "address proof",
        "re-verification",
        "OVD",
        "selfie",
        "liveness",
        "consent",
        "CKYC",
        "video KYC",
    ],
    "forex": [
        "remittance",
        "nostro",
        "SWIFT",
        "hedge",
        "spot rate",
        "forward contract",
        "conversion",
        "corridor",
        "settlement",
        "margin",
    ],
}

HYPOTHESIS = "Mera UPI payment fail hua, NEFT aur IMPS bhi nahi chala."
EXPECTED_IDS = ["PAY-00", "PAY-01", "PAY-02"]  # UPI, IMPS, NEFT
BUDGET = 40


def _glossary() -> list[dict]:
    out: list[dict] = []
    for category, terms in CATEGORY_TERMS.items():
        for idx, surface in enumerate(terms):
            out.append(
                {
                    "term_id": f"{category[:3].upper()}-{idx:02d}",
                    "canonical": surface,
                    "category": category,
                    "scoring_aliases": [],
                    "origin": "fictional",
                }
            )
    return out


def _by_id(glossary: list[dict]) -> dict[str, dict]:
    return {entry["term_id"]: entry for entry in glossary}


def _builder(returned=()):
    """Recording fake for T6's ``build_hard_negative`` (kept out of imports)."""
    calls: list[dict] = []

    def builder(glossary, expected_terms, *, budget, seed=0):
        calls.append(
            {
                "glossary": glossary,
                "expected_terms": list(expected_terms),
                "budget": budget,
                "seed": seed,
            }
        )
        return list(returned)

    return builder, calls


def _arms(
    *,
    glossary=None,
    hypothesis=HYPOTHESIS,
    call_type="payments",
    budget=BUDGET,
    seed=0,
    expected_terms=EXPECTED_IDS,
    static_terms=None,
    by_category=None,
    hard_negative_builder=None,
):
    if hard_negative_builder is None:
        hard_negative_builder = _builder()[0]
    return build_arms(
        hypothesis,
        _glossary() if glossary is None else glossary,
        call_type,
        budget=budget,
        seed=seed,
        expected_terms=expected_terms,
        static_terms=static_terms,
        by_category=by_category,
        hard_negative_builder=hard_negative_builder,
    )


def test_arms_tuple_is_frozen():
    assert ARMS == (
        "baseline",
        "selected-200",
        "mismatched-200",
        "hard-negative-200",
        "static-200",
    )


def test_baseline_is_empty_and_every_other_arm_exact_budget():
    arms = _arms()
    assert list(arms) == list(ARMS)
    assert arms["baseline"] == []
    for arm in ARMS[1:]:
        assert len(arms[arm]) == BUDGET, arm
        assert len({canon(term) for term in arms[arm]}) == BUDGET, arm


def test_arms_return_canonical_surfaces_not_ids():
    glossary = _glossary()
    ids = {entry["term_id"] for entry in glossary}
    surfaces = {entry["canonical"] for entry in glossary}
    arms = _arms(glossary=glossary)
    for arm in ARMS[1:]:
        for term in arms[arm]:
            assert isinstance(term, str)
            assert term not in ids, (arm, term)
            assert term in surfaces, (arm, term)


def test_selected_pads_natural_underfill_deterministically():
    glossary = _glossary()
    natural_ids = select(
        HYPOTHESIS, to_selector_glossary(glossary), "payments", budget=BUDGET
    )
    natural = [_by_id(glossary)[tid]["canonical"] for tid in natural_ids]
    assert 0 < len(natural) < BUDGET

    arms = _arms(glossary=glossary)
    assert arms["selected-200"][: len(natural)] == natural
    assert len(arms["selected-200"]) == BUDGET
    # The pad comes from the full glossary, not from the expected set.
    assert set(arms["selected-200"]) <= {
        entry["canonical"] for entry in glossary
    }


def test_mismatched_has_zero_expected_overlap():
    glossary = _glossary()
    expected = {canon(_by_id(glossary)[tid]["canonical"]) for tid in EXPECTED_IDS}
    arms = _arms(glossary=glossary)
    drawn = {canon(term) for term in arms["mismatched-200"]}
    assert drawn & expected == set()


def test_mismatched_draws_from_other_categories():
    glossary = _glossary()
    payments = {canon(term) for term in CATEGORY_TERMS["payments"]}
    drew = {canon(term) for term in _arms(glossary=glossary)["mismatched-200"]}
    assert drew & payments == set()
    assert len(drew) == BUDGET


def test_explicit_category_adapter_is_used():
    glossary = _glossary()
    other = list(CATEGORY_TERMS["cards"]) + list(CATEGORY_TERMS["loans"])
    by_category = {"payments": list(CATEGORY_TERMS["payments"]), "cards": other}
    arms = _arms(glossary=glossary, by_category=by_category, budget=15)
    drew = {canon(term) for term in arms["mismatched-200"]}
    assert drew <= {canon(term) for term in other}
    assert len(drew) == 15


def test_hard_negative_zero_exact_overlap_and_expected_resolution():
    glossary = _glossary()
    builder, calls = _builder(
        ["UPI", "IMPS", "filler0", "filler1", "filler2", "filler3"]
    )
    arms = _arms(
        glossary=glossary,
        budget=6,
        expected_terms=["PAY-00", "PAY-01"],
        hard_negative_builder=builder,
    )
    drawn = {canon(term) for term in arms["hard-negative-200"]}
    assert drawn & {canon("UPI"), canon("IMPS")} == set()
    assert len(arms["hard-negative-200"]) == 6
    # Expected terms reach T6 as canonical surfaces, not glossary IDs.
    assert calls[0]["expected_terms"] == ["IMPS", "UPI"]
    assert calls[0]["budget"] == 6
    assert calls[0]["seed"] == 0


def test_hard_negative_default_import_is_lazy():
    code = (
        "import sys\n"
        "import lexiforge.contexts.arms as arms\n"
        "assert 'lexiforge.contexts.hard_negative' not in sys.modules\n"
        "assert callable(arms.build_arms)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr


def test_reference_key_in_glossary_raises_typeerror():
    glossary = _glossary()
    glossary[3] = dict(glossary[3], reference="leaked script line")
    with pytest.raises(TypeError, match="reference"):
        _arms(glossary=glossary, budget=5)


def test_reference_key_in_hypothesis_raises_typeerror():
    with pytest.raises(TypeError, match="reference"):
        _arms(
            hypothesis={"text": HYPOTHESIS, "reference": "leaked script line"},
            budget=5,
        )


def test_static_arm_is_fixed_across_hypotheses():
    glossary = _glossary()
    first = _arms(glossary=glossary, hypothesis=HYPOTHESIS)
    second = _arms(
        glossary=glossary,
        hypothesis="Mera insurance claim reject ho gaya.",
        call_type="insurance",
    )
    assert first["static-200"] == second["static-200"]
    assert len(first["static-200"]) == BUDGET


def test_static_terms_are_prefix_then_padded():
    glossary = _glossary()
    chosen = ["claim", "nominee"]
    arms = _arms(glossary=glossary, static_terms=chosen, budget=5)
    assert arms["static-200"][:2] == chosen
    assert len(arms["static-200"]) == 5
    assert len({canon(term) for term in arms["static-200"]}) == 5


def test_same_inputs_same_arms():
    glossary = _glossary()
    builder = _builder()[0]
    first = _arms(glossary=glossary, seed=9, hard_negative_builder=builder)
    second = _arms(glossary=glossary, seed=9, hard_negative_builder=builder)
    assert first == second


def test_identical_across_python_hash_seeds():
    child = """
import json
from lexiforge.canon import canon
from lexiforge.contexts.arms import build_arms

CATS = {
    "payments": ["UPI", "IMPS", "NEFT", "RTGS", "VPA", "BHIM", "AutoPay", "e-mandate"],
    "cards": ["credit card", "debit card", "CVV", "card PIN", "expiry date", "issuer",
              "chargeback", "contactless"],
    "loans": ["EMI", "tenure", "principal", "interest", "foreclosure", "moratorium",
              "disbursal", "sanction"],
    "insurance": ["policy", "premium", "claim", "rider", "deductible", "nominee",
                  "cover", "renewal"],
    "kyc": ["Aadhaar", "PAN", "address", "OVD", "selfie", "liveness", "consent", "CKYC"],
    "forex": ["remittance", "nostro", "SWIFT", "hedge", "spot", "forward",
              "conversion", "margin"],
}
GLOSSARY = [
    {"term_id": "%s-%02d" % (cat[:3].upper(), i), "canonical": surface,
     "category": cat, "scoring_aliases": []}
    for cat, terms in CATS.items()
    for i, surface in enumerate(terms)
]

def builder(glossary, expected_terms, *, budget, seed=0):
    excluded = {canon(t) for t in expected_terms}
    out = []
    for entry in glossary:
        surface = entry["canonical"]
        if canon(surface) in excluded:
            continue
        out.append(surface)
        if len(out) >= budget:
            break
    return out

arms = build_arms(
    "Mera UPI payment fail hua, NEFT aur IMPS bhi nahi chala.",
    GLOSSARY,
    "payments",
    budget=12,
    seed=5,
    expected_terms={"PAY-00", "PAY-01", "PAY-02"},
    static_terms={"CVV", "EMI", "policy", "PAN", "hedge", "selfie"},
    hard_negative_builder=builder,
)
print(json.dumps(arms, sort_keys=True))
"""
    payloads = []
    for hash_seed in ("0", "1"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = hash_seed
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(ROOT), env.get("PYTHONPATH", "")) if p
        )
        proc = subprocess.run(
            [sys.executable, "-c", child],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        payloads.append(json.loads(proc.stdout))

    assert len(payloads[0]["mismatched-200"]) == 12
    assert len(payloads[0]["hard-negative-200"]) == 12
    assert payloads[0] == payloads[1]


def test_build_arm_configs_exact_budget_and_baseline_without_keyterms():
    glossary = _glossary()
    builder = _builder()[0]
    arms = _arms(glossary=glossary, hard_negative_builder=builder)
    configs = build_arm_configs(
        HYPOTHESIS,
        glossary,
        "payments",
        budget=BUDGET,
        seed=0,
        expected_terms=EXPECTED_IDS,
        hard_negative_builder=builder,
    )
    assert list(configs) == list(ARMS)
    assert configs["baseline"] == {"canon_version": CANON_VERSION}
    for arm in ARMS[1:]:
        keyterms = configs[arm]["keyterms"]
        assert len(keyterms) == BUDGET, arm
        assert {canon(term) for term in keyterms} == {
            canon(term) for term in arms[arm]
        }, arm


def test_budget_above_max_rejected():
    with pytest.raises(ValueError):
        _arms(budget=201)


def test_glossary_too_small_for_budget_raises():
    with pytest.raises(ValueError):
        _arms(glossary=_glossary()[:4], budget=10, expected_terms=None)
