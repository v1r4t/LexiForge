"""Unified Prisma v3.0 API client for Gnani.

This module provides a high-level, production-ready interface to the Gnani Prisma v3.0 API
with support for both synchronous and asynchronous operations, enhanced error handling,
Pydantic models, and better observability.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import httpx
from pydantic import ValidationError

from lexiforge.api.errors import (
    InvalidAudioError,
    JobCreationError,
    PrismaAuthError,
    PrismaError,
    PrismaNetworkError,
    PrismaNotFoundError,
    PrismaRateLimitError,
    PrismaServerError,
    PrismaTimeoutError,
    PrismaValidationError,
)
from lexiforge.api.models import (
    ApiInfo,
    BatchJob,
    BatchJobConfig,
    FileEntry,
    JobStatus,
    Transcript,
)


class PrismaClient:
    """High-level client for Gnani Prisma v3.0 API."""
    
    DEFAULT_BASE_URL = "https://api.vachana.ai"
    BATCH_PREFIX = "/stt/v3/batch/jobs"
    
    MAX_FILES_PER_JOB = 100
    MAX_FILE_BYTES = 10 * 1024 * 1024
    
    TERMINAL_STATUSES = {"COMPLETED", "PARTIAL_FAILURE", "FAILED", "START_FAILED", "CANCELLED"}
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        verify_ssl: bool = True,
    ):
        self.api_key = api_key or os.environ.get("GNANI_API_KEY") or os.environ.get("API_KEY")
        if not self.api_key:
            raise PrismaAuthError("API key is required. Set GNANI_API_KEY or pass api_key.")
        
        self.base_url = (base_url or os.environ.get("GNANI_BASE_URL") or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.verify_ssl = verify_ssl
        
        # The API key is sent per request, never baked into the client: a
        # pre-signed transcript URL points at object storage, and the key must
        # not travel there.
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            verify=verify_ssl,
        )
        self._async_client: Optional[httpx.AsyncClient] = None

    @property
    def auth_headers(self) -> Dict[str, str]:
        return {"X-API-Key-ID": self.api_key}

    @property
    def async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                verify=self.verify_ssl,
            )
        return self._async_client
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()
    
    def close(self):
        """Close the synchronous transport.

        An ``AsyncClient`` created lazily cannot be closed here (no event
        loop); use ``async with``/``await aclose()`` for that path.
        """
        self._client.close()

    async def aclose(self):
        """Close both transports. Safe when only the sync one was ever used."""
        self._client.close()
        self._async_client = None
        # Nothing async to close: httpx.Client has no aclose().
    
    def _handle_response(self, response: httpx.Response):
        """Handle API response and raise appropriate errors."""
        if response.status_code < 400:
            return response
        
        try:
            error_data = response.json()
        except Exception:
            error_data = {"message": response.text}
        
        message = error_data.get("message") or error_data.get("error") or f"HTTP {response.status_code}"
        details = error_data
        
        if response.status_code in (401, 403):
            raise PrismaAuthError(message, details)
        elif response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise PrismaRateLimitError(
                message, 
                retry_after=int(retry_after) if retry_after else None,
                details=details
            )
        elif response.status_code == 404:
            raise PrismaNotFoundError(message, details)
        elif response.status_code in (400, 422):
            raise PrismaValidationError(message, details)
        elif response.status_code >= 500:
            raise PrismaServerError(message, details)
        else:
            raise PrismaError(message, details)
    
    def get_info(self) -> ApiInfo:
        """Get API information and constraints."""
        try:
            response = self._client.get(f"{self.base_url}/stt/v3/languages")
            self._handle_response(response)
            data = response.json()
            return ApiInfo.model_validate(data)
        except ValidationError as e:
            raise PrismaError(f"Failed to parse API info: {e}")
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    async def aget_info(self) -> ApiInfo:
        """Async version of get_info."""
        try:
            response = await self.async_client.get(f"{self.base_url}/stt/v3/languages")
            self._handle_response(response)
            data = response.json()
            return ApiInfo.model_validate(data)
        except ValidationError as e:
            raise PrismaError(f"Failed to parse API info: {e}")
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    def create_job(
        self,
        files: Union[List[Union[str, Path]], List[Path]],
        config: Optional[Union[BatchJobConfig, Dict[str, Any]]] = None,
    ) -> str:
        """Create a batch transcription job."""
        paths = [Path(f) for f in files]
        
        if len(paths) > self.MAX_FILES_PER_JOB:
            raise InvalidAudioError(f"Too many files: {len(paths)} > {self.MAX_FILES_PER_JOB}")
        if not paths:
            raise InvalidAudioError("At least one audio file is required")
        
        if config is None:
            config = BatchJobConfig()
        elif isinstance(config, dict):
            try:
                config = BatchJobConfig.model_validate(config)
            except ValidationError as e:
                raise PrismaValidationError(f"Invalid config: {e}")
        
        multipart: List[tuple] = []
        for path in paths:
            if not path.is_file():
                raise InvalidAudioError(f"Audio file not found: {path}")
            size = path.stat().st_size
            if size > self.MAX_FILE_BYTES:
                raise InvalidAudioError(f"File too large ({size} bytes): {path}")
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            multipart.append(("files", (path.name, path.read_bytes(), mime)))
        
        try:
            response = self._client.post(
                f"{self.base_url}{self.BATCH_PREFIX}",
                data={"config": json.dumps(config.model_dump(exclude_none=True))},
                files=multipart,
                headers=self.auth_headers,
            )
            self._handle_response(response)
            data = response.json()
            job_id = data.get("job_id") or data.get("id")
            if not job_id:
                raise JobCreationError("No job_id in response", data)
            return str(job_id)
        except (PrismaError, JobCreationError):
            raise
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    async def acreate_job(
        self,
        files: Union[List[Union[str, Path]], List[Path]],
        config: Optional[Union[BatchJobConfig, Dict[str, Any]]] = None,
    ) -> str:
        """Async version of create_job."""
        paths = [Path(f) for f in files]
        
        if len(paths) > self.MAX_FILES_PER_JOB:
            raise InvalidAudioError(f"Too many files: {len(paths)} > {self.MAX_FILES_PER_JOB}")
        if not paths:
            raise InvalidAudioError("At least one audio file is required")
        
        if config is None:
            config = BatchJobConfig()
        elif isinstance(config, dict):
            try:
                config = BatchJobConfig.model_validate(config)
            except ValidationError as e:
                raise PrismaValidationError(f"Invalid config: {e}")
        
        multipart: List[tuple] = []
        for path in paths:
            if not path.is_file():
                raise InvalidAudioError(f"Audio file not found: {path}")
            size = path.stat().st_size
            if size > self.MAX_FILE_BYTES:
                raise InvalidAudioError(f"File too large ({size} bytes): {path}")
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            # Need to read file content
            with open(path, 'rb') as f:
                multipart.append(("files", (path.name, f.read(), mime)))
        
        try:
            response = await self.async_client.post(
                f"{self.base_url}{self.BATCH_PREFIX}",
                data={"config": json.dumps(config.model_dump(exclude_none=True))},
                files=multipart,
                headers=self.auth_headers,
            )
            self._handle_response(response)
            data = response.json()
            job_id = data.get("job_id") or data.get("id")
            if not job_id:
                raise JobCreationError("No job_id in response", data)
            return str(job_id)
        except (PrismaError, JobCreationError):
            raise
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    def start_job(self, job_id: str) -> None:
        """Start a created batch job."""
        try:
            response = self._client.post(
                f"{self.base_url}{self.BATCH_PREFIX}/{job_id}/start",
                headers=self.auth_headers,
            )
            self._handle_response(response)
        except (PrismaError):
            raise
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    async def astart_job(self, job_id: str) -> None:
        """Async version of start_job."""
        try:
            response = await self.async_client.post(
                f"{self.base_url}{self.BATCH_PREFIX}/{job_id}/start",
                headers=self.auth_headers,
            )
            self._handle_response(response)
        except (PrismaError):
            raise
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    def get_job(self, job_id: str) -> BatchJob:
        """Get job status."""
        try:
            response = self._client.get(
                f"{self.base_url}{self.BATCH_PREFIX}/{job_id}",
                headers=self.auth_headers,
            )
            self._handle_response(response)
            data = response.json()
            # Unwrap if needed
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            elif isinstance(data, dict) and "job" in data:
                data = data["job"]
            return BatchJob.model_validate(data)
        except ValidationError as e:
            raise PrismaError(f"Failed to parse job: {e}")
        except (PrismaError):
            raise
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    async def aget_job(self, job_id: str) -> BatchJob:
        """Async version of get_job."""
        try:
            response = await self.async_client.get(
                f"{self.base_url}{self.BATCH_PREFIX}/{job_id}",
                headers=self.auth_headers,
            )
            self._handle_response(response)
            data = response.json()
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            elif isinstance(data, dict) and "job" in data:
                data = data["job"]
            return BatchJob.model_validate(data)
        except ValidationError as e:
            raise PrismaError(f"Failed to parse job: {e}")
        except (PrismaError):
            raise
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    def list_files(self, job_id: str, status: Optional[str] = None) -> List[FileEntry]:
        """List files in a job."""
        try:
            params = {"status": status} if status else None
            response = self._client.get(
                f"{self.base_url}{self.BATCH_PREFIX}/{job_id}/files",
                params=params,
                headers=self.auth_headers,
            )
            self._handle_response(response)
            data = response.json()
            files_data = data
            if isinstance(data, dict):
                for key in ("files", "data", "items"):
                    if isinstance(data.get(key), list):
                        files_data = data[key]
                        break
            if not isinstance(files_data, list):
                raise PrismaError("Unexpected response format", data)
            return [FileEntry.model_validate(f) for f in files_data]
        except ValidationError as e:
            raise PrismaError(f"Failed to parse files: {e}")
        except (PrismaError):
            raise
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    async def alist_files(self, job_id: str, status: Optional[str] = None) -> List[FileEntry]:
        """Async version of list_files."""
        try:
            params = {"status": status} if status else None
            response = await self.async_client.get(
                f"{self.base_url}{self.BATCH_PREFIX}/{job_id}/files",
                params=params,
                headers=self.auth_headers,
            )
            self._handle_response(response)
            data = response.json()
            files_data = data
            if isinstance(data, dict):
                for key in ("files", "data", "items"):
                    if isinstance(data.get(key), list):
                        files_data = data[key]
                        break
            if not isinstance(files_data, list):
                raise PrismaError("Unexpected response format", data)
            return [FileEntry.model_validate(f) for f in files_data]
        except ValidationError as e:
            raise PrismaError(f"Failed to parse files: {e}")
        except (PrismaError):
            raise
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    def fetch_transcript(self, transcript_url: str) -> Transcript:
        """Fetch transcript from a pre-signed URL."""
        try:
            # No auth header for pre-signed URLs
            response = self._client.get(transcript_url, headers={})
            self._handle_response(response)
            data = response.json()
            return Transcript.model_validate(data)
        except ValidationError as e:
            raise PrismaError(f"Failed to parse transcript: {e}")
        except (PrismaError):
            raise
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    async def afetch_transcript(self, transcript_url: str) -> Transcript:
        """Async version of fetch_transcript."""
        try:
            response = await self.async_client.get(transcript_url, headers={})
            self._handle_response(response)
            data = response.json()
            return Transcript.model_validate(data)
        except ValidationError as e:
            raise PrismaError(f"Failed to parse transcript: {e}")
        except (PrismaError):
            raise
        except httpx.TimeoutException:
            raise PrismaTimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise PrismaNetworkError(f"Network error: {e}")
    
    def wait_for_completion(self, job_id: str, timeout: int = 1800, poll_interval: float = 15.0) -> JobStatus:
        """Wait for job to reach terminal status."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            job = self.get_job(job_id)
            if job.status.value in self.TERMINAL_STATUSES:
                return job.status
            time.sleep(poll_interval)
        raise PrismaTimeoutError(f"Job {job_id} did not complete within {timeout}s")
    
    async def await_completion(self, job_id: str, timeout: int = 1800, poll_interval: float = 15.0) -> JobStatus:
        """Async version of wait_for_completion."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            job = await self.aget_job(job_id)
            if job.status.value in self.TERMINAL_STATUSES:
                return job.status
            await asyncio.sleep(poll_interval)
        raise PrismaTimeoutError(f"Job {job_id} did not complete within {timeout}s")


# Convenience function
def create_client(api_key: Optional[str] = None, **kwargs) -> PrismaClient:
    """Create a Prisma client instance."""
    return PrismaClient(api_key=api_key, **kwargs)
