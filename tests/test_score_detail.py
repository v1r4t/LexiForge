"""Tests for the detailed (row-level) scorer used by the pilot report."""

from lexiforge.score.match import score_file, score_file_detail

GLOSSARY = [
    {"term_id": "UPI", "aliases": ["UPI"], "origin": "real"},
    {"term_id": "F1", "aliases": ["Zorbix"], "origin": "fictional"},
]


def test_score_file_detail_returns_hit_and_insertion_rows():
    detail = score_file_detail("mera UPI fail hua", "mera UPI fail hua Zorbix", GLOSSARY)

    assert detail["hits"] == 1
    assert detail["insertions"] == 1
    assert detail["n_reference_occurrences"] == 1

    rows = detail["rows"]
    upi = next(row for row in rows if row["term_id"] == "UPI")
    assert upi == {
        "term_id": "UPI",
        "origin": "real",
        "hit": True,
        "insertion": False,
        "in_denom": True,
    }
    fictional = next(row for row in rows if row["term_id"] == "F1")
    assert fictional["origin"] == "fictional"
    assert fictional["hit"] is False
    assert fictional["insertion"] is True
    assert fictional["in_denom"] is False


def test_score_file_detail_counts_match_score_file():
    ref = "mera UPI fail hua"
    hyp = "mera UPI fail hua Zorbix"
    counts = score_file(ref, hyp, GLOSSARY)
    detail = score_file_detail(ref, hyp, GLOSSARY)
    for key in (
        "hits",
        "insertions",
        "misses",
        "n_reference_occurrences",
        "n_hypothesis_spans",
    ):
        assert detail[key] == counts[key]
