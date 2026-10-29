"""Tests for the frozen canonicaliser.

Run with:  python -m unittest discover -s tests -v
"""

import unittest

from lexiforge.canon import CANON_VERSION, canon, tokens


class TestStep1NFC(unittest.TestCase):
    def test_precomposed_equals_decomposed(self):
        self.assertEqual(canon("cafe\u0301"), canon("caf\u00e9"))

    def test_devanagari_composition(self):
        # क + nukta vs precomposed क़ must agree.
        self.assertEqual(canon("\u0915\u093c"), canon("\u0958"))


class TestStep2Nukta(unittest.TestCase):
    def test_nukta_is_preserved(self):
        # क and क़ are different phonemes; folding them would merge real terms.
        self.assertNotEqual(canon("\u0915"), canon("\u0958"))


class TestStep3Anusvara(unittest.TestCase):
    def test_chandrabindu_folds_to_anusvara(self):
        self.assertEqual(canon("\u0939\u0942\u0901"), canon("\u0939\u0942\u0902"))


class TestStep4NoTransliteration(unittest.TestCase):
    def test_scripts_stay_separate(self):
        self.assertNotEqual(canon("\u0916\u093e\u0924\u093e"), canon("khata"))

    def test_devanagari_survives_roundtrip(self):
        self.assertEqual(canon("\u0916\u093e\u0924\u093e"), "\u0916\u093e\u0924\u093e")


class TestStep5Casefold(unittest.TestCase):
    def test_acronym_case(self):
        self.assertEqual(canon("NACH"), canon("nach"))
        self.assertEqual(canon("Nach"), canon("NACH"))


class TestStep6Punctuation(unittest.TestCase):
    def test_hyphen_is_a_separator(self):
        self.assertEqual(canon("e-mandate"), canon("e mandate"))

    def test_apostrophe_is_deleted(self):
        self.assertEqual(canon("don't"), canon("dont"))

    def test_apostrophe_does_not_create_a_token(self):
        self.assertNotEqual(canon("don't"), "don t")

    def test_danda_and_fullstop_are_separators(self):
        self.assertEqual(canon("mandate\u0964"), "mandate")
        self.assertEqual(canon("mandate."), "mandate")


class TestStep7Acronyms(unittest.TestCase):
    def test_letter_spelled_acronym_joins(self):
        self.assertEqual(canon("N A C H"), canon("NACH"))

    def test_dotted_acronym_joins(self):
        self.assertEqual(canon("N.A.C.H."), canon("NACH"))

    def test_two_letter_run_is_not_joined(self):
        # Guards against inventing tokens from initials.
        self.assertEqual(canon("e mandate"), "e mandate")

    def test_run_beyond_six_is_left_alone(self):
        self.assertNotEqual(canon("a b c d e f g"), "abcdefg")


class TestStep8Digits(unittest.TestCase):
    def test_devanagari_digits_normalise(self):
        self.assertEqual(canon("\u0968\u0966"), "20")

    def test_words_do_not_fold_to_digits(self):
        self.assertNotEqual(canon("twenty"), canon("20"))

    def test_digit_shapes_are_stable(self):
        self.assertEqual(canon("20"), "20")


class TestHardNegativeSeparation(unittest.TestCase):
    """The matcher must never merge a pre-registered confusable pair."""

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

    def test_pairs_are_distinct_under_canon(self):
        for a, b in self.PAIRS:
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(
                    canon(a),
                    canon(b),
                    msg=f"{a!r} and {b!r} canonicalise to the same key",
                )

    def test_pairs_are_distinct_as_token_sequences(self):
        for a, b in self.PAIRS:
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(tokens(a), tokens(b))


class TestInvariants(unittest.TestCase):
    def test_idempotent(self):
        samples = [
            "N.A.C.H. mandate fail ho gaya",
            "Mera e-mandate \u0916\u093e\u0924\u093e",
            "U P I ID check karo",
            "\u0968\u0966\u0966\u0966 rupaye",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                once = canon(sample)
                self.assertEqual(canon(once), once)

    def test_empty_and_whitespace(self):
        self.assertEqual(canon(""), "")
        self.assertEqual(canon("   \t\n "), "")

    def test_none_raises(self):
        with self.assertRaises(TypeError):
            canon(None)

    def test_version_is_pinned(self):
        self.assertRegex(CANON_VERSION, r"^matcher-v\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
