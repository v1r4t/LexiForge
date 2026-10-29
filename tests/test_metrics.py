"""Tests for metrics."""

import unittest

from lexiforge.score import metrics


class TestTermRecall(unittest.TestCase):
    def test_zero_denominator_returns_none(self):
        rows = [
            {'term_id': 't1', 'hit': True, 'denom': False},
            {'term_id': 't2', 'hit': False, 'denom': False},
        ]
        res = metrics.term_recall(rows)
        self.assertIsNone(res['rate'])
        self.assertEqual(res['denominator'], 0)

    def test_hand_computed_recall(self):
        rows = [
            {'term_id': 't1', 'hit': True},
            {'term_id': 't2', 'hit': False},
            {'term_id': 't3', 'hit': True},
            {'term_id': 't4', 'hit': True},
        ]
        res = metrics.term_recall(rows)
        self.assertEqual(res['numerator'], 3)
        self.assertEqual(res['denominator'], 4)
        self.assertAlmostEqual(res['rate'], 0.75)


class TestInsertionsPerUtterance(unittest.TestCase):
    def test_insertion_counts_per_utterance(self):
        rows = [
            {'utterance_id': 'u1', 'insertion': True},
            {'utterance_id': 'u1', 'insertion': False},
            {'utterance_id': 'u2', 'insertion': True},
            {'utterance_id': 'u2', 'insertion': True},
            {'utterance_id': 'u3'},  # no insertion
        ]
        res = metrics.insertions_per_utterance(rows)
        self.assertEqual(res['n_utterances'], 3)
        self.assertEqual(res['total_events'], 3)
        self.assertAlmostEqual(res['mean'], 1.0)
        self.assertIsInstance(res['95% interval'], (tuple, list))
        self.assertEqual(len(res['95% interval']), 2)


class TestWER(unittest.TestCase):
    def test_raw_vs_folded_wer_differ_on_case_punctuation_only(self):
        ref = "Hello World!"
        hyp = "hello world"
        raw = metrics.wer(ref, hyp, level="raw")
        folded = metrics.wer(ref, hyp, level="folded")
        self.assertNotEqual(raw, folded)
        self.assertGreater(raw, folded)

    def test_unknown_level_raises(self):
        with self.assertRaises(ValueError):
            metrics.wer("a", "a", level="unknown")


if __name__ == '__main__':
    unittest.main()
