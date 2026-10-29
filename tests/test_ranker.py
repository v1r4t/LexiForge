"""Tests for the adaptive context selector (docs/design.md §5).

Run with:  python -m pytest tests/test_ranker.py -q
"""

import unittest

from lexiforge.select.ranker import is_hard_negative_pair, score_breakdown, select


def _glossary():
    return [
        {"id": "NACH", "aliases": ["NACH", "nach mandate", "n a c h"]},
        {"id": "E-MANDATE", "aliases": ["e-mandate", "e mandate"]},
        {"id": "UPI", "aliases": ["UPI", "u p i", "upi id"]},
        {"id": "KYC", "aliases": ["KYC", "k y c", "kay see"]},
        {"id": "IFSC", "aliases": ["IFSC", "ifsc code"]},
        {"id": "MICR", "aliases": ["MICR", "micr code"]},
        {"id": "NEFT", "aliases": ["NEFT", "neft transfer"]},
        {"id": "IMPS", "aliases": ["IMPS", "imps transfer"]},
        {
            "id": "PhonePe",
            "aliases": ["PhonePe", "phonepe"],
            "hard_negatives": ["PhonPe"],
        },
        {
            "id": "PhonPe",
            "aliases": ["PhonPe", "phonpe"],
            "hard_negatives": ["PhonePe"],
        },
        {
            "id": "Paytm",
            "aliases": ["Paytm", "paytm"],
            "hard_negatives": ["Patym"],
        },
        {
            "id": "Patym",
            "aliases": ["Patym", "patym"],
            "hard_negatives": ["Paytm"],
        },
    ]


class TestNachRetrieval(unittest.TestCase):
    def test_nack_mandate_retrieves_nach(self):
        res = select("nack mandate set up karo", _glossary(), "collections")
        self.assertIn("NACH", res)

    def test_nach_ranks_first(self):
        res = select("nack mandate set up karo", _glossary(), "collections")
        self.assertEqual(res[0], "NACH")


class TestHardNegative(unittest.TestCase):
    def test_pair_not_both_preferentially_boosted(self):
        res = select("phonepe se paise bhejo", _glossary(), "upi")
        self.assertIn("PhonePe", res)
        self.assertNotIn("PhonPe", res)

    def test_veto_zeroes_phonetic_component(self):
        comp = score_breakdown("phonepe se paise bhejo", _glossary(), "upi")
        self.assertEqual(comp["PhonPe"]["phon"], 0.0)
        self.assertGreater(comp["PhonePe"]["phon"], 0.0)
        self.assertTrue(is_hard_negative_pair("PhonePe", "PhonPe"))

    def test_confusable_selected_without_declaration(self):
        plain = [
            {k: v for k, v in e.items() if k != "hard_negatives"} for e in _glossary()
        ]
        res = select("phonepe se paise bhejo", plain, "upi")
        # Without the declared pair the phonetic neighbour also scores —
        # the veto, not the lexicon, is what excludes it above.
        self.assertIn("PhonPe", res)


class TestDeterminism(unittest.TestCase):
    def test_repeated_calls_agree(self):
        g = _glossary()
        self.assertEqual(
            select("nack mandate set up karo", g, "collections"),
            select("nack mandate set up karo", g, "collections"),
        )

    def test_glossary_order_independent(self):
        g = _glossary()
        rev = list(reversed(g))
        self.assertEqual(
            select("phonepe se paise bhejo", g, "upi"),
            select("phonepe se paise bhejo", rev, "upi"),
        )


class TestEmptyHypothesis(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(select("", _glossary(), "collections"), [])

    def test_whitespace_returns_empty(self):
        self.assertEqual(select("   \t\n ", _glossary(), "collections"), [])


class TestNaturalSet(unittest.TestCase):
    def test_no_padding_and_within_budget(self):
        g = _glossary()
        res = select("nack mandate set up karo", g, "collections", budget=200)
        self.assertLessEqual(len(res), 200)
        self.assertTrue(set(res) <= {e["id"] for e in g})

    def test_budget_caps_selection(self):
        g = _glossary()
        res = select("nack mandate set up karo", g, "collections", budget=2)
        self.assertLessEqual(len(res), 2)
        self.assertEqual(res[0], "NACH")


class TestLeakageGuard(unittest.TestCase):
    def test_reference_in_glossary_raises(self):
        g = _glossary() + [{"id": "X", "reference": "leaked"}]
        with self.assertRaises(TypeError):
            select("nack mandate", g, "collections")

    def test_reference_in_hypothesis_dict_raises(self):
        with self.assertRaises(TypeError):
            select({"text": "nack mandate", "reference": "leaked"}, _glossary(), "collections")

    def test_reference_in_priors_raises(self):
        with self.assertRaises(TypeError):
            select(
                "nack mandate",
                _glossary(),
                "collections",
                priors={"NACH": {"reference": 5}},
            )


if __name__ == "__main__":
    unittest.main()
