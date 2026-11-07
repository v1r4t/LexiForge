"""Gnani Timbre TTS client."""

from .client import SYNTHESIZE_PATH, TimbreClient, TTSResult
from .errors import (
    TTSAuthError,
    TTSError,
    TTSRateLimitError,
    TTSUnavailableError,
    TTSValidationError,
)

__all__ = [
    "SYNTHESIZE_PATH",
    "TimbreClient",
    "TTSResult",
    "TTSAuthError",
    "TTSRateLimitError",
    "TTSError",
    "TTSUnavailableError",
    "TTSValidationError",
]
