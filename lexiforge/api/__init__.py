"""Batch STT API client (Gnani Prisma v3.0 batch endpoints)."""

from lexiforge.api.client import (
    BATCH_PREFIX,
    MAX_FILE_BYTES,
    MAX_FILES_PER_JOB,
    TERMINAL_STATUSES,
    BatchApiError,
    BatchClient,
    Settings,
)

__all__ = [
    "BATCH_PREFIX",
    "MAX_FILE_BYTES",
    "MAX_FILES_PER_JOB",
    "TERMINAL_STATUSES",
    "BatchApiError",
    "BatchClient",
    "Settings",
]
