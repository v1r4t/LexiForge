"""Typed errors for Gnani Timbre TTS client."""


class TTSError(Exception):
    """Base exception for TTS errors."""


class TTSAuthError(TTSError):
    """Authentication/authorization failures (401, 403)."""


class TTSRateLimitError(TTSError):
    """Rate limited (429)."""


class TTSValidationError(TTSError):
    """Validation errors (400, empty text, etc.)."""


class TTSUnavailableError(TTSError):
    """Service unavailable, server errors (5xx), or timeouts."""
