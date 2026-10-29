"""Tests for the frozen exact term matcher.

Run with:  python -m pytest tests/test_match.py -q
"""

import unittest

from lexiforge.score.match import (
    AliasCollision,
    HardNegativeCollision,
    assert_hard_negatives_separable,
    build_alias_map,
    find_spans,
    score_file,
)


def neft_glossary():
    return [{"id": "NEFT", "aliases": ["NEFT", "N.E.F.T."]}]


class TestMissedTerm(unittest.TestCase):
    def test_missed_term_counts_one_miss(self):
        result = score_file(
            "send money through NEFT today",
            "send money through net today",
            neft_glossary(),
        )
        self.assertEqual(result["misses"], 1)
        self.assertEqual(result["hits"], 0)
        self.assertEqual(result["insertions"], 0)
        self.assertEqual(result["n_reference_occurrences"], 1)
        self.assertEqual(result["n_hypothesis_spans"], 0)


class TestInsertion(unittest.TestCase):
    def test_insertion_where_reference_says_something_else(self):
        result = score_file(
            "pay the electricity bill today",
            "pay the NEFT today",
            neft_glossary(),
        )
        self.assertEqual(result["insertions"], 1)
        self.assertEqual(result["hits"], 0)
        self.assertEqual(result["misses"], 0)
        self.assertEqual(result["n_hypothesis_spans"], 1)
        self.assertEqual(result["n_reference_occurrences"], 0)


class TestSimilarSoundingWord(unittest.TestCase):
    def test_ordinary_word_sharing_sound_is_neither_hit_nor_insertion(self):
        glossary = [{"id": "Paytm", "aliases": ["Paytm"]}]
        text = "i met patym at the store"
        self.assertEqual(find_spans(text, glossary), [])
        result = score_file(text, text, glossary)
        self.assertEqual(result["hits"], 0)
        self.assertEqual(result["insertions"], 0)
        self.assertEqual(result["misses"], 0)


class TestAliasCollision(unittest.TestCase):
    def test_collision_raises(self):
        glossary = [
            {"id": "NEFT", "aliases": ["NEFT"]},
            {"id": "NEFT_DUP", "aliases": ["neft"]},
        ]
        with self.assertRaises(AliasCollision):
            build_alias_map(glossary)
        with self.assertRaises(AliasCollision):
            find_spans("pay via NEFT", glossary)


class TestHardNegatives(unittest.TestCase):
    def test_clean_assertion_passes(self):
        glossary = [
            {"id": "NACH", "aliases": ["NACH"]},
            {"id": "E_MANDATE", "aliases": ["e-mandate"]},
            {"id": "IFSC", "aliases": ["IFSC"]},
            {"id": "MICR", "aliases": ["MICR"]},
        ]
        assert_hard_negatives_separable(
            glossary, [("NACH", "e-mandate"), ("IFSC", "MICR")]
        )

    def test_poisoned_assertion_fails_naming_key(self):
        with self.assertRaises(HardNegativeCollision) as ctx:
            assert_hard_negatives_separable(
                neft_glossary(), [("NEFT", "N E F T")]
            )
        self.assertIn("neft", str(ctx.exception))


class TestLongestSpanFirst(unittest.TestCase):
    def test_longer_alias_wins(self):
        glossary = [
            {"id": "UPI", "aliases": ["UPI"]},
            {"id": "UPI_ID", "aliases": ["UPI ID"]},
        ]
        text = "link my UPI ID please"
        spans = find_spans(text, glossary)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["term_id"], "UPI_ID")
        self.assertEqual(spans[0]["surface"], "UPI ID")
        self.assertEqual(spans[0]["canon_key"], "upi id")
        self.assertEqual(text[spans[0]["start"] : spans[0]["end"]], "UPI ID")


class TestHit(unittest.TestCase):
    def test_shared_term_is_a_hit_not_insertion(self):
        result = score_file(
            "my NEFT transfer failed",
            "my NEFT transfer failed",
            neft_glossary(),
        )
        self.assertEqual(result["hits"], 1)
        self.assertEqual(result["insertions"], 0)
        self.assertEqual(result["misses"], 0)


if __name__ == "__main__":
    unittest.main()
