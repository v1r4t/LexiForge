"""Concurrent batch helpers on top of :class:`PrismaClient`.

``PrismaClient`` is synchronous (it shares the ledger/runner call style). This
module adds bounded-concurrency batching for jobs and transcript fetches
without duplicating the HTTP layer: every call is delegated through
``asyncio.to_thread`` so retries, typed errors and response validation stay in
one place.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from lexiforge.api.models import BatchJobConfig, Transcript
from lexiforge.api.prisma import PrismaClient

__all__ = ["AsyncPrismaClient"]


class AsyncPrismaClient:
    """Bounded-concurrency front end for :class:`PrismaClient`."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        max_concurrent: int = 10,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.client = PrismaClient(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def __aenter__(self) -> "AsyncPrismaClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.client.aclose()

    async def create_job_batch(
        self,
        file_batches: List[List[Union[str, Path]]],
        configs: Optional[List[Optional[Union[BatchJobConfig, Dict[str, Any]]]]] = None,
    ) -> List[str]:
        """Create several jobs concurrently, preserving input order."""
        if configs is None:
            configs = [None] * len(file_batches)
        if len(configs) != len(file_batches):
            raise ValueError("configs and file_batches must be the same length")

        async def create_one(files, config):
            async with self._semaphore:
                return await asyncio.to_thread(self.client.create_job, files, config)

        return list(
            await asyncio.gather(
                *(create_one(f, c) for f, c in zip(file_batches, configs))
            )
        )

    async def fetch_all_transcripts(
        self, job_ids: List[str]
    ) -> Dict[str, Dict[str, Transcript]]:
        """Fetch every completed transcript for every job id."""

        async def fetch_job(job_id: str):
            async with self._semaphore:
                entries = await asyncio.to_thread(self.client.list_files, job_id)
                out: Dict[str, Transcript] = {}
                for entry in entries:
                    if not entry.transcript_url:
                        continue
                    transcript = await asyncio.to_thread(
                        self.client.fetch_transcript, entry.transcript_url
                    )
                    out[entry.file_id] = transcript
                return job_id, out

        results = await asyncio.gather(*(fetch_job(j) for j in job_ids))
        return dict(results)
