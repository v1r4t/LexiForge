"""Tests for the validated real-audio study manifest (P14).

Schema is defined in ``lexiforge.study.manifest`` and documented in
``docs/real-audio-intake.md``. PREPARE-ONLY: no human audio is exercised.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lexiforge.study import ManifestError, load_manifest, validate_manifest


def _call(**overrides):
    call = {
        "call_id": "c01",
        "audio": "audio/c01.wav",
        "reference": "refs/c01.txt",
        "call_type": "mandate_fail",
        "utterances": 5,
        "mismatched_domain": "upi_failed",
        "must_have": ["UPI", "NEFT"],
    }
    call.update(overrides)
    return call


def _write(tmp_path: Path, payload) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _payload(calls=None, **overrides):
    payload = {"study_id": "gnani-bfsi-pilot", "calls": calls or [_call()]}
    payload.update(overrides)
    return payload


def test_load_manifest_matches_legacy_loader_output(tmp_path):
    path = _write(tmp_path, _payload())

    assert load_manifest(path) == {
        "study_id": "gnani-bfsi-pilot",
        "calls": [
            {
                "call_id": "c01",
                "audio": "audio/c01.wav",
                "reference": "refs/c01.txt",
                "reference_text": None,
                "call_type": "mandate_fail",
                "mismatched_domain": "upi_failed",
                "utterances": 5,
                "must_have": ["UPI", "NEFT"],
            }
        ],
    }


def test_legacy_defaults_are_preserved(tmp_path):
    path = _write(
        tmp_path,
        _payload(
            calls=[
                {
                    "call_id": "c02",
                    "audio": "audio/c02.wav",
                    "reference_text": "mera UPI fail hua",
                }
            ]
        ),
    )

    call = load_manifest(path)["calls"][0]
    assert call["call_type"] == "general"
    assert call["mismatched_domain"] is None
    assert call["utterances"] == 1
    assert call["must_have"] == []
    assert call["reference"] is None


def test_both_reference_forms_are_rejected(tmp_path):
    path = _write(
        tmp_path,
        _payload(calls=[_call(reference_text="mera UPI fail hua")]),
    )

    with pytest.raises(ManifestError, match="exactly one of 'reference' or 'reference_text'"):
        load_manifest(path)


def test_neither_reference_form_is_rejected(tmp_path):
    call = _call()
    del call["reference"]
    path = _write(tmp_path, _payload(calls=[call]))

    with pytest.raises(ManifestError, match="exactly one of 'reference' or 'reference_text'"):
        load_manifest(path)


def test_empty_reference_string_counts_as_absent(tmp_path):
    path = _write(
        tmp_path,
        _payload(calls=[_call(reference="", reference_text="mera UPI fail hua")]),
    )

    call = load_manifest(path)["calls"][0]
    assert call["reference"] is None
    assert call["reference_text"] == "mera UPI fail hua"


def test_duplicate_call_id_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        _payload(
            calls=[
                _call(),
                _call(reference_text="mera NEFT fail hua"),
            ]
        ),
    )

    with pytest.raises(ManifestError, match="duplicate call_id 'c01'"):
        load_manifest(path)


def test_unknown_key_is_rejected(tmp_path):
    path = _write(tmp_path, _payload(notes="not part of the schema"))
    with pytest.raises(ManifestError, match="unknown manifest field 'notes'"):
        load_manifest(path)

    path = _write(tmp_path, _payload(calls=[_call(turns=5)]))
    with pytest.raises(ManifestError, match="calls\\[0\\] has unknown field 'turns'"):
        load_manifest(path)


def test_must_have_is_normalized_to_list_of_strings(tmp_path):
    path = _write(
        tmp_path,
        _payload(calls=[_call(must_have=["UPI", "NEFT"])]),
    )
    assert load_manifest(path)["calls"][0]["must_have"] == ["UPI", "NEFT"]

    path = _write(tmp_path, _payload(calls=[_call(must_have=["UPI", 3])]))
    with pytest.raises(ManifestError, match="must_have"):
        load_manifest(path)


def test_optional_consent_and_pii_fields_are_carried(tmp_path):
    path = _write(
        tmp_path,
        _payload(
            calls=[
                _call(consent_ref="consent/c01.pdf", pii_status="redacted"),
            ]
        ),
    )

    call = load_manifest(path)["calls"][0]
    assert call["consent_ref"] == "consent/c01.pdf"
    assert call["pii_status"] == "redacted"


def test_validate_manifest_returns_all_errors_without_raising():
    errors = validate_manifest(
        {
            "study_id": "",
            "extra": True,
            "calls": [
                {"call_id": "c01", "audio": "", "utterances": 0},
                {"call_id": "c01", "audio": "a.wav", "reference_text": "x"},
            ],
        }
    )

    assert isinstance(errors, list)
    assert any("study_id" in error for error in errors)
    assert any("unknown manifest field 'extra'" in error for error in errors)
    assert any("calls[0].audio" in error for error in errors)
    assert any("calls[0] must have exactly one of" in error for error in errors)
    assert any("calls[0].utterances must be >= 1" in error for error in errors)
    assert any("duplicate call_id 'c01'" in error for error in errors)


def test_validate_manifest_accepts_a_valid_manifest():
    assert validate_manifest(_payload()) == []


def test_manifest_error_is_a_value_error():
    assert issubclass(ManifestError, ValueError)


def test_invalid_json_and_non_object_are_manifest_errors(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError, match="valid JSON"):
        load_manifest(path)

    path = _write(tmp_path, [])
    with pytest.raises(ManifestError, match="JSON object"):
        load_manifest(path)


def test_unicode_reference_round_trips(tmp_path):
    text = "मेरा UPI fail हुआ, NEFT नहीं गया"
    call = _call(reference_text=text)
    del call["reference"]
    path = _write(tmp_path, _payload(calls=[call]))

    assert load_manifest(path)["calls"][0]["reference_text"] == text
