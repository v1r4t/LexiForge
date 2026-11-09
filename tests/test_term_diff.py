"""Tests for per-term diff and per-call deltas (P02).

docs/design.md section 5 defines the matcher and insertion rule; section 6
requires per-call units before any summary. These tests pin surfaces, statuses,
and denominator membership so the report appendix cannot drift from the frozen
scorer.
"""

from __future__ import annotations

import pytest

from lexiforge.score.terms import per_call_deltas, term_diff

GLOSSARY = [
    {"term_id": "UPI", "aliases": ["UPI"], "origin": "real"},
    {"term_id": "NEFT", "aliases": ["NEFT"], "origin": "real"},
    {"term_id": "KYC", "aliases": ["KYC"], "origin": "real"},
    {"term_id": "ZORBIX", "aliases": ["Zorbix"], "origin": "fictional"},
]


def _row(rows, term_id: str) -> dict:
    matches = [row for row in rows if row["term_id"] == term_id]
    assert len(matches) == 1, f"expected one {term_id} row, got {matches!r}"
    return matches[0]


def test_acronym_spacing_is_a_variant_hit() -> None:
    diff = term_diff("mera U P I fail hua", "mera UPI fail hua", GLOSSARY)

    row = _row(diff["rows"], "UPI")
    assert row["status"] == "variant"
    assert row["expected_surface"] == "U P I"
    assert row["heard_surface"] == "UPI"
    assert row["variant_of"] == "U P I"
    assert row["in_denom"] is True
    assert row["in_selected"] is False
    assert row["in_expected"] is False
    assert diff["counts"]["variant"] == 1
    assert diff["counts"]["n_hits"] == 1
    assert diff["counts"]["recall"] == 1.0


def test_exact_surface_is_a_plain_hit() -> None:
    diff = term_diff("mera UPI fail hua", "mera UPI fail hua", GLOSSARY)

    row = _row(diff["rows"], "UPI")
    assert row["status"] == "hit"
    assert row["variant_of"] is None
    assert row["heard_surface"] == "UPI"
    assert diff["counts"]["hit"] == 1


def test_latin_and_devanagari_are_distinct_namespaces() -> None:
    diff = term_diff("NEFT kiya", "नेफ्ट किया", GLOSSARY)

    row = _row(diff["rows"], "NEFT")
    assert row["status"] == "miss"
    assert row["heard_surface"] is None
    assert diff["counts"]["miss"] == 1
    assert diff["counts"]["recall"] == 0.0


def test_case_truncation_is_a_miss_not_a_variant() -> None:
    diff = term_diff("NEFT kiya", "NEf kiya", GLOSSARY)

    row = _row(diff["rows"], "NEFT")
    assert row["status"] == "miss"
    assert row["variant_of"] is None
    assert diff["counts"]["recall"] == 0.0


def test_insertion_is_excluded_from_the_denominator() -> None:
    diff = term_diff("mera UPI fail hua", "mera UPI fail hua Zorbix", GLOSSARY)

    row = _row(diff["rows"], "ZORBIX")
    assert row["status"] == "insertion"
    assert row["expected_surface"] is None
    assert row["heard_surface"] == "Zorbix"
    assert row["in_denom"] is False
    assert diff["counts"]["insertion"] == 1
    assert diff["counts"]["n_insertions"] == 1
    assert diff["counts"]["n_denominator"] == 1
    assert diff["counts"]["recall"] == 1.0


def test_empty_hypothesis_marks_every_reference_term_missed() -> None:
    diff = term_diff("mera NEFT aur UPI", "", GLOSSARY)

    assert diff["counts"]["miss"] == 2
    assert diff["counts"]["insertion"] == 0
    assert diff["counts"]["n_denominator"] == 2
    assert diff["counts"]["recall"] == 0.0
    assert all(row["heard_surface"] is None for row in diff["rows"])


def test_repeated_occurrences_produce_one_row_each() -> None:
    diff = term_diff("UPI UPI UPI", "UPI UPI", GLOSSARY)

    upi_rows = [row for row in diff["rows"] if row["term_id"] == "UPI"]
    assert [row["status"] for row in upi_rows] == ["hit", "hit", "miss"]
    assert diff["counts"]["n_denominator"] == 3


def test_selected_and_expected_flags_and_absent_rows() -> None:
    diff = term_diff(
        "mera UPI",
        "mera UPI",
        GLOSSARY,
        selected=["UPI", "Zorbix"],
        expected=["UPI", "KYC"],
    )

    upi = _row(diff["rows"], "UPI")
    assert upi["in_selected"] is True
    assert upi["in_expected"] is True

    absent = _row(diff["rows"], "KYC")
    assert absent["status"] == "absent"
    assert absent["expected_surface"] == "KYC"
    assert absent["heard_surface"] is None
    assert absent["in_denom"] is False
    assert absent["in_expected"] is True
    assert absent["in_selected"] is False
    assert diff["counts"]["absent"] == 1
    assert diff["counts"]["n_denominator"] == 1


def _term_rows(call_id: str, statuses: list[str]) -> list[dict]:
    return [
        {"call_id": call_id, "status": status, "in_denom": status not in {"insertion", "absent"}}
        for status in statuses
    ]


def test_per_call_deltas_are_signed_arm_minus_baseline() -> None:
    rows = {
        "baseline": _term_rows("c1", ["hit"]) + _term_rows("c2", ["miss"]),
        "arm": _term_rows("c1", ["miss"]) + _term_rows("c2", ["hit"]),
    }

    result = per_call_deltas(rows, baseline="baseline", cluster_key="call_id")

    deltas = result["arms"]["arm"]["per_call"]
    assert deltas["c1"]["delta"] == -1.0
    assert deltas["c2"]["delta"] == 1.0
    assert result["arms"]["arm"]["mean"] == pytest.approx(0.0)


def test_per_call_deltas_reduce_per_call_before_summarising() -> None:
    rows = {
        "baseline": _term_rows("c1", ["miss"]) + _term_rows("c2", ["miss"] * 9),
        "arm": _term_rows("c1", ["hit"]) + _term_rows("c2", ["miss"] * 9),
    }

    result = per_call_deltas(rows, baseline="baseline", cluster_key="call_id")
    arm = result["arms"]["arm"]

    # c1 +1.0, c2 0.0 -> mean 0.5, never the pooled 1/10.
    assert arm["per_call"]["c1"]["delta"] == pytest.approx(1.0)
    assert arm["per_call"]["c2"]["delta"] == pytest.approx(0.0)
    assert arm["mean"] == pytest.approx(0.5)
    assert arm["n"] == 2


def test_per_call_deltas_drop_calls_with_no_denominator() -> None:
    rows = {
        "baseline": _term_rows("c1", ["insertion"]),
        "arm": _term_rows("c1", ["hit"]),
    }

    result = per_call_deltas(rows, baseline="baseline", cluster_key="call_id")

    assert result["arms"]["arm"]["per_call"] == {}
    assert result["arms"]["arm"]["n"] == 0
    assert result["arms"]["arm"]["mean"] is None


def test_per_call_deltas_requires_a_known_baseline() -> None:
    with pytest.raises(ValueError):
        per_call_deltas({"arm": []}, baseline="baseline", cluster_key="call_id")
