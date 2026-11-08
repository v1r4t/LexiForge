"""Validate a real-audio study manifest before spending credits.

Checks every call has a readable audio file and a reference transcript, then
reports duration, sample rate, channels and clipping. WAV files are inspected
directly; other formats get a size/existence check and a warning.
"""

from __future__ import annotations

import argparse
import array
import json
import sys
import wave
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_keyterm_study import load_manifest  # noqa: E402

__all__ = ["check_manifest", "main"]


def _resolve(path_value: str, manifest_path: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    for candidate in (Path.cwd() / path, manifest_path.parent / path):
        if candidate.exists():
            return candidate
    return Path.cwd() / path


def _check_audio(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "errors": [],
        "warnings": [],
        "duration_s": None,
        "sample_rate": None,
        "channels": None,
        "clipping_ratio": None,
    }
    if not path.exists():
        report["errors"].append(f"audio not found: {path}")
        return report
    if path.stat().st_size == 0:
        report["errors"].append(f"audio is empty: {path}")
        return report
    if path.suffix.lower() != ".wav":
        report["warnings"].append(
            f"non-WAV audio ({path.suffix}); deep validation skipped"
        )
        return report

    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_rate = handle.getframerate()
            sample_width = handle.getsampwidth()
            frames = handle.getnframes()
            report["channels"] = channels
            report["sample_rate"] = sample_rate
            report["duration_s"] = frames / sample_rate if sample_rate else 0.0
            data = handle.readframes(frames)
    except (wave.Error, OSError) as exc:
        report["errors"].append(f"not a readable WAV: {exc}")
        return report

    if frames == 0:
        report["errors"].append("audio has zero frames")
    if sample_rate and sample_rate < 8000:
        report["warnings"].append(f"sample rate {sample_rate} Hz is below 8 kHz")
    if channels not in (1, 2):
        report["warnings"].append(f"unusual channel count: {channels}")

    if sample_width == 2 and data:
        samples = array.array("h")
        samples.frombytes(data)
        if samples:
            clipped = sum(1 for value in samples if value >= 32767 or value <= -32768)
            ratio = clipped / len(samples)
            report["clipping_ratio"] = ratio
            if ratio > 0.001:
                report["warnings"].append(
                    f"clipping on {ratio * 100:.2f}% of samples"
                )
    return report


def check_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Return ``{ok, errors, warnings, calls}`` for a manifest."""
    path = Path(manifest_path)
    manifest = load_manifest(path)
    errors: list[str] = []
    warnings: list[str] = []
    calls: list[dict[str, Any]] = []

    seen: set[str] = set()
    for call in manifest["calls"]:
        call_id = call["call_id"]
        if call_id in seen:
            errors.append(f"duplicate call_id: {call_id}")
        seen.add(call_id)

        audio = _resolve(call["audio"], path)
        audio_report = _check_audio(audio)
        errors.extend(f"{call_id}: {message}" for message in audio_report["errors"])
        warnings.extend(
            f"{call_id}: {message}" for message in audio_report["warnings"]
        )

        reference = call.get("reference")
        if reference:
            ref_path = _resolve(reference, path)
            if not ref_path.exists():
                errors.append(f"{call_id}: reference not found: {ref_path}")
            elif not ref_path.read_text(encoding="utf-8", errors="ignore").strip():
                errors.append(f"{call_id}: reference is empty: {ref_path}")
        elif not str(call.get("reference_text") or "").strip():
            errors.append(f"{call_id}: no reference transcript")

        calls.append({"call_id": call_id, **audio_report})

    return {
        "ok": not errors,
        "study_id": manifest["study_id"],
        "errors": errors,
        "warnings": warnings,
        "calls": calls,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a real-audio study manifest")
    parser.add_argument("manifest")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    args = parser.parse_args(argv)

    report = check_manifest(args.manifest)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"study: {report['study_id']}")
        print(
            f"{'call':<8} {'duration':>9} {'rate':>7} {'ch':>3} {'clip%':>6}  status"
        )
        for call in report["calls"]:
            duration = call.get("duration_s")
            duration_text = f"{duration:.2f}s" if isinstance(duration, (int, float)) else "n/a"
            rate = call.get("sample_rate") or "n/a"
            channels = call.get("channels") or "n/a"
            clipping = call.get("clipping_ratio")
            clip_text = f"{clipping * 100:.2f}" if isinstance(clipping, float) else "n/a"
            status = "OK" if not call["errors"] else "ERROR"
            print(
                f"{call['call_id']:<8} {duration_text:>9} {str(rate):>7} "
                f"{str(channels):>3} {clip_text:>6}  {status}"
            )
        for message in report["warnings"]:
            print(f"WARN  {message}")
        for message in report["errors"]:
            print(f"ERROR {message}")
        print("OK" if report["ok"] else "FAILED")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
