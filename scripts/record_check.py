"""Validate a real-audio study manifest before spending credits.

Checks every call has a readable audio file and a reference transcript, then
reports duration, sample rate, channels, clipping, DC offset and silence for
PCM WAV files (8/16/24/32-bit). Other formats get a size/existence check and a
warning. Duration/rate/clipping bounds are QC heuristics, not evidence that
audio was recorded or that any study claim holds -- this task is PREPARE-ONLY.

See ``docs/real-audio-intake.md`` and the P13 hardening spec.
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_keyterm_study import load_manifest  # noqa: E402

__all__ = ["check_manifest", "main"]

DURATION_MIN_S = 8.0
DURATION_MAX_S = 60.0
MIN_SAMPLE_RATE = 8000
CLIPPING_WARN_RATIO = 0.001
SILENCE_THRESHOLD_RATIO = 0.01
SILENT_RATIO = 0.999


def _resolve(path_value: str, manifest_path: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    for candidate in (Path.cwd() / path, manifest_path.parent / path):
        if candidate.exists():
            return candidate
    return Path.cwd() / path


def _pcm_samples(data: bytes, sample_width: int) -> Iterator[int]:
    """Yield signed PCM samples without host-endian ``array("h")`` assumptions."""
    if sample_width == 1:
        for value in data:
            yield value - 128
        return
    for offset in range(0, len(data) - sample_width + 1, sample_width):
        yield int.from_bytes(data[offset : offset + sample_width], "little", signed=True)


def _pcm_metrics(data: bytes, sample_width: int) -> dict[str, float] | None:
    full_scale = 1 << (8 * sample_width - 1)
    silence_threshold = full_scale * SILENCE_THRESHOLD_RATIO
    total = 0
    clipped = 0
    silent = 0
    value_sum = 0
    for value in _pcm_samples(data, sample_width):
        total += 1
        value_sum += value
        if abs(value) >= full_scale - 1:
            clipped += 1
        if abs(value) < silence_threshold:
            silent += 1
    if total == 0:
        return None
    return {
        "clipping_ratio": clipped / total,
        "dc_offset": value_sum / total / full_scale,
        "silence_ratio": silent / total,
    }


def _check_audio(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "errors": [],
        "warnings": [],
        "duration_s": None,
        "sample_rate": None,
        "channels": None,
        "clipping_ratio": None,
        "dc_offset": None,
        "silence_ratio": None,
    }
    if not path.exists():
        report["errors"].append(f"audio not found: {path}")
        return report
    if path.stat().st_size == 0:
        report["errors"].append(f"audio is empty: {path}")
        return report
    if path.suffix.lower() != ".wav":
        report["warnings"].append(f"non-WAV audio ({path.suffix}); deep validation skipped")
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
    elif report["duration_s"] < DURATION_MIN_S or report["duration_s"] > DURATION_MAX_S:
        report["warnings"].append(f"duration {report['duration_s']:.2f} s outside 8-60 s")
    if sample_rate and sample_rate < MIN_SAMPLE_RATE:
        report["warnings"].append(f"sample rate {sample_rate} Hz is below 8 kHz")
    if channels not in (1, 2):
        report["warnings"].append(f"unusual channel count: {channels}")

    if sample_width not in (1, 2, 3, 4):
        report["warnings"].append(
            f"unsupported sample width {sample_width} bytes; deep audio checks skipped"
        )
        return report

    metrics = _pcm_metrics(data, sample_width)
    if metrics is None:
        report["errors"].append("audio has no samples")
        return report
    report.update(metrics)

    if report["silence_ratio"] >= SILENT_RATIO:
        report["errors"].append("audio is silent")
    if report["clipping_ratio"] > CLIPPING_WARN_RATIO:
        report["warnings"].append(f"clipping on {report['clipping_ratio'] * 100:.2f}% of samples")
    return report


def check_manifest(manifest_path: str | Path, *, strict: bool = False) -> dict[str, Any]:
    """Return ``{ok, study_id, errors, warnings, calls}`` for a manifest.

    ``strict=True`` treats QC warnings (duration, sample rate, clipping,
    non-WAV deep checks) as failures without moving them into ``errors``.
    """
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
        warnings.extend(f"{call_id}: {message}" for message in audio_report["warnings"])

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
        "ok": not errors and not (strict and warnings),
        "study_id": manifest["study_id"],
        "errors": errors,
        "warnings": warnings,
        "calls": calls,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a real-audio study manifest")
    parser.add_argument("manifest")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat QC warnings (duration, rate, clipping, skipped checks) as failures",
    )
    args = parser.parse_args(argv)

    report = check_manifest(args.manifest, strict=args.strict)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"study: {report['study_id']}")
        print(
            f"{'call':<8} {'duration':>9} {'rate':>7} {'ch':>3} "
            f"{'clip%':>6} {'dc%':>6} {'sil%':>6}  status"
        )
        for call in report["calls"]:
            duration = call.get("duration_s")
            duration_text = f"{duration:.2f}s" if isinstance(duration, (int, float)) else "n/a"
            rate = call.get("sample_rate") or "n/a"
            channels = call.get("channels") or "n/a"
            clipping = call.get("clipping_ratio")
            clip_text = f"{clipping * 100:.2f}" if isinstance(clipping, float) else "n/a"
            dc_offset = call.get("dc_offset")
            dc_text = f"{dc_offset * 100:.2f}" if isinstance(dc_offset, float) else "n/a"
            silence = call.get("silence_ratio")
            silence_text = f"{silence * 100:.2f}" if isinstance(silence, float) else "n/a"
            status = "OK" if not call["errors"] else "ERROR"
            print(
                f"{call['call_id']:<8} {duration_text:>9} {str(rate):>7} "
                f"{str(channels):>3} {clip_text:>6} {dc_text:>6} "
                f"{silence_text:>6}  {status}"
            )
        for message in report["warnings"]:
            print(f"WARN  {message}")
        for message in report["errors"]:
            print(f"ERROR {message}")
        print("OK" if report["ok"] else "FAILED")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
