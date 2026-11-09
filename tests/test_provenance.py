"""Tests for report provenance stamps and the claims register (P17)."""

from __future__ import annotations

import hashlib
import json

import pytest

from lexiforge.canon import CANON_VERSION
from lexiforge.report.provenance import (
    MissingProvenance,
    assert_reportable,
    claims_register,
    provenance_block,
    sha256_bytes,
    sha256_text,
)

_GENERATED_AT = "2026-11-09T00:00:00+00:00"


def _block(**overrides):
    kwargs = {
        "model": "gnani-prisma-v3.0",
        "context_hashes": {"selected-200": b"selected context"},
        "seed": 0,
        "audio_hashes": {"c01_t01": b"RIFF audio bytes"},
        "audio_chain": ["wav", "16k", "mono"],
        "format": "transcribe",
        "language_code": "hi-IN,en-IN",
        "generated_at": _GENERATED_AT,
        "study_id": "poc-2026",
    }
    kwargs.update(overrides)
    return provenance_block(**kwargs)


def test_canon_version_defaults_from_canon_and_can_be_overridden() -> None:
    block = _block()
    assert block["canon_version"] == CANON_VERSION
    assert _block(canon_version="matcher-v9.9")["canon_version"] == "matcher-v9.9"


def test_hashes_are_sha256_hex_and_stable() -> None:
    expected = hashlib.sha256(b"RIFF audio bytes").hexdigest()
    block = _block()
    assert block["audio_hashes"] == {"c01_t01": expected}
    assert _block() == block
    assert sha256_bytes(b"abc") == hashlib.sha256(b"abc").hexdigest()
    assert sha256_text("नमस्ते") == hashlib.sha256("नमस्ते".encode("utf-8")).hexdigest()


def test_precomputed_hex_digests_are_preserved_lowercase() -> None:
    digest = hashlib.sha256(b"audio").hexdigest()
    block = _block(context_hashes={"selected": digest.upper()})
    assert block["context_hashes"] == {"selected": digest}


def test_keys_are_sorted_and_optional_fields_are_omitted() -> None:
    block = _block(study_id=None)
    assert list(block) == sorted(block)
    assert "study_id" not in block
    assert block["generated_at"] == _GENERATED_AT
    assert block["seed"] == 0


def test_generated_at_is_injectable_and_never_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GNANI_API_KEY", "sk-do-not-leak")
    block = _block(generated_at="2026-01-02T03:04:05+00:00")
    assert block["generated_at"] == "2026-01-02T03:04:05+00:00"
    payload = json.dumps(block, ensure_ascii=False)
    assert "sk-do-not-leak" not in payload
    assert "GNANI_API_KEY" not in payload


def test_output_never_contains_absolute_paths() -> None:
    block = _block(
        context_hashes={"selected-200": r"C:\Users\analyst\runs\context.json"},
        audio_hashes={"c01": "/home/analyst/audio/c01.wav"},
    )
    payload = json.dumps(block, ensure_ascii=False)
    assert "C:\\Users" not in payload
    assert "analyst" not in payload
    assert "/home/" not in payload


def test_assert_reportable_accepts_a_complete_block() -> None:
    assert assert_reportable(_block()) is None


def test_assert_reportable_rejects_missing_canon_version() -> None:
    block = _block()
    block.pop("canon_version")
    with pytest.raises(MissingProvenance) as excinfo:
        assert_reportable(block)
    assert "canon_version" in str(excinfo.value)


def test_assert_reportable_rejects_missing_context_hash() -> None:
    with pytest.raises(MissingProvenance) as excinfo:
        assert_reportable(_block(context_hashes={}))
    assert "context" in str(excinfo.value).lower()


def test_assert_reportable_rejects_blank_values() -> None:
    with pytest.raises(MissingProvenance):
        assert_reportable(_block(canon_version="  "))
    with pytest.raises(MissingProvenance):
        assert_reportable(_block(context_hashes={"selected": ""}))
    with pytest.raises(MissingProvenance):
        assert_reportable({"canon_version": CANON_VERSION})


def test_claims_register_carries_text_and_basis_in_every_category() -> None:
    register = claims_register(
        verified=[{"text": "608 tests pass", "basis": "pytest run on main"}],
        inferred=[{"text": "cost is not a constraint", "basis": "design §10 billing math"}],
        unverified=[{"text": "lift on real calls", "basis": "no pass-2 audio yet"}],
    )
    assert set(register) == {"verified", "inferred", "unverified"}
    assert register["verified"] == [
        {"basis": "pytest run on main", "text": "608 tests pass"}
    ]
    assert register["inferred"][0]["basis"] == "design §10 billing math"


def test_claims_register_rejects_claims_without_basis() -> None:
    with pytest.raises(ValueError):
        claims_register(unverified=[{"text": "a claim without evidence"}])
    with pytest.raises(ValueError):
        claims_register(verified=["plain string has no basis"])
    with pytest.raises(ValueError):
        claims_register(verified=[{"text": "  ", "basis": "x"}])


def test_claims_register_is_deterministic_and_preserves_unicode_and_extra_fields() -> None:
    entries = [
        {"text": "बैंक शब्द सही मिले", "basis": "manual audit", "source": "c04"},
        {"text": "alpha", "basis": "fixture"},
    ]
    forward = claims_register(verified=entries)
    backward = claims_register(verified=list(reversed(entries)))
    assert forward == backward
    assert forward["verified"][1]["text"] == "बैंक शब्द सही मिले"
    assert forward["verified"][1]["source"] == "c04"
    assert list(forward["verified"][0]) == sorted(forward["verified"][0])


def test_claims_register_empty_categories_are_present() -> None:
    register = claims_register()
    assert register == {"inferred": [], "unverified": [], "verified": []}
