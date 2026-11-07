"""Dry-run-first orchestrator for the four-arm keyterm pilot.

The default path is a dry run: it builds the four decoding arms, writes
``runs/<call_id>/plan.json`` and performs zero network I/O. Only ``execute=True``
constructs a real :class:`lexiforge.api.client.BatchClient` (and therefore
requires ``GNANI_API_KEY``), creating exactly one job per arm with one file each.

T5 (arms), T7 (validator) and T9 (report) land on parallel branches, so every
dependency is imported lazily and can be injected for tests:

* ``arms_builder`` — ``build_arms`` from ``lexiforge.contexts.arms``;
* ``validator`` — ``validate_batch_config`` from ``lexiforge.api.gnani_v3``;
* ``report_builder`` / ``renderer`` — from ``lexiforge.report.keyterm_health``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

ARM_NAMES = ("baseline", "selected-200", "mismatched-200", "hard-negative-200")

INTERNAL_ONLY_LABEL = (
    "> **INTERNAL-ONLY** — pilot harness output; not customer evidence and not "
    "for external distribution."
)


@dataclass
class PilotResult:
    dry_run: bool
    arms: dict[str, list[str]]
    job_ids: list[str] = field(default_factory=list)
    statuses: dict[str, str] = field(default_factory=dict)
    rows_by_arm: dict[str, dict[str, dict]] = field(default_factory=dict)
    report_markdown: str = ""
    report_path: Path | None = None
    credits: float = 0.0


def _lazy_import_arm_builder() -> Callable[..., dict[str, list[str]]] | None:
    try:
        from lexiforge.contexts.arms import build_arms
    except ImportError:
        return None
    return build_arms


def _lazy_import_validator() -> Callable[[dict], dict] | None:
    try:
        from lexiforge.api.gnani_v3 import validate_batch_config
    except ImportError:
        return None
    return validate_batch_config


def _lazy_import_report() -> tuple[Callable[..., dict] | None, Callable[[dict], str] | None]:
    try:
        from lexiforge.report.keyterm_health import build_report, render_markdown
    except ImportError:
        return None, None
    return build_report, render_markdown


def _glossary_surfaces(glossary: Any) -> list[str]:
    surfaces: list[str] = []
    seen: set[str] = set()
    for entry in glossary or []:
        if isinstance(entry, Mapping):
            surface = entry.get("canonical") or entry.get("term") or entry.get("term_id")
        else:
            surface = entry
        if surface is None:
            continue
        text = str(surface)
        if text and text not in seen:
            seen.add(text)
            surfaces.append(text)
    return surfaces


def _fallback_build_arms(
    hypothesis: str,
    glossary: list[dict],
    call_type: str,
    *,
    budget: int = 200,
    seed: int = 0,
    **_: Any,
) -> dict[str, list[str]]:
    """Stand-in used only until T5 lands; deterministic and overlap-aware."""
    del hypothesis, call_type, seed
    surfaces = _glossary_surfaces(glossary)
    if not surfaces:
        return {name: [] for name in ARM_NAMES}

    def take(start: int) -> list[str]:
        picked: list[str] = []
        index = start
        while len(picked) < budget:
            candidate = surfaces[index % len(surfaces)]
            if candidate not in picked:
                picked.append(candidate)
            index += 1
            if index - start > len(surfaces) * (budget + 1):
                break
        return picked

    return {
        "baseline": [],
        "selected-200": take(0),
        "mismatched-200": take(budget),
        "hard-negative-200": take(2 * budget),
    }


def _build_arms(
    call: str,
    glossary: list[dict],
    *,
    arms_builder: Callable[..., dict[str, list[str]]] | None,
    budget: int,
    seed: int,
) -> dict[str, list[str]]:
    builder = arms_builder or _lazy_import_arm_builder()
    if builder is None:
        built = _fallback_build_arms(f"call {call}", glossary, "general", budget=budget, seed=seed)
    else:
        built = builder(
            hypothesis=f"call {call}",
            glossary=glossary,
            call_type="general",
            budget=budget,
            seed=seed,
        )

    missing = [name for name in ARM_NAMES if name not in built]
    if missing:
        raise ValueError(f"arms builder did not return {missing}")
    return {name: list(built[name]) for name in ARM_NAMES}


def _batch_config(
    arm: str,
    terms: list[str],
    *,
    fmt: str,
    language_code: str,
    budget: int,
) -> dict[str, Any]:
    config: dict[str, Any] = {"format": fmt, "language_code": language_code}
    if arm != "baseline":
        config["keyterms"] = terms[:budget]
    return config


def _normalise_transcript(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"text": "", "segments": [], "detected_language_code": None}
    row = dict(payload)
    text = row.get("text")
    if not isinstance(text, str):
        segments = row.get("segments")
        if isinstance(segments, list):
            parts = [
                str(segment.get("text", ""))
                for segment in segments
                if isinstance(segment, Mapping)
            ]
            text = " ".join(part for part in parts if part)
        else:
            text = ""
    row["text"] = text
    row.setdefault("segments", [])
    detected = row.get("detected_language_code") or row.get("language_code")
    row["detected_language_code"] = detected
    return row


def _normalise_transcripts(transcripts: Any) -> dict[str, dict[str, Any]]:
    if isinstance(transcripts, Mapping):
        items = transcripts.items()
    elif isinstance(transcripts, list):
        items = enumerate(transcripts)
    else:
        return {}
    return {str(key): _normalise_transcript(payload) for key, payload in items}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _resolve_client(client: Any) -> Any:
    if client is not None:
        return client
    from lexiforge.api.client import BatchClient

    # Raises before any network call when GNANI_API_KEY is absent.
    return BatchClient()


def _resolve_validator(validator: Callable[[dict], dict] | None) -> Callable[[dict], dict]:
    resolved = validator or _lazy_import_validator()
    if resolved is None:
        raise RuntimeError(
            "validate_batch_config unavailable: T7 (lexiforge.api.gnani_v3) is not merged; "
            "pass validator= or land T7 before executing."
        )
    return resolved


def _build_report(
    *,
    call: str,
    arms: dict[str, list[str]],
    provenance: dict[str, Any],
    prereg: dict[str, Any],
    report_builder: Callable[..., dict] | None,
    renderer: Callable[[dict], str] | None,
) -> tuple[str, dict[str, Any]]:
    if report_builder is None or renderer is None:
        lazy_builder, lazy_renderer = _lazy_import_report()
        report_builder = report_builder or lazy_builder
        renderer = renderer or lazy_renderer

    if report_builder is not None:
        report = report_builder(call_id=call, arms=arms, provenance=provenance, prereg=prereg)
    else:
        report = {"call_id": call, "arms": arms, "provenance": provenance, "prereg": prereg}
    report.setdefault("internal_only", True)

    if renderer is not None:
        markdown = renderer(report)
    else:
        markdown = "# Keyterm Health Report\n\n" + json.dumps(report, indent=2, ensure_ascii=False)
    if "internal-only" not in markdown.lower():
        markdown = f"{INTERNAL_ONLY_LABEL}\n\n{markdown}"
    return markdown, report


def run_pilot(
    call,
    audio_path,
    glossary,
    *,
    execute=False,
    client=None,
    out_dir="runs",
    budget=200,
    seed=0,
    fmt="transcribe",
    language_code="hi-IN,en-IN",
    poll_timeout=1800,
    arms_builder=None,
    validator=None,
    report_builder=None,
    renderer=None,
):
    """Run the four-arm pilot for one call; dry-run unless ``execute=True``."""
    run_dir = Path(out_dir) / str(call)
    run_dir.mkdir(parents=True, exist_ok=True)

    arms = _build_arms(
        call,
        glossary,
        arms_builder=arms_builder,
        budget=budget,
        seed=seed,
    )

    plan: dict[str, Any] = {
        "call_id": call,
        "audio_path": str(audio_path),
        "execute": bool(execute),
        "format": fmt,
        "language_code": language_code,
        "budget": budget,
        "seed": seed,
        "arms": arms,
        "jobs": {},
    }
    plan_path = run_dir / "plan.json"
    _write_json(plan_path, plan)

    if not execute:
        return PilotResult(dry_run=True, arms=arms)

    audio = Path(audio_path)
    if not audio.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio}.")

    validate_config = _resolve_validator(validator)
    active_client = _resolve_client(client)

    job_ids: list[str] = []
    statuses: dict[str, str] = {}
    for arm in ARM_NAMES:
        config = _batch_config(
            arm,
            arms[arm],
            fmt=fmt,
            language_code=language_code,
            budget=budget,
        )
        config = validate_config(config) or config
        # Job creation is never retried: one POST per arm, one file per job.
        job_id = active_client.create_job(config, [audio])
        job_ids.append(job_id)
        plan["jobs"][arm] = job_id
        _write_json(plan_path, plan)
        active_client.start_job(job_id)
        statuses[job_id] = active_client.wait(job_id, timeout_s=poll_timeout)

    rows_by_arm = {
        arm: _normalise_transcripts(active_client.fetch_all_transcripts(job_id))
        for arm, job_id in zip(ARM_NAMES, job_ids)
    }

    provenance = {
        "call_id": call,
        "audio_path": str(audio_path),
        "format": fmt,
        "language_code": language_code,
        "budget": budget,
        "seed": seed,
    }
    prereg = {"arms": list(ARM_NAMES), "budget": budget}
    report_markdown, _ = _build_report(
        call=call,
        arms=arms,
        provenance=provenance,
        prereg=prereg,
        report_builder=report_builder,
        renderer=renderer,
    )
    report_path = run_dir / "report.md"
    report_path.write_text(report_markdown, encoding="utf-8")

    return PilotResult(
        dry_run=False,
        arms=arms,
        job_ids=job_ids,
        statuses=statuses,
        rows_by_arm=rows_by_arm,
        report_markdown=report_markdown,
        report_path=report_path,
        credits=float(len(job_ids)),
    )


def _load_glossary(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, Mapping):
        data = data.get("terms") or data.get("glossary_terms") or []
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list of glossary entries.")
    return data


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run keyterm pilot (dry-run by default)")
    parser.add_argument("call", nargs="?", default="c00", help="Call ID")
    parser.add_argument("--audio", dest="audio_path", help="Path to audio file")
    parser.add_argument("--glossary", dest="glossary_path", help="Path to glossary JSON")
    parser.add_argument("--execute", action="store_true", help="Execute for real (not dry-run)")
    parser.add_argument("--out-dir", default="runs", help="Output directory")
    parser.add_argument("--budget", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--format", dest="fmt", default="transcribe")
    parser.add_argument("--language-code", dest="language_code", default="hi-IN,en-IN")
    args = parser.parse_args(argv)

    audio_path = args.audio_path or f"data/audio/{args.call}.wav"
    glossary_path = Path(args.glossary_path or "data/glossary.json")
    glossary = _load_glossary(glossary_path) if glossary_path.exists() else []

    result = run_pilot(
        call=args.call,
        audio_path=audio_path,
        glossary=glossary,
        execute=args.execute,
        out_dir=args.out_dir,
        budget=args.budget,
        seed=args.seed,
        fmt=args.fmt,
        language_code=args.language_code,
    )

    if result.dry_run:
        plan_path = Path(args.out_dir) / args.call / "plan.json"
        print(f"Dry run for {args.call}: plan written to {plan_path}")
        print(f"Arms: {', '.join(f'{name} ({len(terms)})' for name, terms in result.arms.items())}")
    else:
        print(
            f"Executed pilot for {args.call}: {len(result.job_ids)} jobs, "
            f"report at {result.report_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
