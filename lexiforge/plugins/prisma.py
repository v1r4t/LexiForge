"""Gnani Prisma backend plugin.

Implements the interface :class:`lexiforge.runner.Runner` calls:

``create_job(files=, context=, condition=)`` -> ``{"job_id": ...}``
``get_job_status(job_id)`` -> ``{"status": ...}``
``get_results(job_id)`` -> ``[{file_id, name, transcript_url, ...}]``
``download_transcript(job_id, file_info)`` -> transcript dict

The runner does not know about Prisma's create/start split, so ``create_job``
creates *and* starts the remote job, and ``get_results`` waits for the job to
reach a terminal state before listing files. Without the wait the runner would
poll a job that is still queued and record every file as missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from lexiforge.api.models import BatchJobConfig
from lexiforge.api.prisma import PrismaClient
from lexiforge.plugins.base import ASRBackend, BackendConfig
from lexiforge.plugins.registry import get_registry

__all__ = ["PrismaBackend"]

_TERMINAL = {"COMPLETED", "PARTIAL_FAILURE", "FAILED", "START_FAILED", "CANCELLED"}


class PrismaBackend(ASRBackend):
    """Gnani Prisma v3.0 backend."""

    def __init__(self, config: BackendConfig) -> None:
        super().__init__(config)
        self.client = PrismaClient(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )
        self.timeout = float(config.extra.get("job_timeout_s", 1800))
        self.poll_interval = float(config.extra.get("poll_interval_s", 15.0))

    @property
    def name(self) -> str:
        return "prisma"

    @property
    def supported_formats(self) -> List[str]:
        return ["wav", "mp3", "flac", "m4a", "ogg"]

    # -- runner-facing interface -----------------------------------------
    def create_job(
        self,
        files: Union[List[Union[str, Path]], List[Path]],
        config: Optional[Dict[str, Any]] = None,
        context: Optional[List[str]] = None,
        condition: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create and start a batch job; return ``{"job_id": ...}``."""
        job_config: Dict[str, Any] = dict(config or {})
        job_config.setdefault("model", "prisma-v3.0")
        job_config.setdefault("language", "hi")
        if context:
            # The runner's per-call keyterm list is exactly Prisma's context.
            job_config["keyterms"] = list(context)[:200]
        if condition:
            job_config["condition"] = condition

        batch_config = BatchJobConfig.model_validate(job_config)
        job_id = self.client.create_job(files, batch_config)
        self.client.start_job(job_id)
        return {"job_id": job_id, "status": "STARTED"}

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        job = self.client.get_job(job_id)
        return job.model_dump()

    def start_job(self, job_id: str) -> None:
        """Start a previously created job (already done by ``create_job``)."""
        self.client.start_job(job_id)

    def get_results(self, job_id: str) -> List[Dict[str, Any]]:
        """Wait for a terminal status, then list per-file records."""
        status = self.get_job_status(job_id).get("status")
        if isinstance(status, str) and status.upper() not in _TERMINAL:
            final = self.client.wait_for_completion(
                job_id, timeout=int(self.timeout), poll_interval=self.poll_interval
            )
            status = final.value if hasattr(final, "value") else str(final)
        if isinstance(status, str) and status.upper() in {"FAILED", "START_FAILED", "CANCELLED"}:
            return []
        return [entry.model_dump() for entry in self.client.list_files(job_id)]

    def download_transcript(self, job_id: str, file_info: Dict[str, Any]) -> Any:
        url = file_info.get("transcript_url")
        if not url:
            raise ValueError("file record has no transcript_url")
        return self.client.fetch_transcript(str(url)).model_dump()

    def close(self) -> None:
        self.client.close()


# Register the backend under the names callers actually use.
for _alias in ("prisma", "gnani", "vachana"):
    get_registry().register(_alias, PrismaBackend)
