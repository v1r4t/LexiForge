"""Tests for the Prisma client error mapping, async helper and plugin registry.

The earlier suite only exercised a mocked ``create_job``, which is why a broken
``aclose`` (sync client awaited as if async) shipped unnoticed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from lexiforge.api.async_client import AsyncPrismaClient
from lexiforge.api.errors import (
    PrismaAuthError,
    PrismaNotFoundError,
    PrismaRateLimitError,
    PrismaServerError,
    PrismaValidationError,
)
from lexiforge.api.models import BatchJob, BatchJobConfig, FileEntry, JobStatus
from lexiforge.api.prisma import PrismaClient


def _client_with_response(status: int, payload=None, headers=None) -> PrismaClient:
    response = httpx.Response(
        status,
        json=payload if payload is not None else {},
        headers=headers or {},
        request=httpx.Request("GET", "http://test/x"),
    )
    client = PrismaClient(api_key="test-key", base_url="http://test")
    client._client = MagicMock()
    client._client.get.return_value = response
    client._client.post.return_value = response
    return client


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, PrismaAuthError),
        (403, PrismaAuthError),
        (404, PrismaNotFoundError),
        (400, PrismaValidationError),
        (422, PrismaValidationError),
        (500, PrismaServerError),
        (503, PrismaServerError),
    ],
)
def test_http_errors_map_to_typed_exceptions(status, expected):
    client = _client_with_response(status, {"message": "boom"})
    with pytest.raises(expected):
        client.get_info()


def test_rate_limit_carries_retry_after():
    client = _client_with_response(429, {"message": "slow down"}, {"Retry-After": "7"})
    with pytest.raises(PrismaRateLimitError) as excinfo:
        client.get_info()
    assert excinfo.value.retry_after == 7


def test_missing_api_key_is_rejected(monkeypatch):
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(PrismaAuthError):
        PrismaClient()


def test_aclose_closes_sync_client():
    client = PrismaClient(api_key="test-key")
    asyncio.run(client.aclose())  # must not raise AttributeError


def test_async_client_aclose_is_awaitable():
    client = AsyncPrismaClient(api_key="test-key")
    asyncio.run(client.aclose())


def test_async_client_rejects_bad_concurrency():
    with pytest.raises(ValueError):
        AsyncPrismaClient(api_key="test-key", max_concurrent=0)


def test_async_create_job_batch_preserves_order(tmp_path: Path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"fake")
    other = tmp_path / "b.wav"
    other.write_bytes(b"fake")

    client = AsyncPrismaClient(api_key="test-key")
    with patch.object(client.client, "create_job", side_effect=["job-a", "job-b"]) as call:
        jobs = asyncio.run(client.create_job_batch([[audio], [other]]))
    assert jobs == ["job-a", "job-b"]
    assert call.call_count == 2


def test_create_job_rejects_missing_file():
    client = PrismaClient(api_key="test-key")
    with pytest.raises(Exception):
        client.create_job([Path("does-not-exist.wav")])


def test_batch_job_model_accepts_id_alias():
    job = BatchJob.model_validate({"id": "job-1", "status": "COMPLETED"})
    assert job.job_id == "job-1"
    assert job.status is JobStatus.COMPLETED


def test_file_entry_defaults_to_pending():
    entry = FileEntry.model_validate({"file_id": "f1"})
    assert entry.status.value == "PENDING"


def test_batch_job_config_round_trips_extra_keys():
    config = BatchJobConfig.model_validate({"model": "prisma-v3.0", "keyterms": ["NEFT"]})
    dumped = config.model_dump(exclude_none=True)
    assert dumped["model"] == "prisma-v3.0"
    assert dumped["keyterms"] == ["NEFT"]


def test_plugin_registry_creates_prisma_backend(monkeypatch):
    from lexiforge.plugins import BackendConfig, get_registry

    registry = get_registry()
    assert {"prisma", "gnani", "vachana"} <= set(registry.list_backends())

    backend = registry.create(
        "prisma", BackendConfig(api_key="test-key", base_url="http://test")
    )
    assert backend.name == "prisma"
    assert "wav" in backend.supported_formats
    assert isinstance(backend.client, PrismaClient)
    backend.close()
