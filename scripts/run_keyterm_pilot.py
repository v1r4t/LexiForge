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
import time
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
    hypothesis: str,
    glossary: list[dict],
    call_type: str,
    *,
    arms_builder: Callable[..., dict[str, list[str]]] | None,
    budget: int,
    seed: int,
) -> dict[str, list[str]]:
    builder = arms_builder or _lazy_import_arm_builder()
    if builder is None:
        built = _fallback_build_arms(
            hypothesis, glossary, call_type, budget=budget, seed=seed
        )
    else:
        built = builder(
            hypothesis=hypothesis,
            glossary=glossary,
            call_type=call_type,
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
    config: dict[str, Any] = {
        "model": "prisma-v3.0",
        "format": fmt,
        "language_code": language_code,
    }
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


def _load_script(call: Any) -> dict[str, Any]:
    """Load ``data/scripts/<call>.json`` when present; empty otherwise."""
    path = Path("data/scripts") / f"{call}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return dict(data)


def _reference_text_from_script(call: Any, script: Mapping[str, Any]) -> str:
    turns = script.get("turns")
    parts: list[str] = []
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, Mapping):
                continue
            text = turn.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    text = " ".join(parts)
    if not text:
        path = Path("data/scripts") / f"{call}.json"
        raise FileNotFoundError(f"Reference transcript not found: {path} has no turn text.")
    return text


def _transcript_text(rows: Mapping[str, Mapping[str, Any]]) -> str:
    parts = [
        str(row.get("text") or "").strip()
        for _, row in sorted(rows.items())
        if isinstance(row, Mapping)
    ]
    return " ".join(part for part in parts if part).strip()


def _entry_origin(entry: Any) -> str | None:
    if not isinstance(entry, Mapping):
        return None
    for key in ("origin", "kind", "term_type", "origin_type"):
        value = entry.get(key)
        if isinstance(value, str) and value in ("real", "fictional", "oov"):
            return value
    return None


def _origin_glossary(glossary: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {"real": [], "fictional": [], "oov": []}
    tagged = False
    for entry in glossary or []:
        origin = _entry_origin(entry)
        if origin is None:
            continue
        groups[origin].append(entry)
        tagged = True
    if not tagged:
        # Legacy glossaries without origin tags can still yield the primary
        # real-term recall metric.
        return {"real": list(glossary or [])}
    return {name: entries for name, entries in groups.items() if entries}


def _score_arms(
    *,
    call: Any,
    rows_by_arm: Mapping[str, Mapping[str, Mapping[str, Any]]],
    reference_text: str,
    glossary: list[dict],
    script: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Score each arm transcript against the reference script.

    ``score_file`` is the frozen scorer. Scoring per origin (from the
    glossary's ``origin`` field) yields recall numerator/denominator counts
    without re-implementing the matcher.
    """
    from lexiforge.score.match import score_file_detail
    from lexiforge.score.metrics import term_recall, wer

    groups = _origin_glossary(glossary)
    turns = script.get("turns")
    n_utterances = len(turns) if isinstance(turns, list) and turns else 1

    scored: list[dict[str, Any]] = []
    for name in ARM_NAMES:
        hypothesis = _transcript_text(rows_by_arm.get(name) or {})
        detail = score_file_detail(reference_text, hypothesis, glossary)
        rows = [{"call_id": str(call), **row} for row in detail["rows"]]
        metrics: dict[str, Any] = {
            "insertions_per_utterance": {
                "num": detail["insertions"],
                "den": n_utterances,
            },
            "wer": float(wer(reference_text, hypothesis)),
        }
        for origin in groups:
            recall = term_recall(rows, stratum=origin)
            metrics[f"{origin}_recall"] = {
                "num": recall["numerator"],
                "den": recall["denominator"],
            }
        # One aggregate row per call keeps paired deltas computable while the
        # term rows feed the appendix.
        rows.append({"call_id": str(call), **metrics})
        scored.append({"name": name, "rows": rows, "metrics": metrics})
    return scored


def _resolve_client(client: Any) -> Any:
    if client is not None:
        return client
    import os

    if not os.environ.get("GNANI_API_KEY"):
        raise ValueError("API key is missing (GNANI_API_KEY).")
    from lexiforge.api.client import BatchClient

    # The constructor re-checks the key, then opens an httpx client.
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
    arms: list[dict[str, Any]],
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


def _create_job_with_retry(
    client: Any,
    config: dict,
    audio: Path,
    *,
    attempts: int = 6,
    base: float = 5.0,
) -> str:
    """Create a job, waiting out 429s; never retry ambiguous failures."""
    from lexiforge.api.client import BatchApiError

    for attempt in range(attempts):
        try:
            return client.create_job(config, [audio])
        except BatchApiError as exc:
            rate_limited = getattr(exc, "status_code", None) == 429
            if not rate_limited or attempt >= attempts - 1:
                raise
            time.sleep(base * (2**attempt))
    raise RuntimeError("unreachable")


def _run_arm(
    active_client: Any,
    arm: str,
    terms: list[str],
    *,
    audio: Path,
    plan: dict[str, Any],
    plan_path: Path,
    validate_config: Callable[[dict], dict],
    fmt: str,
    language_code: str,
    budget: int,
    poll_timeout: float,
) -> tuple[str, str]:
    config = _batch_config(
        arm,
        terms,
        fmt=fmt,
        language_code=language_code,
        budget=budget,
    )
    config = validate_config(config) or config
    # Job creation is never retried ambiguously; a 429 is a clean rejection.
    job_id = _create_job_with_retry(active_client, config, audio)
    plan["jobs"][arm] = job_id
    _write_json(plan_path, plan)
    active_client.start_job(job_id)
    status = active_client.wait(job_id, timeout_s=poll_timeout)
    return job_id, status


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
    reference_text=None,
    arms_builder=None,
    validator=None,
    report_builder=None,
    renderer=None,
):
    """Run the four-arm pilot for one call; dry-run unless ``execute=True``."""
    run_dir = Path(out_dir) / str(call)
    run_dir.mkdir(parents=True, exist_ok=True)

    script = _load_script(call)
    call_type = str(script.get("call_type") or "general")

    plan: dict[str, Any] = {
        "call_id": call,
        "audio_path": str(audio_path),
        "execute": bool(execute),
        "call_type": call_type,
        "format": fmt,
        "language_code": language_code,
        "budget": budget,
        "seed": seed,
        "arms": {},
        "jobs": {},
    }
    plan_path = run_dir / "plan.json"

    if not execute:
        # No pass-1 transcript exists yet, so selection is provisional and
        # uses only call metadata. The reference script must never be the
        # selector input (circularity).
        plan["arms"] = _build_arms(
            f"call {call}",
            glossary,
            call_type,
            arms_builder=arms_builder,
            budget=budget,
            seed=seed,
        )
        plan["selection_source"] = "dry-run placeholder"
        _write_json(plan_path, plan)
        return PilotResult(dry_run=True, arms=plan["arms"])

    audio = Path(audio_path)
    if not audio.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio}.")

    if reference_text is None:
        reference_text = _reference_text_from_script(call, script)

    validate_config = _resolve_validator(validator)
    active_client = _resolve_client(client)

    job_ids: list[str] = []
    statuses: dict[str, str] = {}

    # Baseline first: its transcript is the selector input for the treated arms.
    baseline_job, baseline_status = _run_arm(
        active_client,
        "baseline",
        [],
        audio=audio,
        plan=plan,
        plan_path=plan_path,
        validate_config=validate_config,
        fmt=fmt,
        language_code=language_code,
        budget=budget,
        poll_timeout=poll_timeout,
    )
    job_ids.append(baseline_job)
    statuses[baseline_job] = baseline_status
    rows_by_arm: dict[str, dict[str, dict[str, Any]]] = {
        "baseline": _normalise_transcripts(
            active_client.fetch_all_transcripts(baseline_job)
        )
    }

    arms = _build_arms(
        _transcript_text(rows_by_arm["baseline"]),
        glossary,
        call_type,
        arms_builder=arms_builder,
        budget=budget,
        seed=seed,
    )
    plan["arms"] = arms
    plan["selection_source"] = "baseline pass-1 transcript"
    _write_json(plan_path, plan)

    for arm in ARM_NAMES[1:]:
        job_id, status = _run_arm(
            active_client,
            arm,
            arms[arm],
            audio=audio,
            plan=plan,
            plan_path=plan_path,
            validate_config=validate_config,
            fmt=fmt,
            language_code=language_code,
            budget=budget,
            poll_timeout=poll_timeout,
        )
        job_ids.append(job_id)
        statuses[job_id] = status
        rows_by_arm[arm] = _normalise_transcripts(
            active_client.fetch_all_transcripts(job_id)
        )

    provenance = {
        "call_id": call,
        "call_type": call_type,
        "audio_path": str(audio_path),
        "format": fmt,
        "language_code": language_code,
        "budget": budget,
        "seed": seed,
    }
    prereg = {"arms": list(ARM_NAMES), "budget": budget, "call_type": call_type}
    scored_arms = _score_arms(
        call=call,
        rows_by_arm=rows_by_arm,
        reference_text=reference_text,
        glossary=glossary,
        script=script,
    )
    report_markdown, _ = _build_report(
        call=call,
        arms=scored_arms,
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
