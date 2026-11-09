"""Tests for lexiforge.api.batch_admin. No network: fake client only."""

from __future__ import annotations

import unittest

from lexiforge.api import batch_admin
from lexiforge.api.client import BatchApiError


class FakeClient:
    """Minimal BatchClient stand-in that records calls."""

    def __init__(self, jobs=None, statuses=None):
        self.jobs = list(jobs or [])
        self.statuses = dict(statuses or {})
        self.calls: list[tuple[str, tuple]] = []

    def list_jobs(self, *, status=None, limit=100):
        self.calls.append(("list_jobs", (status, limit)))
        return [dict(job) for job in self.jobs]

    def get_job(self, job_id):
        self.calls.append(("get_job", (job_id,)))
        return {"job_id": job_id, "status": self.statuses[job_id]}

    def job_status(self, job):
        status = job.get("status")
        return str(status).upper() if status is not None else None

    def cancel_job(self, job_id):
        self.calls.append(("cancel_job", (job_id,)))
        return self.statuses.get(job_id, "CANCELLED")


class TestReconcile(unittest.TestCase):
    def test_flags_orphans_and_missing(self):
        client = FakeClient(jobs=[{"job_id": "a"}, {"id": "orphan"}])
        ledger_rows = [
            {"remote_job_id": "a"},
            {"remote_job_id": "missing"},
        ]
        result = batch_admin.reconcile(client, ledger_rows)
        self.assertEqual(result["known"], ["a"])
        self.assertEqual(result["orphans"], ["orphan"])
        self.assertEqual(result["missing"], ["missing"])

    def test_output_is_sorted_and_deduplicated(self):
        client = FakeClient(
            jobs=[{"job_id": "b"}, {"job_id": "a"}, {"job_id": "a"}]
        )
        ledger_rows = [
            {"remote_job_id": "a"},
            {"remote_job_id": "a"},
            {"remote_job_id": "c"},
        ]
        result = batch_admin.reconcile(client, ledger_rows)
        self.assertEqual(result["known"], ["a"])
        self.assertEqual(result["orphans"], ["b"])
        self.assertEqual(result["missing"], ["c"])

    def test_prefers_remote_job_id_over_client_job_id(self):
        client = FakeClient(jobs=[{"job_id": "server-id"}])
        result = batch_admin.reconcile(
            client, [{"client_job_id": "local-id", "remote_job_id": "server-id"}]
        )
        self.assertEqual(result["known"], ["server-id"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["orphans"], [])

    def test_empty_ledger_marks_every_server_job_orphan(self):
        client = FakeClient(jobs=[{"job_id": "a"}, {"job_id": "b"}])
        result = batch_admin.reconcile(client, [])
        self.assertEqual(result["known"], [])
        self.assertEqual(result["orphans"], ["a", "b"])
        self.assertEqual(result["missing"], [])


class TestCancel(unittest.TestCase):
    def test_cancels_each_job_once_and_returns_statuses(self):
        client = FakeClient(statuses={"a": "CANCELLED", "b": "COMPLETED"})
        result = batch_admin.cancel(client, ["a", "b", "a"])
        self.assertEqual(result, {"a": "CANCELLED", "b": "COMPLETED"})
        cancelled = [call for call in client.calls if call[0] == "cancel_job"]
        self.assertEqual(cancelled, [("cancel_job", ("a",)), ("cancel_job", ("b",))])


class TestResume(unittest.TestCase):
    def test_returns_only_non_terminal_remote_jobs(self):
        client = FakeClient(statuses={"done": "COMPLETED", "run": "PROCESSING"})
        rows = [{"remote_job_id": "done"}, {"remote_job_id": "run"}]
        self.assertEqual(batch_admin.resume(client, rows), ["run"])

    def test_skips_rows_without_remote_id_and_missing_remote_jobs(self):
        def get_job(job_id):
            raise BatchApiError("not found", status_code=404)

        client = FakeClient()
        client.get_job = get_job  # type: ignore[method-assign]
        rows = [{"remote_job_id": ""}, {"remote_job_id": "gone"}, {"client_job_id": "draft"}]
        self.assertEqual(batch_admin.resume(client, rows), [])

    def test_never_creates_jobs(self):
        client = FakeClient(statuses={"run": "PROCESSING"})
        self.assertFalse(hasattr(client, "create_job"))
        batch_admin.resume(client, [{"remote_job_id": "run"}])
        self.assertEqual([call[0] for call in client.calls], ["get_job"])


if __name__ == "__main__":
    unittest.main()
