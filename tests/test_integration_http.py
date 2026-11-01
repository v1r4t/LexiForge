"""Integration tests: the real client code against a faked HTTP transport.

No network, no mocks of our own classes. ``httpx.MockTransport`` swaps only the
socket layer, so retry policy, auth headers, status handling and the job state
machine all execute for real.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from lexiforge.api.client import BatchApiError, BatchClient
from lexiforge.api.prisma import PrismaClient

BASE = "https://api.test"


def _audio(tmp_path: Path, name: str = "c01_t01.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(b"RIFF....WAVEfake")
    return path


class Recorder:
    """Mutable handler state shared with the transport."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.job_polls = 0
        self.rate_limit_once = False


def _handler(recorder: Recorder):
    def handle(request: httpx.Request) -> httpx.Response:
        recorder.requests.append(request)
        path = request.url.path

        if path == "/stt/v3/batch/jobs" and request.method == "POST":
            assert request.headers["X-API-Key-ID"] == "test-key"
            body = request.content
            assert b'name="config"' in body
            return httpx.Response(200, json={"job_id": "job-1"})

        if path == "/stt/v3/batch/jobs/job-1/start":
            return httpx.Response(202, json={"status": "STARTED"})

        if path == "/stt/v3/batch/jobs/job-1":
            if recorder.rate_limit_once:
                recorder.rate_limit_once = False
                return httpx.Response(429, json={"code": "RATE_LIMITED"})
            recorder.job_polls += 1
            status = "IN_PROGRESS" if recorder.job_polls < 2 else "COMPLETED"
            return httpx.Response(200, json={"id": "job-1", "status": status})

        if path == "/stt/v3/batch/jobs/job-1/files":
            return httpx.Response(
                200,
                json=[
                    {
                        "file_id": "f1",
                        "name": "c01_t01.wav",
                        "status": "COMPLETED",
                        "transcript_url": f"{BASE}/signed/f1",
                    }
                ],
            )

        if path == "/signed/f1":
            # Pre-signed URL: must not carry the API key.
            assert "X-API-Key-ID" not in request.headers
            return httpx.Response(200, json={"text": "mera NEFT fail ho gaya"})

        return httpx.Response(404, json={"message": "unexpected"})

    return handle


@pytest.fixture()
def recorder() -> Recorder:
    return Recorder()


def _mock_http(recorder: Recorder) -> httpx.Client:
    """Transport-only client; auth headers are added per request by the client."""
    return httpx.Client(
        transport=httpx.MockTransport(_handler(recorder)),
        timeout=5.0,
    )


def _batch_client(recorder: Recorder) -> BatchClient:
    transport = httpx.MockTransport(_handler(recorder))
    return BatchClient(
        settings={"api_key": "test-key", "base_url": BASE},
        transport=transport,
        poll_interval=0.0,
        backoff_base=0.0,
        backoff_max=0.0,
        max_retries=2,
        client=httpx.Client(transport=transport, timeout=5.0),
    )


def test_batch_lifecycle_end_to_end(tmp_path: Path, recorder: Recorder):
    audio = _audio(tmp_path)
    client = _batch_client(recorder)

    job_id = client.create_job({"model": "prisma-v3.0", "keyterms": ["NEFT"]}, [audio])
    assert job_id == "job-1"

    client.start_job(job_id)
    assert client.wait(job_id, timeout_s=5) == "COMPLETED"

    files = client.list_files(job_id, status="COMPLETED")
    assert files[0]["transcript_url"].endswith("/signed/f1")

    transcript = client.fetch_file_transcript(job_id, files[0], status="COMPLETED")
    assert transcript["text"] == "mera NEFT fail ho gaya"


def test_create_job_posts_exactly_once(tmp_path: Path, recorder: Recorder):
    audio = _audio(tmp_path)
    client = _batch_client(recorder)
    client.create_job({"model": "prisma-v3.0"}, [audio])

    posts = [
        r for r in recorder.requests
        if r.method == "POST" and r.url.path == "/stt/v3/batch/jobs"
    ]
    assert len(posts) == 1


def test_transient_429_is_retried(tmp_path: Path, recorder: Recorder):
    recorder.rate_limit_once = True
    client = _batch_client(recorder)
    client.create_job({"model": "prisma-v3.0"}, [_audio(tmp_path)])
    client.start_job("job-1")

    # First poll returns 429; the client retries and reports COMPLETED.
    assert client.wait("job-1", timeout_s=5) == "COMPLETED"
    polls = [r for r in recorder.requests if r.url.path == "/stt/v3/batch/jobs/job-1"]
    assert len(polls) >= 2


def test_terminal_failure_is_not_retried(tmp_path: Path, recorder: Recorder):
    def failing(request: httpx.Request) -> httpx.Response:
        recorder.requests.append(request)
        if request.url.path.endswith("/start"):
            return httpx.Response(400, json={"code": "INVALID_CONFIG"})
        return httpx.Response(200, json={"job_id": "job-1"})

    transport = httpx.MockTransport(failing)
    client = BatchClient(
        settings={"api_key": "test-key", "base_url": BASE},
        transport=transport,
        max_retries=3,
        client=httpx.Client(transport=transport, timeout=5.0),
    )
    client.create_job({"model": "prisma-v3.0"}, [_audio(tmp_path)])
    with pytest.raises(BatchApiError) as excinfo:
        client.start_job("job-1")
    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "INVALID_CONFIG"
    starts = [r for r in recorder.requests if r.url.path.endswith("/start")]
    assert len(starts) == 1  # never retried


def test_prisma_client_returns_typed_models(recorder: Recorder):
    transport = httpx.MockTransport(_handler(recorder))
    client = PrismaClient(api_key="test-key", base_url=BASE)
    client._client = httpx.Client(transport=transport, timeout=5.0)

    job = client.get_job("job-1")
    assert job.job_id == "job-1"
    assert job.status.value == "IN_PROGRESS"

    transcript = client.fetch_transcript(f"{BASE}/signed/f1")
    assert transcript.text == "mera NEFT fail ho gaya"


def test_get_info_parses_constraints(recorder: Recorder):
    def info_handler(request: httpx.Request) -> httpx.Response:
        recorder.requests.append(request)
        return httpx.Response(
            200,
            json={
                "audio_constraints": {
                    "max_duration_seconds": 1800,
                    "supported_formats": ["wav", "mp3"],
                },
                "models": ["prisma-v3.0"],
            },
        )

    transport = httpx.MockTransport(info_handler)
    client = PrismaClient(api_key="test-key", base_url=BASE)
    client._client = httpx.Client(transport=transport, timeout=5.0)

    info = client.get_info()
    assert info.audio_constraints.max_duration_seconds == 1800
    assert info.models == ["prisma-v3.0"]


def test_missing_transcript_url_is_reported(recorder: Recorder):
    client = _batch_client(recorder)
    with pytest.raises(ValueError, match="transcript_url"):
        client.fetch_file_transcript("job-1", {"file_id": "f1"})


def test_runner_fetches_real_http_transcripts(tmp_path: Path, recorder: Recorder):
    """Runner -> PrismaBackend -> PrismaClient -> transport, transcripts on disk."""
    from lexiforge.plugins import BackendConfig, get_registry
    from lexiforge.runner import Runner

    audio = _audio(tmp_path)
    transcripts_dir = tmp_path / "transcripts"
    backend = get_registry().create(
        "prisma",
        BackendConfig(
            api_key="test-key",
            base_url=BASE,
            extra={"poll_interval_s": 0.0, "job_timeout_s": 5},
        ),
    )
    backend.client._client = _mock_http(recorder)
    runner = Runner(batch_client=backend, ledger=None)

    summary = runner.run_condition(
        condition="mismatched-200",
        conversations=["c01"],
        files_by_call={"c01": [audio]},
        context_by_call={"c01": ["NEFT"]},
        replicate=0,
        config={"transcripts_dir": transcripts_dir, "per_call": True},
    )

    assert summary["attempted"] == 1
    assert summary["downloaded"] == 1, summary
    written = list(transcripts_dir.glob("*.json"))
    assert written, "runner did not persist a transcript"
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert "NEFT" in json.dumps(payload, ensure_ascii=False)

    # The per-call keyterm list must reach the remote config as `keyterms`.
    create_post = next(
        r for r in recorder.requests
        if r.method == "POST" and r.url.path == "/stt/v3/batch/jobs"
    )
    assert b"keyterms" in create_post.content
    assert b"NEFT" in create_post.content


def test_backend_starts_the_job(tmp_path: Path, recorder: Recorder):
    """Prisma needs create-then-start; the runner only calls create."""
    from lexiforge.plugins import BackendConfig, get_registry

    backend = get_registry().create("prisma", BackendConfig(api_key="test-key", base_url=BASE))
    backend.client._client = _mock_http(recorder)

    result = backend.create_job(files=[_audio(tmp_path)], context=["UPI"])
    assert result["job_id"] == "job-1"
    assert any(r.url.path.endswith("/start") for r in recorder.requests)


def test_backend_returns_empty_when_job_failed(tmp_path: Path, recorder: Recorder):
    from lexiforge.plugins import BackendConfig, get_registry

    def failed(request: httpx.Request) -> httpx.Response:
        recorder.requests.append(request)
        if request.url.path == "/stt/v3/batch/jobs":
            return httpx.Response(200, json={"job_id": "job-1"})
        if request.url.path.endswith("/start"):
            return httpx.Response(202, json={})
        return httpx.Response(200, json={"id": "job-1", "status": "FAILED"})

    transport = httpx.MockTransport(failed)
    backend = get_registry().create("prisma", BackendConfig(api_key="test-key", base_url=BASE))
    backend.client._client = httpx.Client(transport=transport, timeout=5.0)

    backend.create_job(files=[_audio(tmp_path)])
    assert backend.get_results("job-1") == []
