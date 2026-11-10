"""Validated real-audio study manifest.

Schema design: ``docs/design.md`` §12 (Keyterm Health POC) and PR P14.
Intake documentation: ``docs/real-audio-intake.md``.

The manifest is the contract between a customer's recording pack and the
study runner. Validation is strict on shape (unknown keys are rejected,
duplicate ``call_id`` values are rejected) but preserves the loader's
historical defaults so existing manifests keep their output.

PREPARE-ONLY: schema code only; no human audio is validated here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["ManifestError", "load_manifest", "validate_manifest"]

MANIFEST_FIELDS = frozenset({"study_id", "calls"})

CALL_FIELDS = frozenset(
    {
        "call_id",
        "audio",
        "reference",
        "reference_text",
        "call_type",
        "utterances",
        "mismatched_domain",
        "must_have",
        "expected_terms",
        "consent_ref",
        "pii_status",
    }
)


class ManifestError(ValueError):
    """Raised when a study manifest fails schema validation."""


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_call(call: Any, index: int, seen: dict[str, int]) -> list[str]:
    prefix = f"calls[{index}]"
    if not isinstance(call, dict):
        return [f"{prefix} must be an object"]

    errors = [f"{prefix} has unknown field '{key}'" for key in sorted(set(call) - CALL_FIELDS)]

    call_id = call.get("call_id")
    if not _is_text(call_id):
        errors.append(f"{prefix}.call_id must be a non-empty string")
    else:
        call_id = call_id.strip()
        if call_id in seen:
            errors.append(
                f"duplicate call_id '{call_id}' in calls[{seen[call_id]}] and {prefix}"
            )
        else:
            seen[call_id] = index

    if not _is_text(call.get("audio")):
        errors.append(f"{prefix}.audio must be a non-empty string")

    reference = call.get("reference")
    reference_text = call.get("reference_text")
    if reference is not None and not isinstance(reference, str):
        errors.append(f"{prefix}.reference must be a string")
    if reference_text is not None and not isinstance(reference_text, str):
        errors.append(f"{prefix}.reference_text must be a string")
    has_reference = isinstance(reference, str) and bool(reference.strip())
    has_reference_text = isinstance(reference_text, str) and bool(reference_text.strip())
    if has_reference == has_reference_text:
        errors.append(
            f"{prefix} must have exactly one of 'reference' or 'reference_text'"
        )

    try:
        utterances = int(call.get("utterances", 1))
    except (TypeError, ValueError):
        errors.append(f"{prefix}.utterances must be an integer")
    else:
        if utterances < 1:
            errors.append(f"{prefix}.utterances must be >= 1")

    call_type = call.get("call_type")
    if call_type is not None and not isinstance(call_type, str):
        errors.append(f"{prefix}.call_type must be a string")

    mismatched_domain = call.get("mismatched_domain")
    if mismatched_domain is not None and not isinstance(mismatched_domain, str):
        errors.append(f"{prefix}.mismatched_domain must be a string")

    for key in ("must_have", "expected_terms"):
        values = call.get(key)
        if values is not None:
            if not isinstance(values, list):
                errors.append(f"{prefix}.{key} must be a list of strings")
            else:
                for item_index, item in enumerate(values):
                    if not _is_text(item):
                        errors.append(
                            f"{prefix}.{key}[{item_index}] must be a non-empty string"
                        )

    for key in ("consent_ref", "pii_status"):
        value = call.get(key)
        if value is not None and not _is_text(value):
            errors.append(f"{prefix}.{key} must be a non-empty string")

    return errors


def validate_manifest(data: Any) -> list[str]:
    """Return every schema error in ``data``; an empty list means valid."""
    if not isinstance(data, dict):
        return ["manifest must be a JSON object"]

    errors = [
        f"unknown manifest field '{key}'" for key in sorted(set(data) - MANIFEST_FIELDS)
    ]

    if not _is_text(data.get("study_id")):
        errors.append("manifest field 'study_id' must be a non-empty string")

    calls = data.get("calls")
    if not isinstance(calls, list) or not calls:
        errors.append("manifest 'calls' must be a non-empty list")
        return errors

    seen: dict[str, int] = {}
    for index, call in enumerate(calls):
        errors.extend(_validate_call(call, index, seen))
    return errors


def _normalize_call(call: dict[str, Any]) -> dict[str, Any]:
    reference = call.get("reference")
    reference_text = call.get("reference_text")
    normalized: dict[str, Any] = {
        "call_id": str(call["call_id"]).strip(),
        "audio": str(call["audio"]).strip(),
        "reference": reference if reference else None,
        "reference_text": reference_text if reference_text else None,
        "call_type": call.get("call_type") or "general",
        "mismatched_domain": call.get("mismatched_domain"),
        "utterances": int(call.get("utterances", 1)),
        "must_have": [str(item) for item in (call.get("must_have") or [])],
        "expected_terms": [
            str(item) for item in (call.get("expected_terms") or [])
        ],
    }
    for key in ("consent_ref", "pii_status"):
        value = call.get(key)
        if value is not None:
            normalized[key] = str(value).strip()
    return normalized


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load, validate and normalize a real-audio intake manifest."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc

    errors = validate_manifest(data)
    if errors:
        raise ManifestError("invalid manifest: " + "; ".join(errors))

    return {
        "study_id": str(data["study_id"]).strip(),
        "calls": [_normalize_call(call) for call in data["calls"]],
    }
