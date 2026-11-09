"""Offline reproduction of a Keyterm Health study run (design §7, P18).

``reproduce`` reads the per-arm transcripts written by the study runner,
re-scores them against the same glossary with the frozen matcher, re-runs the
pre-registered H1/H2 analysis, and writes ``reproduce.json``. It never calls
the network: the only inputs are the manifest, the glossary and the stored
transcripts, each recorded with its sha256.

The recorded ``summary.json`` verdict is compared, never trusted: a tampered
transcript changes the recomputed verdict and clears ``matches_summary``.

P01 (transcript store) and P09 (pre-registered analysis) are imported lazily;
when they are not present yet, the reader and the analysis fall back to the
local implementations below so this module can land independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARM_NAMES = ("baseline", "selected-200", "mismatched-200", "hard-negative-200")
TRANSCRIPT_SUFFIX = ".transcript.json"

__all__ = ["MissingTranscript", "main", "reproduce"]


class MissingTranscript(FileNotFoundError):
    """A required per-arm transcript is absent; reproduction cannot proceed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def _posix(path: Path) -> str:
    return path.as_posix()


def _load_manifest(path: Path) -> dict[str, Any]:
    """Load the intake manifest, preferring the P14 study package."""
    try:
        from lexiforge.study.manifest import load_manifest
    except ImportError:
        from scripts.run_keyterm_study import load_manifest
    return load_manifest(path)


def _load_glossary(path: Path) -> list[dict]:
    from lexiforge.score.match import load_glossary

    return load_glossary(path)


def _read_transcript(path: Path) -> dict[str, Any]:
    """Read one arm transcript, preferring the P01 store reader."""
    try:
        from lexiforge.score.store import read_arm_transcript
    except ImportError:
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = read_arm_transcript(path)
    if not isinstance(data, Mapping):
        raise ValueError(f"transcript {path} must contain a JSON object")
    return dict(data)


def _transcript_text(payload: Mapping[str, Any]) -> str:
    text = payload.get("text")
    if isinstance(text, str):
        return text
    rows = payload.get("rows")
    if isinstance(rows, Mapping):
        parts = [
            str(row.get("text") or "")
            for _, row in sorted(rows.items())
            if isinstance(row, Mapping)
        ]
        return " ".join(part for part in parts if part).strip()
    if isinstance(rows, list):
        parts = [
            str(row.get("text") or "") for row in rows if isinstance(row, Mapping)
        ]
        return " ".join(part for part in parts if part).strip()
    return ""


def _plan_path(call_dir: Path) -> Path:
    return call_dir / "plan.json"


def _read_plan(call_dir: Path) -> dict[str, Any]:
    path = _plan_path(call_dir)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return dict(data)


def _call_dir(runs_dir: Path, study_dir: Path, call_id: str) -> Path:
    primary = runs_dir / call_id
    if primary.is_dir():
        return primary
    alternate = study_dir / call_id
    if alternate.is_dir():
        return alternate
    return primary


def _expected_arms(plan: Mapping[str, Any], call_dir: Path) -> list[str]:
    declared = plan.get("arms")
    if isinstance(declared, Mapping) and declared:
        return [str(name) for name in declared]
    if isinstance(declared, (list, tuple)) and declared:
        return [str(name) for name in declared]
    found = sorted(
        path.name[: -len(TRANSCRIPT_SUFFIX)]
        for path in call_dir.glob(f"*{TRANSCRIPT_SUFFIX}")
    )
    return found or list(ARM_NAMES)


def _reference_text(
    call: Mapping[str, Any], manifest_dir: Path, runs_dir: Path
) -> str:
    inline = call.get("reference_text")
    if isinstance(inline, str) and inline.strip():
        return inline
    raw = call.get("reference")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"call {call.get('call_id')!r} has no reference text")
    path = Path(raw)
    candidates = (
        [path]
        if path.is_absolute()
        else [manifest_dir / path, Path.cwd() / path, runs_dir / path]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(f"reference transcript not found: {raw}")


def _origin_strata(glossary: list[dict]) -> list[str]:
    seen = {
        entry.get("origin")
        for entry in glossary
        if isinstance(entry, Mapping) and isinstance(entry.get("origin"), str)
    }
    ordered = [
        origin for origin in ("real", "fictional", "oov") if origin in seen
    ]
    return ordered or ["real"]


def _score_call(
    call: Mapping[str, Any],
    glossary: list[dict],
    transcripts: Mapping[str, str],
    *,
    manifest_dir: Path,
    runs_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Re-score every arm of one call with the frozen matcher."""
    from lexiforge.score.match import score_file_detail
    from lexiforge.score.metrics import term_recall, wer

    call_id = str(call["call_id"])
    reference = _reference_text(call, manifest_dir, runs_dir)
    try:
        utterances = max(1, int(call.get("utterances") or 1))
    except (TypeError, ValueError):
        utterances = 1
    strata = _origin_strata(glossary)

    scores: dict[str, dict[str, Any]] = {}
    for arm, hypothesis in transcripts.items():
        detail = score_file_detail(reference, hypothesis, glossary)
        rows = [{"call_id": call_id, **row} for row in detail["rows"]]
        metrics: dict[str, Any] = {
            "insertions_per_utterance": {
                "num": float(detail["insertions"]),
                "den": float(utterances),
            },
            "wer": float(wer(reference, hypothesis)),
        }
        for origin in strata:
            recall = term_recall(rows, stratum=origin)
            metrics[f"{origin}_recall"] = {
                "num": float(recall["numerator"]),
                "den": float(recall["denominator"]),
            }
        # One aggregate row per call keeps paired deltas computable while the
        # term rows feed the appendix (same shape as the study runner).
        rows.append({"call_id": call_id, **metrics})
        scores[arm] = {"call_id": call_id, "rows": rows, "metrics": metrics}
    return scores


def _merge_arms(call_scores: list[dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Pool per-call scores into report arms, summing counts across calls."""
    merged: dict[str, dict[str, Any]] = {}
    for scores in call_scores:
        for arm, score in scores.items():
            target = merged.setdefault(
                arm,
                {"name": arm, "rows": [], "metrics": {}, "_wers": []},
            )
            target["rows"].extend(score["rows"])
            for key, value in score["metrics"].items():
                if key == "wer":
                    if isinstance(value, (int, float)):
                        target["_wers"].append(float(value))
                elif (
                    isinstance(value, Mapping)
                    and "num" in value
                    and "den" in value
                ):
                    counts = target["metrics"].setdefault(
                        key, {"num": 0.0, "den": 0.0}
                    )
                    counts["num"] += float(value["num"])
                    counts["den"] += float(value["den"])

    arms: list[dict[str, Any]] = []
    for target in merged.values():
        wers = target.pop("_wers")
        if wers:
            target["metrics"]["wer"] = sum(wers) / len(wers)
        arms.append(target)
    return arms


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _rate(counts: Any) -> float | None:
    if not isinstance(counts, Mapping):
        return None
    num, den = counts.get("num"), counts.get("den")
    if not (_finite(num) and _finite(den)) or float(den) <= 0:
        return None
    return float(num) / float(den)


def _analysis_input(
    call_scores: list[dict[str, dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    """Per-call scalars in the shape ``analyse_h1_h2`` consumes."""
    per_call: dict[str, list[dict[str, Any]]] = {}
    for scores in call_scores:
        for arm, score in scores.items():
            metrics = score["metrics"]
            per_call.setdefault(arm, []).append(
                {
                    "call_id": score["call_id"],
                    "real_recall": _rate(metrics.get("real_recall")),
                    "real_recall_counts": metrics.get("real_recall"),
                    "insertions_per_utterance": _rate(
                        metrics.get("insertions_per_utterance")
                    ),
                    "insertions_per_utterance_counts": metrics.get(
                        "insertions_per_utterance"
                    ),
                    "wer": metrics.get("wer"),
                }
            )
    return per_call


def _paired_deltas(
    per_call: Mapping[str, list[dict[str, Any]]],
    treated: str,
    metric: str,
    *,
    baseline: str = "baseline",
) -> list[float]:
    base = {
        row.get("call_id"): row.get(metric)
        for row in per_call.get(baseline) or []
    }
    deltas: list[float] = []
    for row in per_call.get(treated) or []:
        before = base.get(row.get("call_id"))
        after = row.get(metric)
        if _finite(before) and _finite(after):
            deltas.append(float(after) - float(before))
    return deltas


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _cluster_se(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance / len(values))


def _local_analysis(
    per_call: Mapping[str, list[dict[str, Any]]],
    *,
    seed: int = 0,
    n_permutations: int = 10000,
) -> dict[str, Any]:
    """Stand-in H1/H2 analysis used until P09's module is available.

    H1 is a one-sided sign-flip test of (mismatched - baseline) real recall
    with ``alternative="less"``; H2 is the same on insertions per utterance
    with ``alternative="greater"``. Holm runs over exactly these two tests.
    The positive control reports a cluster CI and never a p-value.
    """
    from lexiforge.analysis.inference import (
        cluster_bootstrap_ci,
        holm,
        mde,
        sign_flip_test,
    )

    treated = "mismatched-200" if "mismatched-200" in per_call else None
    h1_deltas = (
        _paired_deltas(per_call, treated, "real_recall") if treated else []
    )
    h2_deltas = (
        _paired_deltas(per_call, treated, "insertions_per_utterance")
        if treated
        else []
    )
    n_calls = min(len(h1_deltas), len(h2_deltas)) if treated else 0

    def _test(deltas: list[float], metric: str, alternative: str) -> dict:
        if len(deltas) < 2:
            return {
                "metric": metric,
                "alternative": alternative,
                "estimate": _mean(deltas),
                "p_value": None,
                "n_calls": len(deltas),
                "status": "INCONCLUSIVE",
            }
        result = sign_flip_test(
            deltas,
            alternative=alternative,
            n_permutations=n_permutations,
            seed=seed,
        )
        rejected = (
            result["p_value"] <= 0.025
            if alternative == "less"
            else result["p_value"] <= 0.05
        )
        return {
            "metric": metric,
            "alternative": alternative,
            "estimate": result["statistic"],
            "p_value": result["p_value"],
            "n_calls": result["n"],
            "status": "rejected" if rejected else "not_rejected",
        }

    h1 = _test(h1_deltas, "real_recall", "less")
    h2 = _test(h2_deltas, "insertions_per_utterance", "greater")

    thresholds = {"h1": 0.025, "h2": 0.05}
    if h1["p_value"] is not None and h2["p_value"] is not None:
        family = holm({"h1": h1["p_value"], "h2": h2["p_value"]}, alpha=0.05)
        holm_result = {
            "adjusted": family["adjusted"],
            "rejected": family["rejected"],
            "alpha": 0.05,
            "thresholds": thresholds,
        }
    else:
        holm_result = {
            "adjusted": {"h1": None, "h2": None},
            "rejected": {"h1": False, "h2": False},
            "alpha": 0.05,
            "thresholds": thresholds,
        }

    if "oracle-200" in per_call:
        control_deltas = _paired_deltas(per_call, "oracle-200", "real_recall")
        if control_deltas:
            ci = cluster_bootstrap_ci(control_deltas, n_boot=n_permutations, seed=seed)
            positive_control = {
                "status": "present",
                "metric": "real_recall",
                "estimate": ci["statistic"],
                "ci_low": ci["ci_low"],
                "ci_high": ci["ci_high"],
                "n_calls": ci["n"],
            }
        else:
            positive_control = {"status": "inconclusive"}
    else:
        positive_control = {"status": "absent"}

    se = _cluster_se(h1_deltas)
    mde_result = {
        "metric": "real_recall",
        "se": se,
        "value": mde(se, alpha=0.025, power=0.8) if se is not None else None,
        "alpha": 0.025,
        "power": 0.8,
        "n_calls": len(h1_deltas),
    }

    if n_calls < 2:
        claim_ladder = "harness only"
    elif h1["status"] == "rejected" and h2["status"] == "rejected":
        claim_ladder = "H1+H2"
    elif h2["status"] == "rejected":
        claim_ladder = "H2 alone with H1 inconclusive"
    else:
        claim_ladder = "mechanism only"

    return {
        "h1": h1,
        "h2": h2,
        "holm": holm_result,
        "positive_control": positive_control,
        "mde": mde_result,
        "claim_ladder": claim_ladder,
        "n_calls": n_calls,
    }


def _analyse(
    per_call: Mapping[str, list[dict[str, Any]]], *, seed: int
) -> tuple[dict[str, Any], str]:
    try:
        from lexiforge.analysis.preregistered import analyse_h1_h2
    except ImportError:
        return (
            _local_analysis(per_call, seed=seed, n_permutations=10000),
            "local-fallback",
        )
    return (
        analyse_h1_h2(
            per_call,
            cluster_key="call_id",
            n_permutations=10000,
            seed=seed,
        ),
        "preregistered",
    )


def _read_recorded_verdict(path: Path) -> str | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    verdict = data.get("verdict") if isinstance(data, Mapping) else None
    return verdict if isinstance(verdict, str) else None


def _jsonable(value: Any) -> Any:
    """Convert a value to strict JSON: non-finite floats become null."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (int, bool, str)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return _jsonable(value.item())
    return str(value)


def reproduce(
    manifest_path: str | Path,
    runs_dir: str | Path,
    out_path: str | Path,
    *,
    glossary_path: str | Path = "data/glossary.json",
    seed: int = 0,
) -> dict[str, Any]:
    """Re-score stored transcripts and write ``reproduce.json``.

    Raises :class:`MissingTranscript` when any expected arm transcript is
    absent; the CLI maps that to exit code 2.
    """
    from lexiforge.canon import CANON_VERSION
    from lexiforge.report.keyterm_health import build_report

    manifest_path = Path(manifest_path)
    runs_dir = Path(runs_dir)
    glossary_path = Path(glossary_path)
    out_path = Path(out_path)

    manifest = _load_manifest(manifest_path)
    glossary = _load_glossary(glossary_path)
    study_id = str(manifest["study_id"])
    calls = list(manifest.get("calls") or [])
    study_dir = runs_dir / study_id

    transcript_inputs: dict[str, dict[str, str]] = {}
    canon_versions: set[str] = set()
    call_scores: list[dict[str, dict[str, Any]]] = []

    for call in calls:
        call_id = str(call["call_id"])
        call_dir = _call_dir(runs_dir, study_dir, call_id)
        arms = _expected_arms(_read_plan(call_dir), call_dir)
        transcripts: dict[str, str] = {}
        for arm in arms:
            path = call_dir / f"{arm}{TRANSCRIPT_SUFFIX}"
            if not path.is_file():
                raise MissingTranscript(
                    f"missing arm transcript for {call_id}/{arm}: "
                    f"{_posix(path)}"
                )
            payload = _read_transcript(path)
            version = payload.get("canon_version")
            if isinstance(version, str) and version:
                canon_versions.add(version)
            transcripts[arm] = _transcript_text(payload)
            transcript_inputs[f"{call_id}/{arm}"] = {
                "path": _posix(path),
                "sha256": _sha256_file(path),
            }
        call_scores.append(
            _score_call(
                call,
                glossary,
                transcripts,
                manifest_dir=manifest_path.parent,
                runs_dir=runs_dir,
            )
        )

    arms = _merge_arms(call_scores)
    report = build_report(
        call_id=study_id,
        arms=arms,
        provenance={
            "model": "prisma-v3.0",
            "canon_version": CANON_VERSION,
            "seed": seed,
            "source": "re-scored from stored arm transcripts",
            "study_id": study_id,
        },
        prereg={
            "arms": [arm["name"] for arm in arms],
            "n_calls": len(calls),
            "cluster_key": "call_id",
            "seed": seed,
        },
    )

    analysis, analysis_source = _analyse(
        _analysis_input(call_scores), seed=seed
    )
    recorded_verdict = _read_recorded_verdict(study_dir / "summary.json")
    result = _jsonable(
        {
            "study_id": study_id,
            "inputs": {
                "manifest": {
                    "path": _posix(manifest_path),
                    "sha256": _sha256_file(manifest_path),
                },
                "glossary": {
                    "path": _posix(glossary_path),
                    "sha256": _sha256_file(glossary_path),
                },
                "transcripts": transcript_inputs,
            },
            "canon_version": CANON_VERSION,
            "transcript_canon_versions": sorted(canon_versions),
            "per_arm": {
                summary["arm"]: summary for summary in report["metrics_summary"]
            },
            "deltas": report["paired_deltas"],
            "verdict": report["verdict"],
            "recorded_verdict": recorded_verdict,
            "matches_summary": bool(
                recorded_verdict is not None
                and recorded_verdict == report["verdict"]
            ),
            "n_calls": report.get("n_calls", 0),
            "analysis": analysis,
            "analysis_source": analysis_source,
        }
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reproduce a keyterm study offline from stored arm transcripts"
    )
    parser.add_argument("manifest", help="Path to the study manifest JSON")
    parser.add_argument("--runs-dir", default="runs", help="Study output directory")
    parser.add_argument("--out", default="runs/reproduce.json")
    parser.add_argument("--glossary", default="data/glossary.json")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    try:
        result = reproduce(
            args.manifest,
            args.runs_dir,
            args.out,
            glossary_path=args.glossary,
            seed=args.seed,
        )
    except MissingTranscript as exc:
        print(f"Missing transcript: {exc}", file=sys.stderr)
        return 2

    print(
        f"Reproduced {result['study_id']}: verdict {result['verdict']}, "
        f"matches recorded summary: {result['matches_summary']}, "
        f"output {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
