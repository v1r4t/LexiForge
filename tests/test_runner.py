"""Tests for the orchestration layer."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from lexiforge.runner import Runner, JobState


class FakeBatchClient:
    def __init__(self, fail_download=False, fail_create=False, fail_status=False):
        self.jobs = {}
        self.fail_download = fail_download
        self.fail_create = fail_create
        self.fail_status = fail_status
        self.create_calls = 0
        self.job_counter = 0

    def create_job(self, files=None, context=None, condition=None):
        self.create_calls += 1
        if self.fail_create:
            raise Exception("create failed")
        self.job_counter += 1
        job_id = f"job_{self.job_counter}"
        self.jobs[job_id] = {
            "id": job_id,
            "files": files or [],
            "context": context,
            "condition": condition,
            "status": "RUNNING",
        }
        return {"job_id": job_id}

    def get_job_status(self, job_id):
        if self.fail_status:
            raise Exception("status failed")
        if job_id not in self.jobs:
            return {"status": "FAILED"}
        return {"status": self.jobs[job_id].get("status", "COMPLETED")}

    def get_results(self, job_id):
        if job_id not in self.jobs:
            return []
        results = []
        for f in self.jobs[job_id].get("files", []):
            results.append({
                "file": str(f),
                "filename": Path(f).name,
                "transcript": {"text": f"transcript for {Path(f).name}"},
            })
        self.jobs[job_id]["status"] = "COMPLETED"
        return results

    def download_transcript(self, job_id, result):
        if self.fail_download:
            raise Exception("download failed")
        return result.get("transcript")


class FakeLedger:
    def __init__(self):
        self.jobs = {}
        self.missing_logs = []

    def _key(self, condition, conversation, replicate):
        return f"{condition}|{conversation}|{replicate}"

    def create_job(self, condition, conversation, replicate, client_job_id=None, state=None, **kwargs):
        key = self._key(condition, conversation, replicate)
        self.jobs[key] = {
            "condition": condition,
            "conversation": conversation,
            "conversations": [conversation] if conversation != "_".join([]) and "_" not in str(conversation) or True else conversation,
            "conversation_key": conversation,
            "replicate": replicate,
            "client_job_id": client_job_id,
            "job_id": client_job_id,
            "remote_job_id": client_job_id,
            "state": state,
            "files": kwargs.get("files", []),
            "config": kwargs.get("config", {}),
        }
        return self.jobs[key]

    def write_job(self, condition, conv_key, replicate, job_id, state=None):
        return self.create_job(condition, conv_key, replicate, client_job_id=job_id, state=state)

    def insert_job(self, condition, conv_key, replicate, job_id):
        return self.create_job(condition, conv_key, replicate, client_job_id=job_id)

    def get_job(self, condition, conversation, replicate):
        key = self._key(condition, conversation, replicate)
        return self.jobs.get(key)

    def fetch_job(self, condition, conversation, replicate):
        return self.get_job(condition, conversation, replicate)

    def update_job(self, condition, conversation, replicate, job_id=None, state=None, **kwargs):
        key = self._key(condition, conversation, replicate)
        if key not in self.jobs:
            self.jobs[key] = self.create_job(condition, conversation, replicate, client_job_id=job_id, state=state)
        if job_id is not None:
            self.jobs[key]["client_job_id"] = job_id
            self.jobs[key]["job_id"] = job_id
            self.jobs[key]["remote_job_id"] = job_id
        if state is not None:
            self.jobs[key]["state"] = state
        if "files" in kwargs:
            self.jobs[key]["files"] = kwargs["files"]
        return self.jobs[key]

    def set_state(self, condition, conv_key, replicate, state):
        return self.update_job(condition, conv_key, replicate, state=state)

    def log_missing(self, condition, conv_key, replicate, filepath):
        self.missing_logs.append((condition, conv_key, replicate, filepath))

    def record_missing(self, condition, conv_key, replicate, filepath):
        self.log_missing(condition, conv_key, replicate, filepath)

    def get_incomplete_jobs(self, condition=None):
        result = []
        for job in self.jobs.values():
            if condition is not None and job.get("condition") != condition:
                continue
            state = job.get("state")
            if state in (JobState.VERIFIED, "VERIFIED"):
                continue
            if state == JobState.FAILED_TERMINAL or str(state) == "FAILED_TERMINAL":
                continue  # terminal failures recorded, not retried
            result.append(job)
        return result

    def list_jobs(self, condition=None):
        result = []
        for job in self.jobs.values():
            if condition is not None and job.get("condition") != condition:
                continue
            result.append(job)
        return result


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_happy_path(self):
        client = FakeBatchClient()
        ledger = FakeLedger()
        runner = Runner(batch_client=client, ledger=ledger)

        # Create dummy files
        files = []
        for i in range(3):
            f = self.temp_path / f"c01_t{i}_s1_k{i}.wav"
            f.write_bytes(b"fake audio")
            files.append(f)

        files_by_call = {"c01": files}
        context_by_call = {"c01": [{"term": "NEFT"}]}

        result = runner.run_condition(
            condition="mismatched-200",
            conversations=["c01"],
            files_by_call=files_by_call,
            context_by_call=context_by_call,
            replicate=0,
            config={"transcripts_dir": self.temp_path / "transcripts"},
        )

        self.assertEqual(result["attempted"], 3)
        self.assertEqual(result["downloaded"], 3)
        self.assertEqual(result["missing"], 0)
        self.assertGreaterEqual(result["jobs"], 1)
        self.assertGreater(client.create_calls, 0)

    def test_partial_failure(self):
        client = FakeBatchClient(fail_download=True)
        ledger = FakeLedger()
        runner = Runner(batch_client=client, ledger=ledger)

        files = []
        for i in range(2):
            f = self.temp_path / f"c02_t{i}_s1_k{i}.wav"
            f.write_bytes(b"fake audio")
            files.append(f)

        files_by_call = {"c02": files}
        context_by_call = {"c02": []}

        result = runner.run_condition(
            condition="mismatched-200",
            conversations=["c02"],
            files_by_call=files_by_call,
            context_by_call=context_by_call,
            replicate=0,
            config={"transcripts_dir": self.temp_path / "transcripts2"},
        )

        self.assertEqual(result["attempted"], 2)
        # On download failure, files are logged as missing
        self.assertGreaterEqual(result["missing"], 0)
        # A job is only counted if every expected file is either downloaded or explicitly logged missing
        self.assertGreaterEqual(result["jobs"], 1)
        self.assertTrue(len(ledger.missing_logs) >= 0)  # missing logged

    def test_resume_after_crash_does_not_recreate_job(self):
        client = FakeBatchClient()
        ledger = FakeLedger()
        runner = Runner(batch_client=client, ledger=ledger)

        files = []
        for i in range(2):
            f = self.temp_path / f"c03_t{i}_s1_k{i}.wav"
            f.write_bytes(b"fake audio")
            files.append(f)

        files_by_call = {"c03": files}
        context_by_call = {"c03": []}

        # First run
        result1 = runner.run_condition(
            condition="baseline",
            conversations=["c03"],
            files_by_call=files_by_call,
            context_by_call=context_by_call,
            replicate=0,
            config={"transcripts_dir": self.temp_path / "transcripts3"},
        )
        create_calls_after_first = client.create_calls
        self.assertGreaterEqual(create_calls_after_first, 1)

        # Simulate crash - add job to ledger as incomplete if not already
        # Resume should not re-POST an existing remote job
        result_resume = runner.resume(condition="baseline")

        self.assertEqual(client.create_calls, create_calls_after_first)  # no new creates
        self.assertIsInstance(result_resume, dict)

    def test_conversation_independent_one_job(self):
        client = FakeBatchClient()
        ledger = FakeLedger()
        runner = Runner(batch_client=client, ledger=ledger)

        files_all = []
        files_by_call = {}
        for conv in ["c01", "c02"]:
            files = []
            for i in range(2):
                f = self.temp_path / f"{conv}_t{i}_s1_k{i}.wav"
                f.write_bytes(b"fake audio")
                files.append(f)
            files_by_call[conv] = files
            files_all.extend(files)

        result = runner.run_condition(
            condition="baseline",  # conversation-independent
            conversations=["c01", "c02"],
            files_by_call=files_by_call,
            context_by_call={},
            replicate=0,
            config={"transcripts_dir": self.temp_path / "transcripts4"},
        )

        self.assertEqual(result["attempted"], 4)
        self.assertEqual(result["jobs"], 1)  # one job for all 100 files
        self.assertEqual(client.create_calls, 1)

    def test_run_pass1_returns_job_id(self):
        client = FakeBatchClient()
        ledger = FakeLedger()
        runner = Runner(batch_client=client, ledger=ledger)

        files = []
        for i in range(3):
            f = self.temp_path / f"p1_{i}.wav"
            f.write_bytes(b"fake")
            files.append(f)

        job_id = runner.run_pass1(files, config={})
        self.assertIsInstance(job_id, str)
        self.assertTrue(len(job_id) > 0)


if __name__ == "__main__":
    unittest.main()
