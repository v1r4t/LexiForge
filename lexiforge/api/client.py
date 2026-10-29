"""Thin client for the Gnani Prisma v3.0 batch STT endpoints.

Flow: ``create_job`` (multipart: ``config`` JSON string + repeated ``files``)
-> ``start_job`` -> poll ``get_job`` via ``wait`` until a terminal status ->
``list_files`` -> ``fetch_transcript`` per ``transcript_url``.

Only this module performs network I/O for batch jobs. Verified facts encoded
here: auth header ``X-API-Key-ID``; terminal statuses COMPLETED,
PARTIAL_FAILURE, FAILED, START_FAILED, CANCELLED; ``transcript_url`` expires
after ~1h; limits 100 files/job and 10MB/file; error codes 429 RATE_LIMITED
(with no Retry-After), 504 UPSTREAM_TIMEOUT, 400 INVALID_CONFIG.

Retry policy: job creation is never retried (a crash between POST and ledger
write is the double-billing window, so callers persist a client job id first).
Idempotent reads retry transient 429/504 with jittered backoff.
"""

from __future__ import annotations

import json
import mimetypes
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import httpx

BATCH_PREFIX = "/stt/v3/batch/jobs"
DEFAULT_BASE_URL = "https://api.vachana.ai"

TERMINAL_STATUSES = frozenset(
    {"COMPLETED", "PARTIAL_FAILURE", "FAILED", "START_FAILED", "CANCELLED"}
)

MAX_FILES_PER_JOB = 100
MAX_FILE_BYTES = 10 * 1024 * 1024

TRANSIENT_STATUS_CODES = frozenset({429, 504})
_EXPIRY_SIGNALS = ("EXPIRED",)


class BatchApiError(Exception):
    """A batch API call failed (HTTP error or unreachable host)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.payload = payload


@dataclass
class Settings:
    """Connection settings. Also readable from ``GNANI_*`` env vars."""

    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    poll_interval: float = 15.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            base_url=os.environ.get("GNANI_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.environ.get("GNANI_API_KEY", ""),
        )


def _resolve_base_url(settings: Any, override: str | None) -> str:
    if override:
        return override.rstrip("/")
    for attr in ("base_url", "baseUrl", "GNANI_BASE_URL"):
        if isinstance(settings, Mapping):
            value = settings.get(attr)
        else:
            value = getattr(settings, attr, None)
        if value:
            return str(value).rstrip("/")
    return os.environ.get("GNANI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _resolve_api_key(settings: Any, override: str | None) -> str:
    if override:
        return override
    for attr in ("api_key", "apiKey", "GNANI_API_KEY"):
        if isinstance(settings, Mapping):
            value = settings.get(attr)
        else:
            value = getattr(settings, attr, None)
        if value:
            return str(value)
    return os.environ.get("GNANI_API_KEY", "")


def _resolve_poll_interval(settings: Any, default: float) -> float:
    if isinstance(settings, Mapping):
        value = settings.get("poll_interval", default)
    else:
        value = getattr(settings, "poll_interval", default)
    return float(value)


def _error_details(response: httpx.Response) -> tuple[str | None, Any]:
    try:
        payload = response.json()
    except ValueError:
        return None, None
    if isinstance(payload, Mapping):
        code = payload.get("code") or payload.get("error_code") or payload.get("error")
        if isinstance(code, Mapping):
            code = code.get("code")
        return (str(code) if code is not None else None), payload
    return None, payload


def _is_expired(exc: BatchApiError) -> bool:
    if exc.status_code in (401, 403, 410):
        return True
    haystack = f"{exc.code or ''} {exc}".upper()
    return any(signal in haystack for signal in _EXPIRY_SIGNALS)


def _first_present(payload: Mapping, *keys: str) -> Any:
    for key in keys:
        if payload.get(key) is not None:
            return payload[key]
    return None


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        for key in ("data", "job", "result"):
            nested = payload.get(key)
            if isinstance(nested, Mapping) and (
                "status" in nested or "job_id" in nested or nested.get("id")
            ):
                return nested
    return payload


@dataclass
class BatchClient:
    """Blocking client for batch STT jobs over httpx (60s timeout)."""

    settings: Any = None
    transport: httpx.BaseTransport | None = None
    client: httpx.Client | None = None
    poll_interval: float | None = None
    timeout: float = 60.0
    backoff_base: float = 1.0
    backoff_max: float = 30.0
    max_retries: int = 3
    base_url: str | None = None
    api_key: str | None = None
    _http: httpx.Client = field(init=False, repr=False)

    def __init__(
        self,
        settings: Any = None,
        *,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
        poll_interval: float | None = None,
        timeout: float = 60.0,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
        max_retries: int = 3,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.timeout = timeout
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.max_retries = max_retries
        self.base_url = _resolve_base_url(settings, base_url)
        self.api_key = _resolve_api_key(settings, api_key)
        if not self.api_key:
            raise ValueError("API key is missing (GNANI_API_KEY / settings api_key).")
        if poll_interval is None:
            poll_interval = _resolve_poll_interval(settings, 15.0)
        self.poll_interval = float(poll_interval)
        if client is not None:
            self._http = client
            self.client = client
        else:
            self._http = httpx.Client(transport=transport, timeout=timeout)
            self.client = self._http

    # -- internals ---------------------------------------------------------
    @property
    def headers(self) -> dict[str, str]:
        return {"X-API-Key-ID": self.api_key}

    def _job_url(self, *parts: str) -> str:
        return "/".join([self.base_url + BATCH_PREFIX, *[p.strip("/") for p in parts]])

    def _backoff(self, attempt: int) -> float:
        capped = min(self.backoff_base * (2**attempt), self.backoff_max)
        return capped + random.uniform(0, min(capped, 1.0))

    def _call(
        self,
        method: str,
        url: str,
        *,
        action: str,
        retry_transient: bool,
        send_auth: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        attempts = 1 + (self.max_retries if retry_transient else 0)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                request = self._http.build_request(
                    method,
                    url,
                    headers=self.headers if send_auth else None,
                    **kwargs,
                )
                response = self._http.send(request)
            except httpx.HTTPError as exc:
                last_error = exc
                if retry_transient and attempt < attempts - 1:
                    time.sleep(self._backoff(attempt))
                    continue
                raise BatchApiError(f"{action} failed: {exc}") from exc
            if response.status_code < 400:
                return response
            if (
                retry_transient
                and response.status_code in TRANSIENT_STATUS_CODES
                and attempt < attempts - 1
            ):
                # 429 carries no Retry-After: jittered backoff per design §10.
                time.sleep(self._backoff(attempt))
                continue
            code, payload = _error_details(response)
            label = f" {code}" if code else ""
            raise BatchApiError(
                f"{action} failed: HTTP {response.status_code}{label}",
                status_code=response.status_code,
                code=code,
                payload=payload,
            )
        raise BatchApiError(f"{action} failed: {last_error}")

    @staticmethod
    def _json(response: httpx.Response, action: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise BatchApiError(f"{action} returned non-JSON output.") from exc

    # -- job lifecycle -----------------------------------------------------
    def create_job(self, config: dict, files: list[Path]) -> str:
        """Create a batch job. Never retried: exactly one POST per call."""
        paths = [Path(p) for p in files]
        if len(paths) > MAX_FILES_PER_JOB:
            raise ValueError(f"Too many files: {len(paths)} > {MAX_FILES_PER_JOB}.")
        if not paths:
            raise ValueError("At least one audio file is required.")
        multipart: list[tuple[str, tuple[str, bytes, str]]] = []
        for path in paths:
            if not path.is_file():
                raise ValueError(f"Audio file not found: {path}.")
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                raise ValueError(f"File too large ({size} bytes): {path}.")
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            multipart.append(("files", (path.name, path.read_bytes(), mime)))
        response = self._call(
            "POST",
            self._job_url(),
            action="create_job",
            retry_transient=False,
            data={"config": json.dumps(config)},
            files=multipart,
        )
        payload = _unwrap(self._json(response, "create_job"))
        job_id = _first_present(payload, "job_id", "jobId", "id") if isinstance(payload, Mapping) else None
        if not job_id:
            raise BatchApiError("create_job returned no job id.", payload=payload)
        return str(job_id)

    def start_job(self, job_id: str) -> None:
        """Start a created job. Not retried (state-changing POST)."""
        self._call(
            "POST", self._job_url(job_id, "start"), action="start_job", retry_transient=False
        )

    def get_job(self, job_id: str) -> dict:
        """Fetch the current job record (retries transient 429/504)."""
        response = self._call(
            "GET", self._job_url(job_id), action="get_job", retry_transient=True
        )
        payload = self._json(response, "get_job")
        if not isinstance(payload, Mapping):
            raise BatchApiError("get_job returned a non-object payload.", payload=payload)
        return dict(_unwrap(payload))

    def job_status(self, job: Mapping) -> str | None:
        status = _first_present(_unwrap(job), "status", "state", "job_status")
        return str(status).upper() if status is not None else None

    def list_files(self, job_id: str, status: str | None = None) -> list[dict]:
        """List per-file records; each carries ``transcript_url`` (~1h TTL)."""
        params = {"status": status} if status else None
        response = self._call(
            "GET",
            self._job_url(job_id, "files"),
            action="list_files",
            retry_transient=True,
            params=params,
        )
        payload = self._json(response, "list_files")
        if isinstance(payload, list):
            return [dict(item) for item in payload]
        if isinstance(payload, Mapping):
            for key in ("files", "data", "items"):
                if isinstance(payload.get(key), list):
                    return [dict(item) for item in payload[key]]
        raise BatchApiError("list_files returned an unexpected payload.", payload=payload)

    def fetch_transcript(self, url: str) -> dict:
        """GET a ``transcript_url``. Pre-signed: no auth header is attached."""
        response = self._call(
            "GET", url, action="fetch_transcript", retry_transient=True, send_auth=False
        )
        payload = self._json(response, "fetch_transcript")
        if not isinstance(payload, Mapping):
            raise BatchApiError("fetch_transcript returned non-object JSON.", payload=payload)
        return dict(payload)

    def fetch_file_transcript(
        self, job_id: str, file_entry: Mapping, *, status: str | None = None
    ) -> dict:
        """Fetch one file's transcript, refetching the file list once on expiry."""
        url = file_entry.get("transcript_url")
        if not url:
            raise ValueError("File entry has no transcript_url.")
        try:
            return self.fetch_transcript(str(url))
        except BatchApiError as exc:
            if not _is_expired(exc):
                raise
        refreshed = self.list_files(job_id, status=status)
        match = self._match_file(file_entry, refreshed)
        if match is None or not match.get("transcript_url"):
            raise BatchApiError("Refreshed file list has no usable transcript_url.")
        return self.fetch_transcript(str(match["transcript_url"]))

    @staticmethod
    def _match_file(entry: Mapping, files: list[dict]) -> dict | None:
        for key in ("file_id", "fileId", "id", "name", "file_name", "filename"):
            wanted = entry.get(key)
            if wanted is None:
                continue
            for candidate in files:
                if candidate.get(key) == wanted:
                    return candidate
        return None

    def fetch_all_transcripts(
        self, job_id: str, status: str | None = "COMPLETED"
    ) -> dict[str, dict]:
        """Fetch every listed file's transcript, keyed by file id or name."""
        out: dict[str, dict] = {}
        for entry in self.list_files(job_id, status=status):
            key = _first_present(entry, "file_id", "fileId", "id", "name", "file_name")
            out[str(key)] = self.fetch_file_transcript(job_id, entry, status=status)
        return out

    def wait(self, job_id: str, timeout_s: float = 1800, poll_interval: float | None = None) -> str:
        """Poll ``get_job`` until a terminal status; return that status."""
        interval = self.poll_interval if poll_interval is None else float(poll_interval)
        deadline = time.monotonic() + float(timeout_s)
        while True:
            try:
                job = self.get_job(job_id)
            except BatchApiError as exc:
                if exc.status_code not in TRANSIENT_STATUS_CODES:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for job {job_id}.") from exc
                time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
                continue
            status = self.job_status(job)
            if status in TERMINAL_STATUSES:
                return status
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for job {job_id} (last={status}).")
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "BatchClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
