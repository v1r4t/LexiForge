"""Batch STT API client (Gnani Prisma v3.0 batch endpoints)."""

from lexiforge.api.async_client import AsyncPrismaClient
from lexiforge.api.client import (
    BATCH_PREFIX,
    MAX_FILE_BYTES,
    MAX_FILES_PER_JOB,
    TERMINAL_STATUSES,
    BatchApiError,
    BatchClient,
    Settings,
)
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
    TranscriptFetchError,
)
from lexiforge.api.models import (
    ApiInfo,
    BatchJob,
    BatchJobConfig,
    FileEntry,
    JobStatus,
    Transcript,
    Word,
)
from lexiforge.api.prisma import PrismaClient, create_client

__all__ = [
    "BATCH_PREFIX",
    "MAX_FILE_BYTES",
    "MAX_FILES_PER_JOB",
    "TERMINAL_STATUSES",
    "BatchApiError",
    "BatchClient",
    "Settings",
    "PrismaClient",
    "create_client",
    "AsyncPrismaClient",
    "BatchJob",
    "BatchJobConfig",
    "FileEntry",
    "JobStatus",
    "Transcript",
    "Word",
    "ApiInfo",
    "PrismaError",
    "PrismaAuthError",
    "PrismaRateLimitError",
    "PrismaValidationError",
    "PrismaNotFoundError",
    "PrismaServerError",
    "PrismaTimeoutError",
    "PrismaNetworkError",
    "JobCreationError",
    "TranscriptFetchError",
    "InvalidAudioError",
]
