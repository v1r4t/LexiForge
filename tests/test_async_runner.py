"""Tests for bounded-concurrency condition runs."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from lexiforge.runner import Runner


class CountingClient:
    """Minimal runner-facing client that records overlap."""

    def __init__(self, delay: float = 0.02) -> None:
        self.delay = delay
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.created: list[str] = []

    def create_job(self, files=None, context=None, condition=None):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.created.append(condition)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return {"job_id": f"job-{condition}"}

    def get_job_status(self, job_id):
        return {"status": "COMPLETED"}

    def get_results(self, job_id):
        return []

    def download_transcript(self, job_id, result):
        return {"text": ""}


def _run(condition: str) -> dict:
    return {
        "condition": condition,
        "conversations": ["c01"],
        "files_by_call": {"c01": []},
        "context_by_call": {"c01": []},
        "replicate": 0,
        "config": {"per_call": True},
    }


def test_runs_are_actually_concurrent():
    client = CountingClient()
    runner = Runner(batch_client=client, ledger=None)

    results = asyncio.run(
        runner.run_conditions_async([_run(f"cond{i}") for i in range(4)], max_concurrent=4)
    )

    assert set(results) == {"cond0", "cond1", "cond2", "cond3"}
    assert client.peak > 1, "runs were serialised"
    assert client.peak <= 4


def test_concurrency_limit_is_respected():
    client = CountingClient(delay=0.03)
    runner = Runner(batch_client=client, ledger=None)

    asyncio.run(
        runner.run_conditions_async([_run(f"cond{i}") for i in range(6)], max_concurrent=2)
    )
    assert client.peak <= 2


def test_each_condition_runs_once():
    client = CountingClient()
    runner = Runner(batch_client=client, ledger=None)

    asyncio.run(
        runner.run_conditions_async([_run("baseline"), _run("mismatched-200")], max_concurrent=2)
    )
    assert sorted(client.created) == ["baseline", "mismatched-200"]


def test_invalid_concurrency_rejected():
    runner = Runner(batch_client=CountingClient(), ledger=None)
    with pytest.raises(ValueError, match="max_concurrent"):
        asyncio.run(runner.run_conditions_async([_run("baseline")], max_concurrent=0))


def test_async_runner_records_spans():
    from lexiforge.observability import get_tracer

    get_tracer().clear()
    runner = Runner(batch_client=CountingClient(delay=0.0), ledger=None)
    asyncio.run(runner.run_conditions_async([_run("baseline")], max_concurrent=1))
    assert any(span["name"] == "run_condition" for span in get_tracer().recent())
