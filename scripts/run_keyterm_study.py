"""Run the four-arm pilot across a manifest of real calls and aggregate.

The manifest is the real-audio intake format for the Gnani POC:

    {
      "study_id": "gnani-bfsi-pilot",
      "calls": [
        {
          "call_id": "c01",
          "audio": "audio/c01.wav",
          "reference": "refs/c01.txt",
          "call_type": "mandate_fail",
          "utterances": 5
        }
      ]
    }

Each call gets its own report; the study report pools per-call rows so the
paired non-inferiority verdict is computed across calls, not within one call.

Resume (P15, design §6 / §12): a call is skipped only when every arm transcript
it would produce is newer than the call's ``plan.json``. Per-call failures are
isolated — one raising call is logged in ``summary.json["failures"]`` and the
remaining calls still run. Optional arms (``oracle-200``, ``static-head-200``)
are accepted by name; their builders belong to P06/P07 and are never imported
here.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lexiforge.study.manifest import load_manifest  # noqa: E402 - re-exported
from scripts.run_keyterm_pilot import ARM_NAMES, PilotResult, run_pilot  # noqa: E402

__all__ = [
    "StudyResult",
    "EXTRA_ARM_NAMES",
    "STUDY_ARM_NAMES",
    "load_manifest",
    "run_study",
    "main",
]

# ``oracle-200`` (P06) and ``static-head-200`` (P07) are built by their own
# modules; the runner only needs to accept and merge them.
EXTRA_ARM_NAMES = ("oracle-200", "static-head-200")
STUDY_ARM_NAMES = (*ARM_NAMES, *EXTRA_ARM_NAMES)

TRANSCRIPT_SUFFIX = ".transcript.json"


@dataclass
class StudyResult:
    dry_run: bool
    call_results: list[PilotResult] = field(default_factory=list)
    report_markdown: str = ""
    report_path: Path | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    failed_calls: list[str] = field(default_factory=list)
    skipped_calls: list[str] = field(default_factory=list)


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest field '{field_name}' must be a non-empty string")
    return value.strip()


def _resolve_path(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def _reference_text(call: Mapping[str, Any]) -> str:
    inline = call.get("reference_text")
    if isinstance(inline, str) and inline.strip():
        return inline
    path = Path(str(call["reference"]))
    return path.read_text(encoding="utf-8")


def _call_script(call: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "call_type": call.get("call_type") or "general",
        "mismatched_domain": call.get("mismatched_domain"),
        "turns": [{"text": ""} for _ in range(int(call.get("utterances", 1)))],
    }


def _resolve_arms(arms: Any) -> tuple[str, ...]:
    """Validate requested arm names, preserving order and dropping duplicates."""
    if arms is None:
        return tuple(ARM_NAMES)
    if isinstance(arms, str):
        raise ValueError("arms must be a sequence of arm names, not a bare string")
    resolved: list[str] = []
    for value in arms:
        name = str(value).strip()
        if name not in STUDY_ARM_NAMES:
            allowed = ", ".join(STUDY_ARM_NAMES)
            raise ValueError(f"unknown arm '{name}'; expected one of: {allowed}")
        if name not in resolved:
            resolved.append(name)
    if not resolved:
        raise ValueError("arms must contain at least one arm")
    return tuple(resolved)


def _accepts_kwarg(fn: Callable[..., Any], name: str) -> bool:
    """True when ``fn`` can take ``name`` (explicitly or via ``**kwargs``)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values()
    )


def _transcript_paths(run_dir: Path, arms: tuple[str, ...]) -> list[Path]:
    return [run_dir / f"{arm}{TRANSCRIPT_SUFFIX}" for arm in arms]


def _is_resumable(run_dir: Path, arms: tuple[str, ...]) -> bool:
    """A call resumes only if every arm transcript is newer than its plan."""
    plan_path = run_dir / "plan.json"
    try:
        plan_stamp = plan_path.stat().st_mtime_ns
    except OSError:
        return False
    for path in _transcript_paths(run_dir, arms):
        try:
            if path.stat().st_mtime_ns <= plan_stamp:
                return False
        except OSError:
            return False
    return True


def _rows_from_transcript(payload: Any) -> Mapping[str, Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise ValueError("transcript must be a JSON object")
    rows = payload.get("rows")
    if isinstance(rows, Mapping):
        return {
            str(key): dict(value)
            for key, value in rows.items()
            if isinstance(value, Mapping)
        }
    text = payload.get("text")
    return {"0": {"text": text if isinstance(text, str) else ""}}


def _resume_call(
    call: Mapping[str, Any],
    glossary: list[dict],
    run_dir: Path,
    arms: tuple[str, ...],
) -> PilotResult:
    """Rebuild a scored call from persisted P01 transcripts, zero network."""
    from scripts.run_keyterm_pilot import _score_arms

    rows_by_arm: dict[str, dict[str, Mapping[str, Any]]] = {}
    arm_terms: dict[str, list[str]] = {}
    for arm in arms:
        path = run_dir / f"{arm}{TRANSCRIPT_SUFFIX}"
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows_by_arm[arm] = dict(_rows_from_transcript(payload))
        config = payload.get("config") if isinstance(payload, Mapping) else None
        terms = config.get("keyterms") if isinstance(config, Mapping) else None
        arm_terms[arm] = [str(term) for term in terms or []]

    scored_arms = _score_arms(
        call=call["call_id"],
        rows_by_arm=rows_by_arm,
        reference_text=_reference_text(call),
        glossary=glossary,
        script=_call_script(call),
    )
    return PilotResult(
        dry_run=False,
        arms=arm_terms,
        rows_by_arm=rows_by_arm,
        scored_arms=scored_arms,
    )


def _failure_record(call_id: str, exc: BaseException) -> dict[str, str]:
    return {
        "call_id": call_id,
        "error": str(exc),
        "error_type": type(exc).__name__,
    }


def _merge_scored_arms(
    results: list[PilotResult], arms: tuple[str, ...] = ARM_NAMES
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for name in arms:
        rows: list[dict[str, Any]] = []
        metrics: dict[str, Any] = {}
        wers: list[float] = []
        for result in results:
            # One call contributes at most one aggregate per arm: pooling
            # happens across calls, never twice inside the same call.
            arm = next(
                (a for a in result.scored_arms if a.get("name") == name), None
            )
            if arm is None:
                continue
            rows.extend(arm.get("rows") or [])
            for key, value in (arm.get("metrics") or {}).items():
                if key == "wer" and isinstance(value, (int, float)):
                    wers.append(float(value))
                elif (
                    isinstance(value, Mapping)
                    and "num" in value
                    and "den" in value
                ):
                    current = metrics.setdefault(key, {"num": 0.0, "den": 0.0})
                    current["num"] += float(value["num"])
                    current["den"] += float(value["den"])
        if wers:
            metrics["wer"] = sum(wers) / len(wers)
        if rows:
            merged[name] = {"name": name, "rows": rows, "metrics": metrics}
    return [merged[name] for name in arms if name in merged]


def run_study(
    manifest: Mapping[str, Any],
    glossary: list[dict],
    *,
    execute: bool = False,
    out_dir: str | Path = "runs",
    arms: list[str] | tuple[str, ...] | None = None,
    resume: bool = True,
    continue_on_error: bool = True,
    budget: int = 200,
    seed: int = 0,
    fmt: str = "transcribe",
    language_code: str = "hi-IN,en-IN",
    poll_timeout: float = 1800,
    client: Any = None,
    validator: Any = None,
    pad_selected: bool = True,
    critical_only: bool = False,
    must_have: list[str] | None = None,
    base_dir: str | Path | None = None,
    run_pilot_fn: Callable[..., PilotResult] = run_pilot,
) -> StudyResult:
    """Run every call in the manifest; dry-run unless ``execute=True``.

    ``resume`` only skips executed calls whose transcripts are newer than their
    plan. ``continue_on_error`` isolates a raising call: it is recorded in
    ``summary["failures"]`` and the remaining calls still run.
    """
    study_id = _require_str(manifest.get("study_id"), "study_id")
    calls = manifest.get("calls")
    if not isinstance(calls, list) or not calls:
        raise ValueError("manifest 'calls' must be a non-empty list")
    resolved_arms = _resolve_arms(arms)

    study_dir = Path(out_dir) / study_id
    study_dir.mkdir(parents=True, exist_ok=True)

    results: list[PilotResult] = []
    observed_calls: list[str] = []
    failed_calls: list[str] = []
    skipped_calls: list[str] = []
    failures: list[dict[str, str]] = []
    base = Path(base_dir) if base_dir is not None else Path.cwd()

    for call in calls:
        call_id = str(call.get("call_id"))
        call_dir = Path(out_dir) / call_id
        local_call = dict(call)
        local_call["audio"] = str(_resolve_path(call["audio"], base))
        if call.get("reference"):
            local_call["reference"] = str(_resolve_path(call["reference"], base))

        if execute and resume and _is_resumable(call_dir, resolved_arms):
            try:
                results.append(_resume_call(local_call, glossary, call_dir, resolved_arms))
                observed_calls.append(call_id)
                skipped_calls.append(call_id)
                continue
            except (OSError, ValueError, KeyError, TypeError, ImportError):
                # Unreadable/partial transcripts must be re-run, never trusted.
                pass

        pilot_kwargs: dict[str, Any] = {
            "execute": execute,
            "client": client,
            "out_dir": out_dir,
            "budget": budget,
            "seed": seed,
            "fmt": fmt,
            "language_code": language_code,
            "poll_timeout": poll_timeout,
            "reference_text": _reference_text(local_call),
            "script": _call_script(local_call),
            "pad_selected": pad_selected,
            "validator": validator,
            "critical_only": critical_only,
            "must_have": local_call.get("must_have") or must_have,
        }
        if _accepts_kwarg(run_pilot_fn, "arms"):
            pilot_kwargs["arms"] = list(resolved_arms)
        try:
            results.append(run_pilot_fn(call_id, local_call["audio"], glossary, **pilot_kwargs))
        except Exception as exc:
            failures.append(_failure_record(call_id, exc))
            failed_calls.append(call_id)
            if not continue_on_error:
                raise
            continue
        observed_calls.append(call_id)

    summary: dict[str, Any] = {
        "study_id": study_id,
        "calls": len(results),
        "dry_run": not execute,
        "failures": failures,
        "skipped": skipped_calls,
    }
    if not execute:
        _write_summary(study_dir / "summary.json", summary)
        return StudyResult(
            dry_run=True,
            call_results=results,
            summary=summary,
            failed_calls=failed_calls,
            skipped_calls=skipped_calls,
        )

    merged_arms = _merge_scored_arms(results, resolved_arms)
    from lexiforge.report.keyterm_health import build_report, render_markdown

    report = build_report(
        call_id=study_id,
        arms=merged_arms,
        provenance={
            "study_id": study_id,
            "calls": observed_calls,
            "format": fmt,
            "language_code": language_code,
            "budget": budget,
            "seed": seed,
        },
        prereg={
            "arms": list(resolved_arms),
            "budget": budget,
            "n_calls": len(observed_calls),
        },
    )
    markdown = render_markdown(report)
    report_path = study_dir / "report.md"
    report_path.write_text(markdown, encoding="utf-8")
    summary.update(
        {
            "verdict": report.get("verdict"),
            # Observed calls only: a planned-but-failed call is not evidence.
            "n_calls": report.get("n_calls") or len(observed_calls),
            "report": str(report_path),
        }
    )
    _write_summary(study_dir / "summary.json", summary)
    return StudyResult(
        dry_run=False,
        call_results=results,
        report_markdown=markdown,
        report_path=report_path,
        summary=summary,
        failed_calls=failed_calls,
        skipped_calls=skipped_calls,
    )


def _write_summary(path: Path, summary: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the four-arm keyterm study over a manifest (dry-run by default)"
    )
    parser.add_argument("manifest", help="Path to the study manifest JSON")
    parser.add_argument("--glossary", default="data/glossary.json")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--out-dir", default="runs")
    parser.add_argument("--budget", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--format", dest="fmt", default="transcribe")
    parser.add_argument("--language-code", default="hi-IN,en-IN")
    parser.add_argument(
        "--selected-natural",
        action="store_true",
        help="Do not pad the selected arm to the full budget",
    )
    parser.add_argument(
        "--rest",
        action="store_true",
        help="Use synchronous REST STT instead of the Batch API",
    )
    parser.add_argument(
        "--critical-only",
        action="store_true",
        help="Select only fictional/brand and must-have terms",
    )
    args = parser.parse_args(argv)

    from lexiforge.cli import _load_dotenv

    _load_dotenv()
    client = None
    validator = None
    if args.rest:
        from lexiforge.api.rest_stt import RestSttClient

        client = RestSttClient()
        from lexiforge.api.gnani_v3 import validate_rest_config

        validator = validate_rest_config

    manifest = load_manifest(args.manifest)
    glossary = json.loads(Path(args.glossary).read_text(encoding="utf-8"))
    if isinstance(glossary, dict):
        glossary = glossary.get("terms") or glossary.get("glossary_terms") or []
    result = run_study(
        manifest,
        glossary,
        execute=args.execute,
        out_dir=args.out_dir,
        budget=args.budget,
        seed=args.seed,
        fmt=args.fmt,
        language_code=args.language_code,
        pad_selected=not args.selected_natural,
        client=client,
        validator=validator,
        critical_only=args.critical_only,
        base_dir=Path(args.manifest).parent,
    )
    if result.dry_run:
        print(f"Dry run for {manifest['study_id']}: {len(result.call_results)} call plans")
    else:
        print(
            f"Study {manifest['study_id']}: {result.summary.get('calls')} calls, "
            f"verdict {result.summary.get('verdict')}, report {result.report_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
