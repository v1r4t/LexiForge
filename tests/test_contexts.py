"""Tests for lexiforge.contexts (design §2, §4)."""

from __future__ import annotations

import itertools

import pytest

from lexiforge.contexts.build import (
    MAX_KEYTERMS,
    TOPIC_MAX,
    TOPIC_MIN,
    ContextBudgetError,
    assert_budget,
    build_config,
    canonicalise_terms,
    context_hash,
    derive_topic,
)

GOOD_TOPIC = "x" * 60


def test_budget_201_rejected():
    terms = [f"term{i}" for i in range(201)]
    with pytest.raises(ContextBudgetError):
        build_config(topic=GOOD_TOPIC, keyterms=terms)
    with pytest.raises(ContextBudgetError):
        assert_budget(terms)


def test_budget_error_carries_count():
    terms = [f"term{i}" for i in range(201)]
    with pytest.raises(ContextBudgetError) as exc:
        assert_budget(terms)
    assert "201" in str(exc.value)


def test_budget_boundary_200_ok():
    terms = [f"term{i}" for i in range(200)]
    cfg = build_config(keyterms=terms)
    assert len(cfg["keyterms"]) == 200


def test_duplicates_collapse_before_cap():
    # 201 raw entries but only 100 unique -> within budget.
    terms = [f"term{i % 100}" for i in range(201)]
    canon = canonicalise_terms(terms)
    assert len(canon) == 100
    cfg = build_config(keyterms=terms)
    assert len(cfg["keyterms"]) == 100


def test_order_stable_across_permutations():
    terms = ["NEFT", "upi", "KYC", "ifsc", "e-mandate"]
    expected = canonicalise_terms(terms)
    for perm in itertools.permutations(terms):
        assert canonicalise_terms(list(perm)) == expected


def test_sort_key_casefold_then_original():
    out = canonicalise_terms(["b", "A", "a"])
    assert out == sorted(["b", "A", "a"], key=lambda s: (s.casefold(), s))


def test_phrase_counts_as_one_slot():
    terms = ["account balance", "upi"]
    canon = canonicalise_terms(terms)
    assert len(canon) == 2
    assert "account balance" in canon
    assert assert_budget(canon) == 2


def test_forbidden_substrings_rejected():
    with pytest.raises(ValueError):
        canonicalise_terms(["ok term", "bad <| term"])
    with pytest.raises(ValueError):
        canonicalise_terms(["ok term", "bad |> term"])
    with pytest.raises(ValueError):
        build_config(keyterms=["fine", "nope <|x"])


def test_canonicalise_drops_empties_and_collapses_ws():
    out = canonicalise_terms(["  a   b  ", "   ", "", "a b"])
    assert out == ["a b"]


def test_topic_bounds():
    with pytest.raises(ValueError):
        build_config(topic="x" * (TOPIC_MIN - 1))
    with pytest.raises(ValueError):
        build_config(topic="x" * (TOPIC_MAX + 1))
    assert build_config(topic="x" * TOPIC_MIN)["topic"] == "x" * TOPIC_MIN
    assert build_config(topic="x" * TOPIC_MAX)["topic"] == "x" * TOPIC_MAX


def test_combo_rejection():
    # speaker_names mixes with anything else are illegal.
    with pytest.raises(ValueError):
        build_config(topic=GOOD_TOPIC, speaker_names=["Asha"])
    with pytest.raises(ValueError):
        build_config(keyterms=["upi"], speaker_names=["Asha"])
    with pytest.raises(ValueError):
        build_config(
            topic=GOOD_TOPIC, keyterms=["upi"], speaker_names=["Asha"]
        )


def test_allowed_combos():
    assert build_config() == {}
    assert set(build_config(keyterms=["upi"])) == {"keyterms"}
    assert set(build_config(topic=GOOD_TOPIC)) == {"topic"}
    assert set(build_config(topic=GOOD_TOPIC, keyterms=["upi"])) == {
        "topic",
        "keyterms",
    }
    assert set(build_config(speaker_names=["Asha"])) == {"speaker_names"}


def test_derive_topic_refuses_reference_key():
    with pytest.raises(TypeError):
        derive_topic(
            {
                "call_type": "collections",
                "channel": "phone",
                "language": "Hinglish",
                "reference": "NEFT payment due",
            }
        )


def test_derive_topic_refuses_transcript_key():
    with pytest.raises(TypeError):
        derive_topic(
            {
                "call_type": "collections",
                "channel": "phone",
                "language": "Hinglish",
                "transcript": "hello",
            }
        )


def test_derive_topic_uses_only_metadata():
    t1 = derive_topic(
        {"call_type": "collections", "channel": "phone", "language": "Hinglish"}
    )
    t2 = derive_topic(
        {"call_type": "collections", "channel": "phone", "language": "Hinglish"}
    )
    assert t1 == t2
    assert TOPIC_MIN <= len(t1) <= TOPIC_MAX
    # Usable directly as a Batch topic.
    assert build_config(topic=t1)["topic"] == t1


def test_context_hash_stable():
    cfg = build_config(topic=GOOD_TOPIC, keyterms=["b", "a"])
    h1 = context_hash(cfg)
    h2 = context_hash(dict(reversed(list(cfg.items()))))
    assert h1 == h2
    assert len(h1) == 64
