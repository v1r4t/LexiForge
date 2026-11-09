"""Provenance stamps and the claims register for reportable results.

Design reference: ``docs/design.md`` §7 ("Stamped provenance") requires every
scored output to record the canonicaliser version and the context hash; a recall
figure without that stamp is not reportable. ``docs/preregistration.md`` §9
freezes the verified/inferred/unverified claim ladder, so every claim carries
its basis rather than floating free in a report.

Hashes are computed over bytes. Paths are never embedded in a block: a caller
that supplies a path string gets the digest of that string, not the location.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from lexiforge.canon import CANON_VERSION

__all__ = [
    "MissingProvenance",
    "assert_reportable",
    "claims_register",
    "provenance_block",
    "sha256_bytes",
    "sha256_text",
]

_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_CLAIM_CATEGORIES = ("verified", "inferred", "unverified")


class MissingProvenance(ValueError):
    """Raised when a figure lacks the stamp that makes it reportable."""


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 hex digest of ``data``."""
    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_text(text: str) -> str:
    """Return the SHA-256 hex digest of ``text`` encoded as UTF-8."""
    return sha256_bytes(text.encode("utf-8"))


def _hash_value(value: Any) -> Any:
    """Normalise one hash input to a lowercase SHA-256 hex digest.

    Blank strings are preserved so ``assert_reportable`` can report them as
    missing instead of hashing an empty value into a plausible-looking digest.
    """
    if isinstance(value, str):
        if not value.strip():
            return value
        if _SHA256_HEX.fullmatch(value):
            return value.lower()
        return sha256_text(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return sha256_bytes(bytes(value))
    raise TypeError(f"cannot hash provenance value of type {type(value).__name__}")


def _normalise_hashes(values: Any) -> Any:
    """Return a deterministic mapping or list of SHA-256 hex digests."""
    if isinstance(values, Mapping):
        items = sorted(((str(key), value) for key, value in values.items()), key=lambda kv: kv[0])
        return {key: _hash_value(value) for key, value in items}
    if isinstance(values, (str, bytes, bytearray, memoryview)):
        normalised = _hash_value(values)
        return [normalised] if normalised else []
    digests = [_hash_value(value) for value in values]
    return sorted(digest for digest in digests if digest)


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_HEX.fullmatch(value))


def _has_context_hash(provenance: Mapping[str, Any]) -> bool:
    hashes = provenance.get("context_hashes")
    if isinstance(hashes, Mapping):
        return any(_is_digest(value) for value in hashes.values())
    if isinstance(hashes, (list, tuple)):
        return any(_is_digest(value) for value in hashes)
    if _is_digest(hashes):
        return True
    # Backward-compatible singular spelling used by older report payloads.
    return _is_digest(provenance.get("context_hash"))


def _iso_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.replace(microsecond=0).isoformat()
    return str(value)


def provenance_block(
    *,
    model: str,
    canon_version: str | None = None,
    context_hashes: Any,
    seed: int,
    audio_hashes: Any,
    audio_chain: Iterable[str],
    format: str,
    language_code: str,
    generated_at: Any = None,
    study_id: str | None = None,
) -> dict[str, Any]:
    """Build a provenance block for one scored report.

    ``canon_version`` defaults to :data:`lexiforge.canon.CANON_VERSION` so a
    caller cannot silently omit the matcher identity. ``context_hashes`` and
    ``audio_hashes`` accept bytes, text, precomputed SHA-256 hex digests, or a
    mapping of label to any of those. Keys in the returned block are sorted for
    byte-stable JSON output.
    """
    block: dict[str, Any] = {
        "model": model,
        "canon_version": canon_version or CANON_VERSION,
        "context_hashes": _normalise_hashes(context_hashes),
        "seed": seed,
        "audio_hashes": _normalise_hashes(audio_hashes),
        "audio_chain": list(audio_chain),
        "format": format,
        "language_code": language_code,
        "generated_at": _iso_timestamp(
            generated_at if generated_at is not None else datetime.now(timezone.utc)
        ),
    }
    if study_id is not None:
        block["study_id"] = study_id
    return {key: block[key] for key in sorted(block)}


def assert_reportable(provenance: Mapping[str, Any]) -> None:
    """Raise :class:`MissingProvenance` unless a report is stamp-complete."""
    if not isinstance(provenance, Mapping):
        raise MissingProvenance("provenance must be a mapping with a canon version and context hash")
    missing: list[str] = []
    canon_version = provenance.get("canon_version")
    if not (isinstance(canon_version, str) and canon_version.strip()):
        missing.append("canon_version")
    if not _has_context_hash(provenance):
        missing.append("context_hashes")
    if missing:
        raise MissingProvenance(
            "unreportable provenance: missing " + ", ".join(missing)
        )


def _claim_entries(entries: Iterable[Mapping[str, Any]], *, category: str) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for index, entry in enumerate(entries or ()):
        if not isinstance(entry, Mapping):
            raise ValueError(
                f"{category} claim {index} must be a mapping with 'text' and 'basis'"
            )
        text = entry.get("text")
        basis = entry.get("basis")
        if not (isinstance(text, str) and text.strip()):
            raise ValueError(f"{category} claim {index} needs a non-empty 'text'")
        if not (isinstance(basis, str) and basis.strip()):
            raise ValueError(f"{category} claim {index} needs a non-empty 'basis'")
        normalised.append({key: entry[key] for key in sorted(entry)})
    normalised.sort(key=lambda entry: json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str))
    return normalised


def claims_register(
    *,
    verified: Iterable[Mapping[str, Any]] = (),
    inferred: Iterable[Mapping[str, Any]] = (),
    unverified: Iterable[Mapping[str, Any]] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Build a verified/inferred/unverified register.

    Every entry must be ``{"text": ..., "basis": ...}``; optional extra fields
    are preserved. Entries are sorted so the same inputs always serialise to the
    same bytes. Only verified claims may be stated as fact; inferred entries are
    labelled to-validate by the report template.
    """
    groups = {
        "verified": verified,
        "inferred": inferred,
        "unverified": unverified,
    }
    return {
        category: _claim_entries(groups[category], category=category)
        for category in sorted(_CLAIM_CATEGORIES)
    }
