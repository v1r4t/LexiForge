"""Keyterm Health Report for the Gnani keyterm POC.

The primary decision is a pre-registered non-inferiority rule, not a
significance test: the 95% CI lower bound of (selected - baseline) real-term
recall must stay at or above the recall margin, and the 95% CI upper bound of
the paired insertions-per-utterance delta must stay at or below the insertion
cap. Lift is reported as a descriptive secondary estimate only.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

import numpy as np

from lexiforge.analysis.inference import cluster_bootstrap_ci

__all__ = ["build_report", "paired_delta", "render_markdown", "verdict"]

_METRIC_ALIASES = {
    "real_recall": ("real_recall", "real_term_recall"),
    "fictional_recall": ("fictional_recall", "fictional_term_recall"),
    "oov_recall": ("oov_recall", "oov_term_recall"),
    "insertions_per_utterance": (
        "insertions_per_utterance",
        "insertions_utterance",
        "insertions_per_utt",
    ),
    "wer": ("wer", "word_error_rate"),
    "decoder_ignore": ("decoder_ignore", "decoder_ignore_rate"),
}

_ORIGINS = {
    "real_recall": "real",
    "fictional_recall": "fictional",
    "oov_recall": "oov",
}

_COUNT_PAIRS = (("num", "den"), ("numerator", "denominator"), ("n", "d"))

_INSERTION_FLAGS = (
    "insertion",
    "insert",
    "event",
    "glossary_insertion",
    "is_insertion",
)

_DEFAULT_DISCLOSURES = {
    "synthetic_audio": (
        "Synthetic (TTS) audio, when used, is internal harness validation only. "
        "It is not evidence about real customer calls and must not be presented as a "
        "real-world result."
    ),
    "circularity": (
        "Keyterms are selected from the baseline pass-1 transcript and call metadata, "
        "never from the reference script, so the selected arm is not scored on terms it "
        "was handed. The baseline arm is also the selector input, so any lift is "
        "descriptive rather than independent."
    ),
}


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _aliases(metric: str) -> tuple[str, ...]:
    return _METRIC_ALIASES.get(metric, (metric,))


def _as_counts(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, Mapping):
        return None
    for num_key, den_key in _COUNT_PAIRS:
        if num_key in value and den_key in value:
            try:
                return float(value[num_key]), float(value[den_key])
            except (TypeError, ValueError):
                return None
    # ``lexiforge.score.metrics.insertions_per_utterance`` reports the interval
    # on the total, so recover the per-utterance mean from total_events/utterances.
    if "total_events" in value and "n_utterances" in value:
        try:
            return float(value["total_events"]), float(value["n_utterances"])
        except (TypeError, ValueError):
            return None
    return None


def _lookup(row: Mapping[str, Any], metric: str) -> Any:
    containers = [row]
    nested = row.get("metrics")
    if isinstance(nested, Mapping):
        containers.append(nested)
    for container in containers:
        for alias in _aliases(metric):
            if container.get(alias) is not None:
                return container[alias]
    return None


def _cluster_value(rows: Iterable[Mapping[str, Any]], metric: str) -> float:
    """Reduce a cluster's rows to one value, pooling counts before averaging."""
    num_total = 0.0
    den_total = 0.0
    has_counts = False
    scalars: list[float] = []

    for row in rows:
        value = _lookup(row, metric)
        if value is None:
            continue
        counts = _as_counts(value)
        if counts is not None:
            num, den = counts
            if _finite(num) and _finite(den) and den > 0:
                num_total += num
                den_total += den
                has_counts = True
            continue
        if isinstance(value, Mapping):
            mean = value.get("mean")
            if _finite(mean):
                scalars.append(float(mean))
            continue
        if _finite(value):
            scalars.append(float(value))

    if has_counts and den_total > 0:
        return num_total / den_total
    if scalars:
        return float(np.mean(scalars))
    return float("nan")


def _group(rows: Iterable[Mapping[str, Any]], cluster_key: str) -> dict[Any, list]:
    grouped: dict[Any, list] = {}
    for row in rows or []:
        key = row.get(cluster_key)
        grouped.setdefault(key, []).append(row)
    return grouped


def paired_delta(
    rows_a: Iterable[Mapping[str, Any]],
    rows_b: Iterable[Mapping[str, Any]],
    metric: str,
    *,
    cluster_key: str = "call_id",
    n_boot: int = 10000,
    seed: int = 0,
) -> dict:
    """Paired cluster bootstrap delta, one value per call.

    Each cluster is reduced to a single value per arm (counts are pooled, so a
    recall metric is total hits / total opportunities). Delta is ``b - a`` and
    the CI resamples whole clusters.
    """
    by_a = _group(rows_a, cluster_key)
    by_b = _group(rows_b, cluster_key)
    shared = sorted(set(by_a) & set(by_b), key=lambda x: (str(type(x)), repr(x)))

    deltas: list[float] = []
    clusters: list[Any] = []
    for cluster in shared:
        value_a = _cluster_value(by_a[cluster], metric)
        value_b = _cluster_value(by_b[cluster], metric)
        if math.isfinite(value_a) and math.isfinite(value_b):
            deltas.append(value_b - value_a)
            clusters.append(cluster)

    result = {
        "metric": metric,
        "deltas": deltas,
        "clusters": clusters,
        "n": len(deltas),
        "mean": float("nan"),
        "ci_low": float("nan"),
        "ci_high": float("nan"),
    }
    if not deltas:
        return result

    ci = cluster_bootstrap_ci(deltas, statistic=np.mean, n_boot=n_boot, seed=seed)
    result["mean"] = float(np.mean(deltas))
    result["ci_low"] = ci["ci_low"]
    result["ci_high"] = ci["ci_high"]
    return result


def _metric_counts(metrics: Mapping[str, Any], metric: str) -> tuple[float, float] | None:
    for alias in _aliases(metric):
        if alias in metrics:
            counts = _as_counts(metrics[alias])
            if counts is not None:
                return counts
    if metric == "decoder_ignore":
        for num_key, den_key in (
            ("decoder_ignore_num", "decoder_ignore_den"),
            ("decoder_ignored", "relevant_in_context"),
        ):
            if num_key in metrics and den_key in metrics:
                try:
                    return float(metrics[num_key]), float(metrics[den_key])
                except (TypeError, ValueError):
                    return None
    return None


def _metric_scalar(metrics: Mapping[str, Any], metric: str) -> float | None:
    for alias in _aliases(metric):
        value = metrics.get(alias)
        if _finite(value):
            return float(value)
        if isinstance(value, Mapping):
            for key in ("rate", "wer", "mean", "value"):
                if _finite(value.get(key)):
                    return float(value[key])
    return None


def _row_origin(row: Mapping[str, Any]) -> str | None:
    for key in ("origin", "kind", "term_type", "origin_type"):
        value = row.get(key)
        if isinstance(value, str):
            return value
    return None


def _in_denominator(row: Mapping[str, Any]) -> bool:
    value = row.get("in_denom")
    if value is None:
        value = row.get("should_recall", row.get("denom", True))
    return bool(value)


def _is_hit(row: Mapping[str, Any]) -> bool:
    return any(
        row.get(key) is True for key in ("hit", "correct", "recalled", "matched")
    )


def _rows_counts(rows: Iterable[Mapping[str, Any]], metric: str) -> tuple[float, float] | None:
    """Aggregate per-call counts, or fall back to term-level origin rows."""
    num_total = 0.0
    den_total = 0.0
    found = False
    for row in rows or []:
        counts = _as_counts(_lookup(row, metric))
        if counts is None:
            continue
        num, den = counts
        if _finite(num) and _finite(den) and den > 0:
            num_total += num
            den_total += den
            found = True
    if found and den_total > 0:
        return num_total, den_total

    origin = _ORIGINS.get(metric)
    if origin is None:
        return None
    num = den = 0
    for row in rows or []:
        if _row_origin(row) != origin or not _in_denominator(row):
            continue
        den += 1
        if _is_hit(row):
            num += 1
    if den == 0:
        return None
    return float(num), float(den)


def _rows_insertion_counts(rows: Iterable[Mapping[str, Any]]) -> tuple[float, float] | None:
    counts = _rows_counts(rows, "insertions_per_utterance")
    if counts is not None:
        return counts
    per_utterance: dict[Any, int] = {}
    for row in rows or []:
        utterance = (
            row.get("utterance_id")
            or row.get("utterance")
            or row.get("utt_id")
            or row.get("utt")
        )
        if utterance is None:
            continue
        per_utterance.setdefault(utterance, 0)
        if any(row.get(flag) is True for flag in _INSERTION_FLAGS):
            per_utterance[utterance] += 1
    if not per_utterance:
        return None
    return float(sum(per_utterance.values())), float(len(per_utterance))


def _decoder_counts_from_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[float, float] | None:
    """Spoken context terms still missed / all spoken context terms.

    The denominator is every term the reference says was spoken and the arm
    supplied in context; the numerator is the subset the hypothesis missed.
    """
    num = den = 0
    for row in rows or []:
        in_context = any(
            row.get(key) is True
            for key in ("in_context", "present_in_context", "in_context_list")
        )
        if not in_context:
            continue
        den += 1
        if not _is_hit(row):
            num += 1
    if den == 0:
        return None
    return float(num), float(den)


def _counts_payload(num: float, den: float) -> dict:
    return {
        "num": num,
        "den": den,
        "rate": num / den if den > 0 else None,
    }


def _summarize_arm(arm: Mapping[str, Any]) -> dict:
    metrics = arm["metrics"]
    rows = arm["rows"]
    summary: dict[str, Any] = {"arm": arm["name"]}

    for metric in ("real_recall", "fictional_recall", "oov_recall"):
        counts = _metric_counts(metrics, metric)
        if counts is None:
            counts = _rows_counts(rows, metric)
        if counts is not None:
            summary[metric] = _counts_payload(*counts)
        else:
            summary[metric] = {"rate": _metric_scalar(metrics, metric)}

    counts = _metric_counts(metrics, "insertions_per_utterance")
    if counts is None:
        counts = _rows_insertion_counts(rows)
    if counts is not None:
        summary["insertions_per_utterance"] = _counts_payload(*counts)
    else:
        summary["insertions_per_utterance"] = {
            "rate": _metric_scalar(metrics, "insertions_per_utterance")
        }

    wer = _metric_scalar(metrics, "wer")
    if wer is None and rows:
        reduced = _cluster_value(rows, "wer")
        wer = reduced if math.isfinite(reduced) else None
    summary["wer"] = {"rate": wer}

    counts = _metric_counts(metrics, "decoder_ignore")
    if counts is None:
        counts = _decoder_counts_from_rows(rows)
    if counts is not None:
        summary["decoder_ignore"] = _counts_payload(*counts)
    else:
        summary["decoder_ignore"] = {"rate": _metric_scalar(metrics, "decoder_ignore")}

    return summary


def _normalize_arm(arm: Mapping[str, Any]) -> dict:
    name = arm.get("name") or arm.get("arm") or arm.get("id") or arm.get("label")
    metrics = arm.get("metrics") or arm.get("results") or arm.get("scores") or {}
    rows = arm.get("rows") or arm.get("per_call") or arm.get("records") or []
    return {
        "name": str(name or "unknown"),
        "metrics": dict(metrics),
        "rows": list(rows),
    }


def _find_arm(arms: Iterable[Mapping[str, Any]], name: str) -> Mapping[str, Any] | None:
    for arm in arms:
        if arm["name"].lower() == name.lower():
            return arm
    return None


def _find_selected(arms: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    arms = list(arms)
    for arm in arms:
        if "selected" in arm["name"].lower():
            return arm
    for arm in arms:
        if arm["name"].lower() != "baseline":
            return arm
    return None


def _cluster_key(prereg: Mapping[str, Any]) -> str:
    key = prereg.get("cluster_key", "call_id")
    return key if isinstance(key, str) else "call_id"


def _n_calls(arms: Iterable[Mapping[str, Any]], prereg: Mapping[str, Any]) -> int:
    """Observed calls in this run; the pre-registered planned n is not evidence."""
    cluster_key = _cluster_key(prereg)
    best = 0
    for arm in arms:
        clusters = {row.get(cluster_key) for row in arm["rows"] if row.get(cluster_key) is not None}
        best = max(best, len(clusters))
    return best


def _term_level(arms: Iterable[Mapping[str, Any]]) -> dict:
    arms = list(arms)
    arm = _find_selected(arms) or (arms[0] if arms else None)
    if arm is None or not arm["rows"]:
        return {}
    rows = arm["rows"]
    out: dict[str, Any] = {"arm": arm["name"]}
    for metric, origin in _ORIGINS.items():
        subset = [
            row
            for row in rows
            if _row_origin(row) == origin and _in_denominator(row)
        ]
        if not subset:
            continue
        out[origin] = {
            "recovered": sum(1 for row in subset if _is_hit(row)),
            "lost": sum(1 for row in subset if not _is_hit(row)),
            "inserted": sum(
                1 for row in subset if any(row.get(flag) is True for flag in _INSERTION_FLAGS)
            ),
        }
    return out


def _lift_from(delta: Mapping[str, Any] | None) -> dict:
    if not delta or not delta.get("deltas"):
        return {}
    low = delta.get("ci_low")
    high = delta.get("ci_high")
    estimate = delta.get("mean")
    claimable = bool(_finite(low) and _finite(high) and float(low) > 0)
    return {
        "metric": delta.get("metric"),
        "estimate": estimate,
        "ci_low": low,
        "ci_high": high,
        "claimable": claimable,
    }


def _bound(delta: Mapping[str, Any], key: str) -> float:
    value = delta.get(key)
    return float(value) if _finite(value) else float("nan")


def verdict(
    report: Mapping[str, Any],
    *,
    recall_margin: float = -0.05,
    insertion_cap: float = 0.5,
) -> str:
    """Return PASS | FAIL | INCONCLUSIVE under the pre-registered rule.

    PASS needs the recall CI lower bound >= margin AND the insertion CI upper
    bound <= cap. The decision n is the minimum paired-call count across the two
    deltas; a pre-registered planned n is never treated as evidence. A
    missing/wide CI is INCONCLUSIVE, never PASS. One call is always
    INCONCLUSIVE.
    """
    prereg = report.get("prereg") or {}
    recall_margin = float(prereg.get("recall_margin", recall_margin))
    insertion_cap = float(prereg.get("insertion_cap", insertion_cap))

    paired = report.get("paired_deltas") or {}
    recall = paired.get("real_recall") or {}
    insertion = paired.get("insertions_per_utterance") or {}

    paired_counts = [recall.get("n"), insertion.get("n")]
    if not all(
        isinstance(count, int) and not isinstance(count, bool)
        for count in paired_counts
    ):
        return "INCONCLUSIVE"
    if min(paired_counts) < 2:
        return "INCONCLUSIVE"

    recall_low = _bound(recall, "ci_low")
    recall_high = _bound(recall, "ci_high")
    ins_low = _bound(insertion, "ci_low")
    ins_high = _bound(insertion, "ci_high")
    if not all(math.isfinite(x) for x in (recall_low, recall_high, ins_low, ins_high)):
        return "INCONCLUSIVE"

    max_width = prereg.get("max_ci_width")
    if _finite(max_width):
        width = float(max_width)
        if recall_high - recall_low > width or ins_high - ins_low > width:
            return "INCONCLUSIVE"

    if recall_low < recall_margin - 1e-12 or ins_high > insertion_cap + 1e-12:
        return "FAIL"
    return "PASS"


def _verdict_reason(report: Mapping[str, Any]) -> str:
    prereg = report.get("prereg") or {}
    margin = prereg.get("recall_margin", -0.05)
    cap = prereg.get("insertion_cap", 0.5)
    decision = report.get("verdict", "INCONCLUSIVE")
    if decision == "PASS":
        return (
            f"Real-term recall stayed non-inferior (CI lower bound >= {margin:+.2f}) and the "
            f"insertion CI upper bound stayed within the {cap:+.2f} cap."
        )
    if decision == "FAIL":
        return (
            f"The recall CI lower bound fell below the {margin:+.2f} margin or the insertion "
            f"CI upper bound exceeded the {cap:+.2f} cap."
        )
    return (
        "Fewer than two paired calls, or the pre-registered bounds were missing or too wide, "
        "so the non-inferiority rule cannot be decided."
    )


def build_report(
    *,
    call_id: Any,
    arms: Iterable[Mapping[str, Any]],
    provenance: Mapping[str, Any],
    prereg: Mapping[str, Any],
) -> dict:
    arms_list = [_normalize_arm(arm) for arm in (arms or [])]
    provenance = dict(provenance or {})
    prereg = dict(prereg or {})

    report: dict[str, Any] = {
        "call_id": call_id,
        "arms": arms_list,
        "provenance": provenance,
        "prereg": prereg,
        "metrics_summary": [_summarize_arm(arm) for arm in arms_list],
        "n_calls": _n_calls(arms_list, prereg),
        "paired_deltas": {},
        "term_level": _term_level(arms_list),
        "lift": {},
        "claims_register": {"verified": [], "inferred": [], "unverified": []},
        "disclosures": dict(_DEFAULT_DISCLOSURES),
    }

    baseline = _find_arm(arms_list, "baseline")
    selected = _find_selected(arms_list)
    if baseline and selected and baseline is not selected:
        cluster_key = _cluster_key(prereg)
        seed = prereg.get("seed", provenance.get("seed", 0))
        n_boot = prereg.get("n_boot", 10000)
        if not isinstance(seed, int) or isinstance(seed, bool):
            seed = 0
        if not isinstance(n_boot, int) or isinstance(n_boot, bool) or n_boot < 1:
            n_boot = 10000
        for metric in ("real_recall", "insertions_per_utterance"):
            delta = paired_delta(
                baseline["rows"],
                selected["rows"],
                metric,
                cluster_key=cluster_key,
                n_boot=n_boot,
                seed=seed,
            )
            if delta["deltas"]:
                delta["comparison"] = f"{selected['name']} vs {baseline['name']}"
                report["paired_deltas"][metric] = delta
        if report["paired_deltas"]:
            # Display the observed paired count, never the planned prereg n.
            report["n_calls"] = min(
                int(delta["n"]) for delta in report["paired_deltas"].values()
            )
        report["lift"] = _lift_from(report["paired_deltas"].get("real_recall"))

    report["verdict"] = verdict(report)
    report["verdict_reason"] = _verdict_reason(report)
    return report


def _rate_of(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("rate")
    return value if _finite(value) else None


def _fmt_count(value: Any) -> str:
    if not _finite(value):
        return "n/a"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _fmt_rate(value: Any) -> str:
    if not _finite(value):
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _fmt_signed(value: Any) -> str:
    if not _finite(value):
        return "n/a"
    return f"{float(value):+.3f}"


def _fmt_ci(delta: Mapping[str, Any]) -> str:
    low = delta.get("ci_low")
    high = delta.get("ci_high")
    if not (_finite(low) and _finite(high)):
        return "n/a"
    return f"[{float(low):+.3f}, {float(high):+.3f}]"


def _count_cell(value: Mapping[str, Any] | None, *, per_utterance: bool = False) -> str:
    if not isinstance(value, Mapping):
        return "n/a"
    num = value.get("num")
    den = value.get("den")
    rate = value.get("rate")
    if _finite(num) and _finite(den):
        if per_utterance:
            mean = f"{float(rate):.2f}" if _finite(rate) else "n/a"
            return f"{_fmt_count(num)}/{_fmt_count(den)} = {mean}"
        return f"{_fmt_count(num)}/{_fmt_count(den)} ({_fmt_rate(rate)})"
    if _finite(rate):
        return f"{_fmt_rate(rate)} (counts n/a)"
    return "n/a"


def _prettify(key: Any) -> str:
    return str(key).replace("_", " ").strip().capitalize()


def _fmt_provenance_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " -> ".join(str(item) for item in value)
    if isinstance(value, Mapping):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    return str(value)


def _render_provenance(provenance: Mapping[str, Any]) -> list[str]:
    order = (
        "model",
        "canon_version",
        "context_hash",
        "seed",
        "audio_hash",
        "audio_chain",
        "audio_processing_chain",
        "date",
        "generated_at",
    )
    lines = ["| Field | Value |", "|---|---|"]
    rendered: set[str] = set()
    for key in order:
        if key in provenance:
            lines.append(f"| {_prettify(key)} | {_fmt_provenance_value(provenance[key])} |")
            rendered.add(key)
    for key in sorted(provenance):
        if key not in rendered:
            lines.append(f"| {_prettify(key)} | {_fmt_provenance_value(provenance[key])} |")
    if len(lines) == 2:
        lines.append("| Recorded | none |")
    return lines


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the seven-section Keyterm Health Report."""
    call_id = report.get("call_id") or "unknown"
    prereg = report.get("prereg") or {}
    lines: list[str] = [
        f"# Keyterm Health Report - {call_id}",
        "",
        "**Internal harness validation - not for external distribution.**",
        "",
        "## 1. Provenance",
        "",
    ]
    lines.extend(_render_provenance(report.get("provenance") or {}))
    lines.extend(
        [
            "",
            "## 2. Results per arm",
            "",
            "| Arm | Real recall | Fictional recall | OOV recall | Insertions / utterance | WER | Decoder ignore |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for summary in report.get("metrics_summary") or []:
        lines.append(
            "| {arm} | {real} | {fiction} | {oov} | {ins} | {wer} | {dec} |".format(
                arm=summary.get("arm", "unknown"),
                real=_count_cell(summary.get("real_recall")),
                fiction=_count_cell(summary.get("fictional_recall")),
                oov=_count_cell(summary.get("oov_recall")),
                ins=_count_cell(summary.get("insertions_per_utterance"), per_utterance=True),
                wer=_fmt_rate(_rate_of(summary.get("wer"))),
                dec=_count_cell(summary.get("decoder_ignore")),
            )
        )
    if not report.get("metrics_summary"):
        lines.append("| none | n/a | n/a | n/a | n/a | n/a | n/a |")

    lines.extend(
        [
            "",
            "Decoder ignore is reported as numerator/denominator: spoken context "
            "terms still missed / spoken context terms.",
        ]
    )

    lines.extend(["", "### Paired deltas (95% CI)", ""])
    paired = report.get("paired_deltas") or {}
    if paired:
        lines.extend(
            [
                "| Comparison | Metric | Delta | 95% CI | Calls |",
                "|---|---|---|---|---|",
            ]
        )
        for metric, delta in paired.items():
            lines.append(
                f"| {delta.get('comparison', 'n/a')} | {metric} | "
                f"{_fmt_signed(delta.get('mean'))} | {_fmt_ci(delta)} | {delta.get('n', 0)} |"
            )
    else:
        lines.append("No paired deltas recorded for this run.")

    lines.extend(["", "## 3. Term-level appendix", ""])
    term_level = report.get("term_level") or {}
    itemised = [
        (origin, term_level[origin])
        for origin in ("real", "fictional", "oov")
        if isinstance(term_level.get(origin), Mapping)
    ]
    if itemised:
        if term_level.get("arm"):
            lines.extend([f"Arm: {term_level['arm']}", ""])
        lines.extend(
            [
                "| Origin | Recovered | Lost | Inserted |",
                "|---|---|---|---|",
            ]
        )
        for origin, counts in itemised:
            lines.append(
                f"| {origin} | {_fmt_count(counts.get('recovered'))} | "
                f"{_fmt_count(counts.get('lost'))} | {_fmt_count(counts.get('inserted'))} |"
            )
    else:
        lines.append("No term-level appendix recorded for this run.")

    lines.extend(["", "## 4. Verdict", ""])
    decision = report.get("verdict") or "INCONCLUSIVE"
    lines.append(f"**{decision}**")
    lines.append("")
    lines.append(
        report.get("verdict_reason")
        or "Non-inferiority rule not evaluable from this run."
    )
    lines.extend(
        [
            "",
            f"Rule: real-recall CI lower bound >= {float(prereg.get('recall_margin', -0.05)):+.2f} "
            f"and insertions-per-utterance CI upper bound <= "
            f"{float(prereg.get('insertion_cap', 0.5)):+.2f}.",
            "A wide or missing CI yields INCONCLUSIVE, never PASS.",
        ]
    )

    lines.extend(["", "## 5. Descriptive lift (secondary)", ""])
    lift = report.get("lift") or {}
    if lift:
        interpretation = (
            "CI excludes zero; descriptive only, not a causal claim."
            if lift.get("claimable")
            else "CI includes zero; no lift is claimed."
        )
        lines.extend(
            [
                "| Metric | Estimate | 95% CI | Reading |",
                "|---|---|---|---|",
                f"| {lift.get('metric', 'real_recall')} | {_fmt_signed(lift.get('estimate'))} | "
                f"{_fmt_ci(lift)} | {interpretation} |",
            ]
        )
    else:
        lines.append("No paired lift estimate recorded; lift is not claimed.")

    lines.extend(["", "## 6. Claims register", ""])
    claims = report.get("claims_register") or {}
    for key, title in (
        ("verified", "Verified"),
        ("inferred", "Inferred"),
        ("unverified", "Unverified"),
    ):
        lines.extend([f"### {title}", ""])
        entries = claims.get(key) or []
        if entries:
            lines.extend(f"- {entry}" for entry in entries)
        else:
            lines.append("- None recorded.")
        lines.append("")

    lines.extend(["## 7. Synthetic-audio and circularity disclosure", ""])
    disclosures = report.get("disclosures") or _DEFAULT_DISCLOSURES
    lines.extend(["### Synthetic audio", "", disclosures.get("synthetic_audio", ""), ""])
    lines.extend(["### Circularity", "", disclosures.get("circularity", ""), ""])

    return "\n".join(lines).rstrip() + "\n"
