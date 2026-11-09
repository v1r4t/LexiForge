"""Tests for the recording-pack generator."""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

from scripts.build_recording_pack import DEFAULT_CALLS, build_pack, render_call_sheet
from scripts.record_check import check_manifest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _fixture_scripts(root: Path, count: int = 20) -> Path:
    """Write ``count`` minimal scripts with known, distinct dialogue."""
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        call_id = f"c{index:02d}"
        payload = {
            "call_id": call_id,
            "call_type": "mandate_fail",
            "speakers": ["SP-A", "SP-B"],
            "mismatched_domain": "upi_failed",
            "turns": [
                {"idx": 1, "speaker": "AGT", "text": f"Namaste {call_id} start."},
                {"idx": 2, "speaker": "CUS", "text": f"Ji {call_id} middle."},
                {"idx": 3, "speaker": "AGT", "text": f"Theek hai {call_id} end."},
            ],
            "expected_real": [],
            "expected_fictional": [],
            "oov": [],
            "zero_turns": [1],
        }
        (scripts / f"{call_id}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    return scripts


def _fixture_glossary(tmp_path: Path) -> Path:
    path = tmp_path / "glossary.json"
    path.write_text(
        json.dumps(
            [
                {
                    "term_id": "R0137",
                    "canonical": "BG",
                    "origin": "real",
                    "category": "banking",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def _fixture_pack(tmp_path: Path, count: int = 20) -> Path:
    scripts = _fixture_scripts(tmp_path / "data", count=count)
    build_pack(
        [f"c{index:02d}" for index in range(count)],
        out_dir=tmp_path / "recording",
        glossary_path=_fixture_glossary(tmp_path),
        scripts_dir=scripts,
    )
    return tmp_path / "recording"


def _wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(
        struct.pack("<h", int(2000 * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(int(rate * seconds))
    )
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)
    return path


def _summary(tmp_path: Path, calls=("c00", "c01")):
    return build_pack(
        list(calls),
        out_dir=tmp_path / "recording",
        glossary_path=ROOT / "data" / "glossary.json",
        scripts_dir=ROOT / "data" / "scripts",
    )


def test_builds_sheets_refs_and_manifest(tmp_path):
    summary = _summary(tmp_path)
    out = tmp_path / "recording"

    for call in ("c00", "c01"):
        assert (out / "scripts" / f"{call}.md").exists()
        assert (out / "refs" / f"{call}.txt").read_text(encoding="utf-8").strip()
    assert (out / "README.md").exists()
    assert (out / "consent.md").exists()
    assert (out / "qc-checklist.md").exists()
    assert (out / "sidecar.template.json").exists()

    manifest = json.loads((out / "manifest.template.json").read_text(encoding="utf-8"))
    assert manifest["study_id"] == "gnani-bfsi-recording-1"
    assert [call["call_id"] for call in manifest["calls"]] == ["c00", "c01"]
    assert manifest["calls"][0]["utterances"] == 5
    assert manifest["calls"][0]["reference"].endswith("refs/c00.txt")
    assert summary["calls"] == ["c00", "c01"]


def test_sheet_resolves_known_terms_and_flags_missing_ones(tmp_path):
    _summary(tmp_path)
    out = tmp_path / "recording"
    glossary = {
        entry["term_id"]: entry
        for entry in json.loads(
            (ROOT / "data" / "glossary.json").read_text(encoding="utf-8")
        )
    }

    c01_script = json.loads(
        (ROOT / "data" / "scripts" / "c01.json").read_text(encoding="utf-8")
    )
    c01_term = glossary[c01_script["expected_fictional"][0]]["canonical"]
    c01 = (out / "scripts" / "c01.md").read_text(encoding="utf-8")
    assert "Call c01" in c01
    assert c01_term in c01
    assert "MISSING" not in c01

    c00 = (out / "scripts" / "c00.md").read_text(encoding="utf-8")
    assert "MISSING" not in c00


def test_reference_text_is_the_dialogue(tmp_path):
    _summary(tmp_path)
    script = json.loads(
        (ROOT / "data" / "scripts" / "c00.json").read_text(encoding="utf-8")
    )
    ref = (tmp_path / "recording" / "refs" / "c00.txt").read_text(encoding="utf-8")
    assert script["turns"][0]["text"] in ref
    assert script["turns"][-1]["text"] in ref


def test_render_call_sheet_is_deterministic(tmp_path):
    script = json.loads((ROOT / "data" / "scripts" / "c01.json").read_text(encoding="utf-8"))
    glossary = {
        "F0013": {"canonical": "RuvNivesh", "origin": "fictional", "category": "loans_credit"}
    }
    first = render_call_sheet("c01", script, glossary)
    second = render_call_sheet("c01", script, glossary)
    assert first == second
    assert "| 2 | CUS |" in first


def test_default_pack_targets_twenty_calls():
    assert DEFAULT_CALLS == tuple(f"c{index:02d}" for index in range(20))


def test_one_command_builds_twenty_sheets_refs_and_manifest(tmp_path):
    out = _fixture_pack(tmp_path)

    sheets = sorted(path.stem for path in (out / "scripts").glob("*.md"))
    refs = sorted(path.stem for path in (out / "refs").glob("*.txt"))
    assert len(sheets) == 20
    assert sheets == refs == [f"c{index:02d}" for index in range(20)]

    manifest = json.loads((out / "manifest.template.json").read_text(encoding="utf-8"))
    assert len(manifest["calls"]) == 20
    assert [call["call_id"] for call in manifest["calls"]] == sheets
    assert (out / "consent.md").exists()
    assert (out / "qc-checklist.md").exists()


def test_refs_equal_script_dialogue_text(tmp_path):
    out = _fixture_pack(tmp_path)
    script = json.loads(
        (tmp_path / "data" / "scripts" / "c07.json").read_text(encoding="utf-8")
    )
    expected = " ".join(turn["text"] for turn in script["turns"])
    ref = (out / "refs" / "c07.txt").read_text(encoding="utf-8")
    assert ref == expected


def test_manifest_paths_are_relative_and_forward_slashed(tmp_path):
    out = _fixture_pack(tmp_path)
    manifest = json.loads((out / "manifest.template.json").read_text(encoding="utf-8"))
    for call in manifest["calls"]:
        call_id = call["call_id"]
        assert call["audio"] == f"audio/{call_id}.wav"
        assert call["reference"] == f"refs/{call_id}.txt"
        for value in (call["audio"], call["reference"]):
            assert "\\" not in value
            assert ":" not in value
            assert not Path(value).is_absolute()


def test_manifest_template_passes_check_manifest(tmp_path):
    out = _fixture_pack(tmp_path)
    for index in range(20):
        _wav(out / "audio" / f"c{index:02d}.wav")

    report = check_manifest(out / "manifest.template.json")
    assert report["ok"] is True, report["errors"]
    assert report["study_id"] == "gnani-bfsi-recording-1"
    assert len(report["calls"]) == 20


def test_missing_script_is_reported_not_invented(tmp_path):
    scripts = _fixture_scripts(tmp_path / "data", count=19)
    summary = build_pack(
        [f"c{index:02d}" for index in range(20)],
        out_dir=tmp_path / "recording",
        glossary_path=_fixture_glossary(tmp_path),
        scripts_dir=scripts,
    )

    assert summary["missing_scripts"] == ["c19"]
    sheets = list((tmp_path / "recording" / "scripts").glob("*.md"))
    assert len(sheets) == 19


def test_pack_consent_covers_required_clauses(tmp_path):
    out = _fixture_pack(tmp_path)
    consent = (out / "consent.md").read_text(encoding="utf-8")
    for clause in (
        "Recording",
        "Evaluation",
        "Public demo",
        "Storage",
        "Withdrawal",
        "No PII",
    ):
        assert f"- [ ] {clause}" in consent, clause


def test_redaction_doc_names_every_masked_class():
    doc = (DOCS / "consent-and-redaction.md").read_text(encoding="utf-8")
    for mask in ("[CARD]", "[PHONE]", "[AADHAAR]", "[NUMBER]", "[EMAIL]"):
        assert mask in doc, mask
    lowered = doc.lower()
    assert "aggregate" in lowered
    assert "only" in lowered


def test_recording_protocol_links_pack_and_redaction_docs():
    protocol = (DOCS / "recording-protocol.md").read_text(encoding="utf-8")
    assert "build_recording_pack.py" in protocol
    assert "consent-and-redaction.md" in protocol
    assert "manifest.template.json" in protocol
