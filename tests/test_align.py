"""Tests for lexiforge.score.align (design §5 insertion rule)."""

import unittest

from lexiforge.score import align, pair_terms


def span(start, end, term_id):
    return {"start": start, "end": end, "term_id": term_id}


class TestAlign(unittest.TestCase):
    def test_exact_match(self):
        tokens = ["pay", "neft", "now"]
        self.assertEqual(
            align(tokens, list(tokens)),
            [(0, 0, "match"), (1, 1, "match"), (2, 2, "match")],
        )

    def test_one_substitution(self):
        self.assertEqual(
            align(["pay", "neft", "now"], ["pay", "kyc", "now"]),
            [(0, 0, "match"), (1, 1, "sub"), (2, 2, "match")],
        )

    def test_insertion_opcodes(self):
        self.assertEqual(
            align(["pay", "bill"], ["pay", "upi", "bill"]),
            [(0, 0, "match"), (None, 1, "ins"), (1, 2, "match")],
        )

    def test_deletion_opcodes(self):
        self.assertEqual(
            align(["pay", "upi", "bill"], ["pay", "bill"]),
            [(0, 0, "match"), (1, None, "del"), (2, 1, "match")],
        )

    def test_empty_both(self):
        self.assertEqual(align([], []), [])

    def test_empty_hypothesis_is_all_deletions(self):
        self.assertEqual(
            align(["a", "b"], []), [(0, None, "del"), (1, None, "del")]
        )

    def test_empty_reference_is_all_insertions(self):
        self.assertEqual(
            align([], ["a", "b"]), [(None, 0, "ins"), (None, 1, "ins")]
        )

    def test_tie_break_prefers_sub_over_del_ins(self):
        # Three optimal cost-2 paths exist; sub/sub must win deterministically.
        expected = [(0, 0, "sub"), (1, 1, "sub")]
        self.assertEqual(align(["a", "b"], ["b", "a"]), expected)
        self.assertEqual(align(["a", "b"], ["b", "a"]), expected)

    def test_opcode_coverage(self):
        cases = [
            (["a", "b"], ["b", "a"]),
            ([], ["x"]),
            (["x"], []),
            (["a", "b", "c"], ["a", "X", "c", "d"]),
            (["my", "upi", "id"], ["my", "vpa", "id"]),
        ]
        for ref, hyp in cases:
            with self.subTest(ref=ref, hyp=hyp):
                result = align(ref, hyp)
                self.assertEqual(
                    sorted(r for (r, h, op) in result if r is not None),
                    list(range(len(ref))),
                )
                self.assertEqual(
                    sorted(h for (r, h, op) in result if h is not None),
                    list(range(len(hyp))),
                )
                for _, _, op in result:
                    self.assertIn(op, ("match", "sub", "del", "ins"))


class TestPairTerms(unittest.TestCase):
    def test_exact_match_is_hit(self):
        tokens = ["pay", "neft", "now"]
        spans = [span(1, 2, "NEFT")]
        paired = pair_terms(spans, spans, align(tokens, list(tokens)))
        self.assertEqual(paired["hits"], spans)
        self.assertEqual(paired["insertions"], [])
        self.assertEqual(paired["misses"], [])

    def test_substitution_is_miss_plus_insertion(self):
        paired = pair_terms(
            [span(1, 2, "NEFT")],
            [span(1, 2, "KYC")],
            align(["pay", "neft", "now"], ["pay", "kyc", "now"]),
        )
        self.assertEqual(paired["hits"], [])
        self.assertEqual(paired["insertions"], [span(1, 2, "KYC")])
        self.assertEqual(paired["misses"], [span(1, 2, "NEFT")])

    def test_insertion_aligned_to_different_reference_term(self):
        ref = ["my", "upi", "id", "failed"]
        hyp = ["my", "vpa", "id", "failed"]
        paired = pair_terms(
            [span(1, 3, "UPI ID")],
            [span(1, 3, "VPA")],
            align(ref, hyp),
        )
        self.assertEqual(paired["hits"], [])
        self.assertEqual(paired["insertions"], [span(1, 3, "VPA")])
        self.assertEqual(paired["misses"], [span(1, 3, "UPI ID")])

    def test_insertion_aligned_to_nothing(self):
        paired = pair_terms(
            [],
            [span(1, 2, "UPI")],
            align(["pay", "bill"], ["pay", "upi", "bill"]),
        )
        self.assertEqual(paired["hits"], [])
        self.assertEqual(paired["insertions"], [span(1, 2, "UPI")])
        self.assertEqual(paired["misses"], [])

    def test_sounds_like_ordinary_word_is_not_insertion(self):
        # Matcher false alarm: hyp "phone" is really the ordinary word "phone".
        tokens = ["my", "phone", "rang"]
        paired = pair_terms(
            [],
            [span(1, 2, "PhonePe")],
            align(tokens, list(tokens)),
        )
        self.assertEqual(paired["hits"], [])
        self.assertEqual(paired["insertions"], [])
        self.assertEqual(paired["misses"], [])

    def test_tuple_spans_supported(self):
        tokens = ["pay", "neft", "now"]
        paired = pair_terms(
            [(1, 2, "NEFT")], [(1, 2, "NEFT")], align(tokens, list(tokens))
        )
        self.assertEqual(paired["hits"], [span(1, 2, "NEFT")])
        self.assertEqual(paired["insertions"], [])
        self.assertEqual(paired["misses"], [])

    def test_overlapping_spans_resolved_deterministically(self):
        tokens = ["a", "b", "c"]
        alignment = align(tokens, list(tokens))
        ref_spans = [(1, 3, "B"), (0, 2, "A")]
        hyp_spans = [(1, 3, "B"), (0, 2, "A")]
        first = pair_terms(ref_spans, hyp_spans, alignment)
        swapped = pair_terms(
            list(reversed(ref_spans)), list(reversed(hyp_spans)), alignment
        )
        self.assertEqual(first, swapped)
        self.assertEqual(first["hits"], [span(0, 2, "A"), span(1, 3, "B")])
        self.assertEqual(first["insertions"], [])
        self.assertEqual(first["misses"], [])

    def test_same_range_different_terms_not_double_counted(self):
        tokens = ["a", "b"]
        paired = pair_terms(
            [(0, 2, "A")],
            [(0, 2, "B"), (0, 2, "A")],
            align(tokens, list(tokens)),
        )
        self.assertEqual(paired["hits"], [span(0, 2, "A")])
        # All-match "B" over same-term "A" text: ignored, never an insertion.
        self.assertEqual(paired["insertions"], [])
        self.assertEqual(paired["misses"], [])

    def test_never_counted_twice(self):
        tokens = ["a", "b", "c"]
        paired = pair_terms(
            [(0, 2, "A"), (1, 3, "B")],
            [(0, 2, "A"), (1, 3, "B"), (2, 3, "C")],
            align(tokens, list(tokens)),
        )
        key = lambda d: (d["start"], d["end"], d["term_id"])
        hit_keys = {key(d) for d in paired["hits"]}
        ins_keys = {key(d) for d in paired["insertions"]}
        self.assertEqual(hit_keys & ins_keys, set())
        self.assertEqual(len(hit_keys), len(paired["hits"]))
        self.assertEqual(len(ins_keys), len(paired["insertions"]))
        self.assertLessEqual(
            len(hit_keys) + len(ins_keys), 3
        )


if __name__ == "__main__":
    unittest.main()
