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
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from scripts.run_keyterm_pilot import ARM_NAMES, PilotResult, run_pilot

__all__ = ["StudyResult", "load_manifest", "run_study", "main"]


@dataclass
class StudyResult:
    dry_run: bool
    call_results: list[PilotResult] = field(default_factory=list)
    report_markdown: str = ""
    report_path: Path | None = None
    summary: dict[str, Any] = field(default_factory=dict)


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest field '{field_name}' must be a non-empty string")
    return value.strip()


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load and validate the real-audio intake manifest."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    study_id = _require_str(data.get("study_id"), "study_id")
    calls = data.get("calls")
    if not isinstance(calls, list) or not calls:
        raise ValueError("manifest 'calls' must be a non-empty list")

    normalized: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            raise ValueError(f"calls[{index}] must be an object")
        call_id = _require_str(call.get("call_id"), f"calls[{index}].call_id")
        audio = _require_str(call.get("audio"), f"calls[{index}].audio")
        reference = call.get("reference")
        reference_text = call.get("reference_text")
        if not reference and not reference_text:
            raise ValueError(
                f"calls[{index}] needs 'reference' (path) or 'reference_text'"
            )
        try:
            utterances = int(call.get("utterances", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"calls[{index}].utterances must be an integer") from exc
        if utterances < 1:
            raise ValueError(f"calls[{index}].utterances must be >= 1")
        normalized.append(
            {
                "call_id": call_id,
                "audio": audio,
                "reference": reference,
                "reference_text": reference_text,
                "call_type": call.get("call_type") or "general",
                "mismatched_domain": call.get("mismatched_domain"),
                "utterances": utterances,
            }
        )
    return {"study_id": study_id, "calls": normalized}


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


def _merge_scored_arms(results: list[PilotResult]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for name in ARM_NAMES:
        rows: list[dict[str, Any]] = []
        metrics: dict[str, Any] = {}
        wers: list[float] = []
        for result in results:
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
    return [merged[name] for name in ARM_NAMES if name in merged]


def run_study(
    manifest: Mapping[str, Any],
    glossary: list[dict],
    *,
    execute: bool = False,
    out_dir: str | Path = "runs",
    budget: int = 200,
    seed: int = 0,
    fmt: str = "transcribe",
    language_code: str = "hi-IN,en-IN",
    poll_timeout: float = 1800,
    client: Any = None,
    run_pilot_fn: Callable[..., PilotResult] = run_pilot,
) -> StudyResult:
    """Run every call in the manifest; dry-run unless ``execute=True``."""
    study_id = _require_str(manifest.get("study_id"), "study_id")
    calls = manifest.get("calls")
    if not isinstance(calls, list) or not calls:
        raise ValueError("manifest 'calls' must be a non-empty list")

    study_dir = Path(out_dir) / study_id
    study_dir.mkdir(parents=True, exist_ok=True)

    results: list[PilotResult] = []
    for call in calls:
        results.append(
            run_pilot_fn(
                call["call_id"],
                call["audio"],
                glossary,
                execute=execute,
                client=client,
                out_dir=out_dir,
                budget=budget,
                seed=seed,
                fmt=fmt,
                language_code=language_code,
                poll_timeout=poll_timeout,
                reference_text=_reference_text(call),
                script=_call_script(call),
            )
        )

    summary = {
        "study_id": study_id,
        "calls": len(results),
        "dry_run": not execute,
    }
    if not execute:
        (study_dir / "summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        return StudyResult(dry_run=True, call_results=results, summary=summary)

    arms = _merge_scored_arms(results)
    from lexiforge.report.keyterm_health import build_report, render_markdown

    report = build_report(
        call_id=study_id,
        arms=arms,
        provenance={
            "study_id": study_id,
            "calls": [str(c["call_id"]) for c in calls],
            "format": fmt,
            "language_code": language_code,
            "budget": budget,
            "seed": seed,
        },
        prereg={
            "arms": list(ARM_NAMES),
            "budget": budget,
            "n_calls": len(results),
        },
    )
    markdown = render_markdown(report)
    report_path = study_dir / "report.md"
    report_path.write_text(markdown, encoding="utf-8")
    summary.update(
        {
            "verdict": report.get("verdict"),
            "n_calls": report.get("n_calls"),
            "report": str(report_path),
        }
    )
    (study_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return StudyResult(
        dry_run=False,
        call_results=results,
        report_markdown=markdown,
        report_path=report_path,
        summary=summary,
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
    args = parser.parse_args(argv)

    from lexiforge.cli import _load_dotenv

    _load_dotenv()
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
