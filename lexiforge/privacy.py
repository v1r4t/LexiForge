"""Redaction for anything that leaves the harness.

Transcripts are recorded under consent that covers the experiment, not
publication of a customer's account number. The dashboard export is the point
where text becomes shareable, so redaction lives here and is applied there.

Deliberately digit-shaped only: glossary terms (``NEFT``, ``UPI``, ``IFSC``),
amounts below nine digits, and Devanagari words are never touched. Masks are
stable per document so repeated values remain comparable.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Pattern, Tuple

__all__ = ["MASK_EMAIL", "MASK_NUMBER", "redact_object", "redact_text"]

MASK_EMAIL = "[EMAIL]"
MASK_NUMBER = "[NUMBER]"

# Ordered longest-first: a 16-digit card must not be eaten by the generic
# account rule, and a 12-digit Aadhaar must not be read as a phone number.
_EMAIL_RE: Pattern[str] = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

_PATTERNS: Tuple[Tuple[Pattern[str], str], ...] = (
    # Card numbers: 16 digits, optionally separated (4111 1111 1111 1111).
    (re.compile(r"\b(?:\d[ -]?){15}\d\b"), "[CARD]"),
    # Indian mobile, optionally +91-prefixed and space/dash separated.
    (re.compile(r"(?:(?<![\d])\+?91[ -]?)?(?<![\d])[6-9]\d{4}[ -]?\d{5}(?![\d])"), "[PHONE]"),
    # Aadhaar: 12 digits, contiguous or grouped 4-4-4.
    (re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}\b|\b\d{12}\b"), "[AADHAAR]"),
    # Any remaining long digit run is an account number.
    (re.compile(r"\b\d{9,18}\b"), MASK_NUMBER),
)

# Devanagari digits are normalised first so a number typed in either script is
# caught by the same rules.
_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def redact_text(text: str) -> Tuple[str, Dict[str, int]]:
    """Return ``(redacted, counts)`` for a single string."""
    if not text:
        return text, {}

    counts: Dict[str, int] = {}

    def _bump(mask: str) -> None:
        counts[mask] = counts.get(mask, 0) + 1

    original = text
    text = text.translate(_DEVA_DIGITS)

    def _sub_email(match: re.Match) -> str:
        _bump(MASK_EMAIL)
        return MASK_EMAIL

    text = _EMAIL_RE.sub(_sub_email, text)

    for pattern, mask in _PATTERNS:
        def _sub(match: re.Match, mask: str = mask) -> str:
            _bump(mask)
            return mask

        text = pattern.sub(_sub, text)

    # Restore ASCII shape only when nothing was masked, so untouched text keeps
    # its original Devanagari digits.
    if not counts:
        return original, {}
    return text, counts


def redact_object(obj: Any) -> Tuple[Any, Dict[str, int]]:
    """Recursively redact every string in a JSON-like structure."""
    totals: Dict[str, int] = {}

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            redacted, counts = redact_text(value)
            for key, count in counts.items():
                totals[key] = totals.get(key, 0) + count
            return redacted
        if isinstance(value, dict):
            return {key: _walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_walk(item) for item in value]
        return value

    return _walk(obj), totals
