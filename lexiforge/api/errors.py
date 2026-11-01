"""Custom exceptions for Prisma API client."""

from __future__ import annotations

from typing import Optional


class PrismaError(Exception):
    """Base exception for Prisma API errors."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class PrismaAuthError(PrismaError):
    """Authentication error."""
    pass


class PrismaRateLimitError(PrismaError):
    """Rate limit exceeded."""
    
    def __init__(self, message: str, retry_after: Optional[int] = None, details: Optional[dict] = None):
        super().__init__(message, details)
        self.retry_after = retry_after


class PrismaValidationError(PrismaError):
    """Request validation error."""
    pass


class PrismaNotFoundError(PrismaError):
    """Resource not found."""
    pass


class PrismaServerError(PrismaError):
    """Server error."""
    pass


class PrismaTimeoutError(PrismaError):
    """Request timeout."""
    pass


class PrismaNetworkError(PrismaError):
    """Network/connectivity error."""
    pass


class PrismaQuotaExceededError(PrismaError):
    """Quota/credit exceeded."""
    pass


class JobCreationError(PrismaError):
    """Error creating batch job."""
    pass


class TranscriptFetchError(PrismaError):
    """Error fetching transcript."""
    pass


class InvalidAudioError(PrismaError):
    """Invalid audio file."""
    pass
