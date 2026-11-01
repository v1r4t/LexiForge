"""Tests for the JSONL trace sink and ledger schema versioning."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from lexiforge.ledger import SCHEMA_VERSION, Ledger
from lexiforge.observability.tracing import Tracer


class TestTraceSink:
    def test_spans_are_appended_as_jsonl(self):
        import pytest

        with tempfile.TemporaryDirectory() as tmp:
            sink = Path(tmp) / "spans.jsonl"
            tracer = Tracer(sink=sink)
            with tracer.span("first", {"job": "j1"}):
                pass
            with pytest.raises(ValueError):
                with tracer.span("second"):
                    raise ValueError("boom")

            lines = sink.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 2
            first = json.loads(lines[0])
            assert first["name"] == "first"
            assert first["attributes"] == {"job": "j1"}
            assert first["error"] is None
            assert "ts" in first

            second = json.loads(lines[1])
            assert second["error"] == "ValueError"

    def test_sink_is_optional(self):
        tracer = Tracer()
        with tracer.span("no-sink"):
            pass
        assert tracer.sink is None
        assert [s["name"] for s in tracer.recent()] == ["no-sink"]

    def test_unwritable_sink_does_not_raise(self):
        tracer = Tracer(sink=Path("does") / "not" / "exist" / "spans.jsonl")
        with tracer.span("still-works"):
            pass
        assert [s["name"] for s in tracer.recent()] == ["still-works"]

    def test_set_sink_can_be_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracer = Tracer()
            path = Path(tmp) / "a.jsonl"
            tracer.set_sink(path)
            with tracer.span("written"):
                pass
            assert json.loads(path.read_text(encoding="utf-8").strip())["name"] == "written"
            tracer.set_sink(None)
            with tracer.span("not-written"):
                pass
            assert path.read_text(encoding="utf-8").count("\n") == 1


class TestLedgerSchemaVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "v.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_database_is_stamped(self):
        ledger = Ledger(self.db)
        try:
            self.assertEqual(ledger.schema_version(), SCHEMA_VERSION)
        finally:
            ledger.close()

    def test_reopening_keeps_version_and_data(self):
        ledger = Ledger(self.db)
        ledger.reserve_job("baseline", "c01")
        ledger.close()

        reopened = Ledger(self.db)
        try:
            self.assertEqual(reopened.schema_version(), SCHEMA_VERSION)
            self.assertEqual(reopened.count_jobs(), 1)
        finally:
            reopened.close()

    def test_newer_schema_is_refused(self):
        conn = sqlite3.connect(self.db)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 5}")
        conn.commit()
        conn.close()

        with self.assertRaises(RuntimeError) as excinfo:
            Ledger(self.db)
        self.assertIn("newer than this build", str(excinfo.exception))


if __name__ == "__main__":
    unittest.main()
