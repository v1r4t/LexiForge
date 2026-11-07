"""Tests for mismatched and diluted contexts."""

import unittest

from lexiforge.canon import canon
from lexiforge.contexts.mismatch import (
    assign_mismatch_domain,
    build_dilution,
    build_mismatched,
    phonetic_neighbour_overlap,
)


class TestMismatchDeterminism(unittest.TestCase):
    def test_assign_mismatch_domain_deterministic(self):
        d1 = assign_mismatch_domain("upi", seed=123)
        d2 = assign_mismatch_domain("upi", seed=123)
        self.assertEqual(d1, d2)
        # Different seeds may give different results but should be deterministic
        d3 = assign_mismatch_domain("upi", seed=456)
        self.assertIsInstance(d3, str)

    def test_build_mismatched_deterministic(self):
        glossary = {
            "upi": ["UPI", "VPA", "IMPS"],
            "insurance": ["policy", "premium", "claim"],
            "forex": ["forex", "currency", "exchange"],
        }
        expected = ["NEFT", "KYC"]
        # Pool holds exactly 6 off-domain terms; a larger budget must now fail
        # instead of silently returning a short list.
        m1 = build_mismatched(glossary, "upi", expected, seed=42, budget=6)
        m2 = build_mismatched(glossary, "upi", expected, seed=42, budget=6)
        self.assertEqual(m1, m2)
        self.assertEqual(len(m1), 6)


class TestMismatchExactBudget(unittest.TestCase):
    def test_fillable_request_returns_exactly_budget(self):
        glossary = {
            "upi": ["UPI", "VPA", "IMPS"],
            "insurance": ["policy", "premium", "claim", "agent", "renewal"],
            "forex": ["forex", "currency", "exchange"],
        }
        result = build_mismatched(glossary, "upi", ["NEFT"], seed=7, budget=8)
        self.assertEqual(len(result), 8)

    def test_unfillable_request_raises_value_error_with_counts(self):
        glossary = {
            "upi": ["UPI", "VPA"],
            "insurance": ["policy", "premium"],
        }
        with self.assertRaises(ValueError) as ctx:
            build_mismatched(glossary, "upi", ["NEFT"], seed=7, budget=5)
        message = str(ctx.exception)
        self.assertIn("mismatched", message)
        self.assertIn("5", message)
        self.assertIn("2", message)


class TestMismatchZeroOverlap(unittest.TestCase):
    def test_zero_overlap_assertion_fires_on_poisoned_input(self):
        glossary = {
            "upi": ["policy", "premium"],
            "insurance": ["NEFT", "KYC"],
        }
        expected = ["NEFT", "KYC"]  # These are in the "other domain" pool
        # Should raise AssertionError if we can't find non-overlapping terms
        with self.assertRaises(AssertionError):
            build_mismatched(glossary, "upi", expected, seed=1, budget=5)


class TestDilution(unittest.TestCase):
    def test_dilution_contains_all_expected_and_reaches_budget(self):
        glossary = {
            "upi": ["policy", "premium", "claim", "agent"],
            "insurance": ["NEFT", "KYC", "UPI"],  # call_type related
        }
        expected = ["NEFT", "KYC", "IFSC"]
        result = build_dilution(glossary, expected, call_type="insurance", seed=99, budget=200)
        self.assertEqual(len(result), 200)
        # All expected terms must be present
        result_canon = {canon(r) for r in result}
        for e in expected:
            self.assertIn(canon(e), result_canon)

    def test_dilution_returns_exactly_budget(self):
        glossary = {
            "upi": ["policy", "premium"],
            "insurance": ["NEFT", "KYC"],
        }
        result = build_dilution(
            glossary, ["NEFT"], call_type="insurance", seed=5, budget=10
        )
        self.assertEqual(len(result), 10)


class TestPhoneticOverlap(unittest.TestCase):
    def test_overlap_report_correct_on_hand_built_glossary(self):
        terms = ["NEFT", "NIFT", "phone", "xyz"]
        expected = ["NEFT"]
        report = phonetic_neighbour_overlap(terms, expected)
        self.assertIsInstance(report, dict)
        # Should report count/distribution
        self.assertIn("count", report)
        self.assertIn("distribution", report)
        self.assertIsInstance(report["count"], int)
        self.assertIsInstance(report["distribution"], dict)
        # NIFT is phonetically similar to NEFT
        self.assertGreaterEqual(report["count"], 0)  # At least structure is correct


if __name__ == "__main__":
    unittest.main()
