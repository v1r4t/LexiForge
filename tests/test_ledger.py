"""Tests for lexiforge.ledger (SQLite harness ledger)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lexiforge.ledger import Ledger


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "test.db")
        self.ledger = Ledger(self.db)
        self.ledger.init()

    def tearDown(self):
        try:
            self.ledger.close()
        finally:
            self.tmp.cleanup()

    def test_reserve_twice_same_key_returns_one_row_same_id(self):
        first = self.ledger.reserve_job(
            "mismatched-200", "c01", 0, "hash1", '{"k": 1}')
        second = self.ledger.reserve_job(
            "mismatched-200", "c01", 0, "hash1", '{"k": 1}')
        self.assertEqual(first, second)
        self.assertEqual(self.ledger.count_jobs(), 1)

    def test_different_replicate_creates_new_row(self):
        first = self.ledger.reserve_job("mismatched-200", "c01", 0, "h", "{}")
        second = self.ledger.reserve_job("mismatched-200", "c01", 1, "h", "{}")
        self.assertNotEqual(first, second)
        self.assertEqual(self.ledger.count_jobs(), 2)

    def test_coverage_counts_correct_after_partial_recording(self):
        cid = self.ledger.reserve_job("mismatched-200", "c01", 0, "h", "{}")
        for i in range(4):
            self.ledger.record_file(cid, f"c01_t{i}", f"remote_{i}", "ready")
        for i in range(3):
            self.ledger.save_transcript(cid, f"c01_t{i}", f"text {i}",
                                       f"/raw/c01_t{i}.json")
        self.ledger.log_missing_entry("mismatched-200", "c01", 0,
                                      file_id="c01_t3", file_path="c01_t3.wav")
        cov = self.ledger.coverage("mismatched-200")
        self.assertIn("c01", cov)
        self.assertEqual(cov["c01"]["attempted"], 4)
        self.assertEqual(cov["c01"]["contributed"], 3)
        self.assertEqual(cov["c01"]["missing"], 1)

    def test_pending_excludes_terminal(self):
        cid = self.ledger.reserve_job("baseline", "c02", 0, "h", "{}")
        self.assertEqual(len(self.ledger.pending("baseline")), 1)
        self.ledger.record_status(cid, "VERIFIED")
        self.assertEqual(self.ledger.pending("baseline"), [])


if __name__ == "__main__":
    unittest.main()
