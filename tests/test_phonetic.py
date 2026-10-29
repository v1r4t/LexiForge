"""Tests for the HING-SKEL phonetic skeleton.

Run with:  python -m pytest tests/test_phonetic.py -v
"""

import unittest

from lexiforge.select.phonetic import (
    is_hard_negative_pair,
    skeleton,
    skeleton_similarity,
)

PAIRS = [
    ("NACH", "e-mandate"),
    ("UPI ID", "VPA"),
    ("IFSC", "MICR"),
    ("BBPS", "Bharat BillPay"),
    ("IMPS", "NEFT"),
    ("CIBIL", "credit score"),
    ("Paytm", "Patym"),
    ("PhonePe", "PhonPe"),
    ("Mobikwik", "Mobikwick"),
    ("Razorpay", "Razorpey"),
]


class TestSkeletonMerges(unittest.TestCase):
    def test_nack_and_nach_share_skeleton(self):
        self.assertEqual(skeleton("nack"), skeleton("NACH"))

    def test_ifsc_and_micr_do_not_share_skeleton(self):
        self.assertNotEqual(skeleton("IFSC"), skeleton("MICR"))

    def test_letter_spelled_acronym_joins(self):
        self.assertEqual(skeleton("i f s c"), skeleton("IFSC"))

    def test_hyphen_split_matches_space(self):
        self.assertEqual(skeleton("e-mandate"), skeleton("e mandate"))

    def test_phonepe_phonpe_collide_so_veto_has_work(self):
        self.assertEqual(skeleton("PhonePe"), skeleton("PhonPe"))


class TestHardNegativeVeto(unittest.TestCase):
    def test_phonepe_phonpe_flagged(self):
        self.assertTrue(is_hard_negative_pair("PhonePe", "PhonPe", PAIRS))

    def test_phonepe_phonpe_flagged_without_list(self):
        self.assertTrue(is_hard_negative_pair("PhonePe", "PhonPe", []))

    def test_identical_terms_are_not_a_negative_pair(self):
        self.assertFalse(is_hard_negative_pair("NACH", "nach", PAIRS))

    def test_unrelated_terms_not_flagged(self):
        self.assertFalse(is_hard_negative_pair("IFSC", "NACH", []))


class TestSimilarity(unittest.TestCase):
    def test_identical_is_one(self):
        self.assertEqual(skeleton_similarity("NACH", "nack"), 1.0)

    def test_distinct_below_one(self):
        sim = skeleton_similarity("IFSC", "MICR")
        self.assertGreaterEqual(sim, 0.0)
        self.assertLess(sim, 1.0)

    def test_empty_safe(self):
        self.assertEqual(skeleton(""), "")
        self.assertEqual(skeleton("   "), "")
        self.assertEqual(skeleton_similarity("", ""), 0.0)
        self.assertEqual(skeleton_similarity("", "NACH"), 0.0)
        self.assertEqual(skeleton_similarity("IFSC", ""), 0.0)


class TestDeterminism(unittest.TestCase):
    def test_repeated_calls_agree(self):
        samples = ["NACH", "nack", "PhonePe", "PhonPe", "IFSC", "e-mandate",
                   "i f s c", "", "Razorpay"]
        for s in samples:
            with self.subTest(sample=s):
                self.assertEqual(skeleton(s), skeleton(s))
                self.assertEqual(
                    skeleton_similarity(s, "NACH"),
                    skeleton_similarity(s, "NACH"),
                )

    def test_case_and_punct_insensitive(self):
        self.assertEqual(skeleton("N.A.C.H."), skeleton("nach"))


if __name__ == "__main__":
    unittest.main()
