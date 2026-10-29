"""Tests for glossary assignment."""

import unittest

from lexiforge.glossary.assign import assign_terms


class TestAssignTerms(unittest.TestCase):
    def setUp(self):
        # Create a simple glossary with real and fictional terms
        real_terms = []
        for i in range(100):
            real_terms.append({"id": f"real{i:03d}", "term": f"REAL{i:03d}"})
        fict_terms = []
        for i in range(100):
            fict_terms.append({"id": f"fict{i:03d}", "term": f"FICT{i:03d}", "type": "fictional"})
        self.glossary = {
            "real": real_terms,
            "fictional": fict_terms,
        }
        self.call_types = [{"id": f"c{i:02d}", "call_type": "upi"} for i in range(20)]

    def test_counts_within_ranges(self):
        result = assign_terms(self.glossary, self.call_types, seed=12345)
        self.assertEqual(len(result), 20)
        for call_id, assignment in result.items():
            self.assertIn("real", assignment)
            self.assertIn("fictional", assignment)
            self.assertIn("hard_negative_pair", assignment)
            self.assertIn("oov", assignment)
            self.assertIn("call_type", assignment)
            self.assertGreaterEqual(len(assignment["real"]), 4)
            self.assertLessEqual(len(assignment["real"]), 5)
            self.assertGreaterEqual(len(assignment["fictional"]), 3)
            self.assertLessEqual(len(assignment["fictional"]), 4)

    def test_determinism(self):
        result1 = assign_terms(self.glossary, self.call_types, seed=42)
        result2 = assign_terms(self.glossary, self.call_types, seed=42)
        self.assertEqual(result1, result2)

    def test_no_duplicate_within_a_call(self):
        result = assign_terms(self.glossary, self.call_types, seed=999)
        for call_id, assignment in result.items():
            self.assertEqual(len(assignment["real"]), len(set(assignment["real"])))
            self.assertEqual(len(assignment["fictional"]), len(set(assignment["fictional"])))

    def test_oov_in_exactly_six_calls(self):
        result = assign_terms(self.glossary, self.call_types, seed=777)
        oov_count = sum(1 for a in result.values() if a["oov"])
        self.assertEqual(oov_count, 6)
        for assignment in result.values():
            if assignment["oov"]:
                self.assertIsInstance(assignment["oov"], list)
                self.assertEqual(len(assignment["oov"]), 1)
                self.assertIsInstance(assignment["oov"][0], str)

    def test_hard_negative_pair_in_ten_calls(self):
        result = assign_terms(self.glossary, self.call_types, seed=555)
        hn_count = sum(1 for a in result.values() if a["hard_negative_pair"] is not None)
        self.assertEqual(hn_count, 10)
        for assignment in result.values():
            if assignment["hard_negative_pair"] is not None:
                pair = assignment["hard_negative_pair"]
                self.assertIsInstance(pair, (list, tuple))
                self.assertEqual(len(pair), 2)

    def test_core200_kwarg_raises_typeerror(self):
        with self.assertRaises(TypeError):
            assign_terms(self.glossary, self.call_types, seed=123, core200=[1, 2, 3])


if __name__ == "__main__":
    unittest.main()
