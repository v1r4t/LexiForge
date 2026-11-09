"""Pre-registered confirmatory analysis for H1 and H2 (design §6-§7).

The closed confirmatory family is exactly two directional, paired,
call-clustered tests:

* **H1** - ``mismatched-200 < baseline`` on real-term recall
  (``alternative="less"``).
* **H2** - ``mismatched-200 > baseline`` on glossary-term insertions per
  utterance (``alternative="greater"``).

Holm runs over the two raw permutation p-values at alpha 0.05, so the
smallest is tested at 0.025 and the second at 0.05 (preregistration §4).
The positive control ``oracle-200 - mismatched-200`` sits outside the family:
it gets a cluster-bootstrap CI and never a p-value. A flat or inverted
control means the harness, not the model, is the finding, so the claim ladder
drops to ``harness only`` (preregistration §2, §8).

Input is per-call aggregates keyed by arm::

    {"baseline": [{"call_id": "c01", "real_recall": {"num": 9, "den": 10},
                   "insertions_per_utterance": {"num": 0, "den": 5}}, ...],
     "mismatched-200": [...], "oracle-200": [...]}

Rows may instead nest the metrics under ``"metrics"``, and an arm may be a
mapping of cluster id to row. Counts are pooled within a call before any
per-call rate is formed; a call with a non-finite value on either side is
dropped as a pair, never silently sign-flipped as a lone NaN.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

import numpy as np

from lexiforge.analysis.inference import (
    cluster_bootstrap_ci,
    holm,
    mde,
    sign_flip_test,
)

__all__ = ["analyse_h1_h2"]

_METRIC_ALIASES = {
    "real_recall": ("real_recall", "real_term_recall"),
    "insertions_per_utterance": (
        "insertions_per_utterance",
        "insertions_utterance",
        "insertions_per_utt",
    ),
}

_COUNT_PAIRS = (
    ("num", "den"),
    ("numerator", "denominator"),
    ("n", "d"),
)

_SCALAR_KEYS = ("rate", "mean", "value")

_ALPHA = 0.05
_MDE_ALPHA = 0.025
_POWER = 0.8


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _aliases(metric: str) -> tuple[str, ...]:
    return _METRIC_ALIASES.get(metric, (metric,))


def _lookup(row: Mapping[str, Any], metric: str) -> Any:
    containers = [row]
    nested = row.get("metrics")
    if isinstance(nested, Mapping):
        containers.append(nested)
    for container in containers:
        for alias in _aliases(metric):
            value = container.get(alias)
            if value is not None:
                return value
    return None


def _as_counts(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, Mapping):
        return None
    for num_key, den_key in _COUNT_PAIRS:
        if num_key in value and den_key in value:
            try:
                return float(value[num_key]), float(value[den_key])
            except (TypeError, ValueError):
                return None
    if "total_events" in value and "n_utterances" in value:
        try:
            return float(value["total_events"]), float(value["n_utterances"])
        except (TypeError, ValueError):
            return None
    return None


def _cluster_value(rows: Iterable[Mapping[str, Any]], metric: str) -> float:
    """Pool a call's rows into one rate, or NaN when any value is non-finite."""
    num_total = 0.0
    den_total = 0.0
    has_counts = False
    scalars: list[float] = []
    saw_non_finite = False

    for row in rows:
        raw = _lookup(row, metric)
        if raw is None:
            continue
        counts = _as_counts(raw)
        if counts is not None:
            num, den = counts
            if _finite(num) and _finite(den) and den > 0:
                num_total += num
                den_total += den
                has_counts = True
            else:
                saw_non_finite = True
            continue
        if isinstance(raw, Mapping):
            found = False
            for key in _SCALAR_KEYS:
                if key in raw:
                    found = True
                    if _finite(raw[key]):
                        scalars.append(float(raw[key]))
                    else:
                        saw_non_finite = True
                    break
            if not found:
                saw_non_finite = True
            continue
        if _finite(raw):
            scalars.append(float(raw))
        else:
            saw_non_finite = True

    if saw_non_finite:
        return float("nan")
    if has_counts and den_total > 0:
        return num_total / den_total
    if scalars:
        return float(np.mean(scalars))
    return float("nan")


def _normalise_name(name: Any) -> str:
    return str(name).strip().lower().replace("_", "-")


def _normalise_rows(payload: Any, cluster_key: str) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        if (
            cluster_key in payload
            or "metrics" in payload
            or any(alias in payload for aliases in _METRIC_ALIASES.values() for alias in aliases)
        ):
            return [dict(payload)]
        rows: list[dict[str, Any]] = []
        for cluster in sorted(payload, key=lambda item: (type(item).__name__, repr(item))):
            item = payload[cluster]
            if isinstance(item, Mapping):
                row = dict(item)
                row.setdefault(cluster_key, cluster)
                rows.append(row)
        return rows
    if payload is None:
        return []
    return [dict(row) for row in payload if isinstance(row, Mapping)]


def _arm_rows(
    per_call_by_arm: Mapping[str, Any], wanted: str, cluster_key: str
) -> list[dict[str, Any]]:
    exact = _normalise_name(wanted)
    available = {_normalise_name(name): name for name in per_call_by_arm}
    key = available.get(exact)
    if key is None:
        for candidate in sorted(per_call_by_arm, key=lambda item: str(item)):
            if _normalise_name(candidate).startswith(exact):
                key = candidate
                break
    if key is None:
        return []
    return _normalise_rows(per_call_by_arm[key], cluster_key)


def _values_by_cluster(
    rows: Iterable[Mapping[str, Any]], metric: str, cluster_key: str
) -> dict[Any, float]:
    grouped: dict[Any, list[Mapping[str, Any]]] = {}
    for row in rows:
        cluster = row.get(cluster_key)
        if cluster is None:
            continue
        grouped.setdefault(cluster, []).append(row)
    return {cluster: _cluster_value(group, metric) for cluster, group in grouped.items()}


def _delta_clusters(
    a_rows: Iterable[Mapping[str, Any]],
    b_rows: Iterable[Mapping[str, Any]],
    metric: str,
    cluster_key: str,
) -> tuple[list[float], list[Any]]:
    """Paired ``b - a`` deltas; a non-finite value on either side drops the pair."""
    values_a = _values_by_cluster(a_rows, metric, cluster_key)
    values_b = _values_by_cluster(b_rows, metric, cluster_key)
    shared = [cluster for cluster in values_a if cluster in values_b]
    shared.sort(key=lambda item: (type(item).__name__, repr(item)))

    deltas: list[float] = []
    clusters: list[Any] = []
    for cluster in shared:
        value_a = values_a[cluster]
        value_b = values_b[cluster]
        if _finite(value_a) and _finite(value_b):
            deltas.append(float(value_b) - float(value_a))
            clusters.append(cluster)
    return deltas, clusters


def _mean_or_none(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _se(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return float(np.std(values, ddof=1) / math.sqrt(len(values)))


def _test_block(
    hypothesis: str,
    *,
    metric: str,
    comparison: str,
    alternative: str,
    deltas: list[float],
    clusters: list[Any],
    n_permutations: int,
    seed: int,
) -> dict[str, Any]:
    mean = _mean_or_none(deltas)
    block: dict[str, Any] = {
        "hypothesis": hypothesis,
        "metric": metric,
        "comparison": comparison,
        "alternative": alternative,
        "deltas": [float(delta) for delta in deltas],
        "clusters": list(clusters),
        "n": len(deltas),
        "mean": mean,
        "ci_low": None,
        "ci_high": None,
        "p_value": None,
        "direction_ok": False,
        "rejected": False,
        "decision": "INCONCLUSIVE",
    }
    if mean is not None:
        block["direction_ok"] = mean < 0 if alternative == "less" else mean > 0
    if len(deltas) < 2:
        # Two calls are the floor for any inference; one call is descriptive only.
        return block

    ci = cluster_bootstrap_ci(deltas, statistic=np.mean, n_boot=n_permutations, seed=seed)
    test = sign_flip_test(
        deltas,
        alternative=alternative,
        n_permutations=n_permutations,
        seed=seed,
    )
    block["ci_low"] = float(ci["ci_low"])
    block["ci_high"] = float(ci["ci_high"])
    block["p_value"] = float(test["p_value"])
    block["decision"] = "NOT REJECTED"
    return block


def _mde_block(
    deltas_by_metric: Mapping[str, list[float]],
) -> dict[str, Any]:
    out: dict[str, Any] = {"alpha": _MDE_ALPHA, "power": _POWER}
    for metric, deltas in deltas_by_metric.items():
        se = _se(deltas)
        out[metric] = {
            "n": len(deltas),
            "se": se,
            "value": None if se is None else float(mde(se, alpha=_MDE_ALPHA, power=_POWER)),
        }
    return out


def _claim_ladder(
    h1: Mapping[str, Any], h2: Mapping[str, Any], positive_control: Mapping[str, Any]
) -> str:
    control_testable = bool(
        positive_control.get("available") and positive_control.get("n", 0) >= 2
    )
    if control_testable and not positive_control.get("passed"):
        return "harness only"
    if h1.get("rejected") and h2.get("rejected"):
        return "H1+H2"
    if h2.get("rejected"):
        return "H2 alone"
    if h1.get("rejected"):
        return "H1 alone"
    if not h1.get("n") and not h2.get("n"):
        return "harness only"
    return "mechanism only"


def analyse_h1_h2(
    per_call_by_arm: Mapping[str, Any],
    *,
    cluster_key: str = "call_id",
    n_permutations: int = 10000,
    seed: int = 0,
) -> dict[str, Any]:
    """Run the two pre-registered directional tests and Holm-correct them.

    ``per_call_by_arm`` is a mapping of arm name to per-call aggregate rows.
    Counts are pooled within a call; a call missing or carrying a non-finite
    value on either arm is dropped as a whole pair before the sign-flip
    permutation (which would otherwise drop one side silently).

    Returns ``h1``, ``h2``, ``holm``, ``positive_control``, ``mde``,
    ``claim_ladder`` and the observed ``n_calls``. No planned sample size is
    ever substituted for an observed one, and fewer than two paired calls is
    ``INCONCLUSIVE``.
    """
    if not isinstance(per_call_by_arm, Mapping):
        raise TypeError("per_call_by_arm must be a mapping of arm name to rows")
    if not isinstance(n_permutations, int) or isinstance(n_permutations, bool):
        raise TypeError("n_permutations must be an integer")
    if n_permutations < 1:
        raise ValueError("n_permutations must be >= 1")

    baseline = _arm_rows(per_call_by_arm, "baseline", cluster_key)
    mismatched = _arm_rows(per_call_by_arm, "mismatched-200", cluster_key)
    oracle = _arm_rows(per_call_by_arm, "oracle-200", cluster_key)

    real_deltas, real_clusters = _delta_clusters(
        baseline, mismatched, "real_recall", cluster_key
    )
    insertion_deltas, insertion_clusters = _delta_clusters(
        baseline, mismatched, "insertions_per_utterance", cluster_key
    )

    h1 = _test_block(
        "H1",
        metric="real_recall",
        comparison="mismatched-200 - baseline",
        alternative="less",
        deltas=real_deltas,
        clusters=real_clusters,
        n_permutations=n_permutations,
        seed=seed,
    )
    h2 = _test_block(
        "H2",
        metric="insertions_per_utterance",
        comparison="mismatched-200 - baseline",
        alternative="greater",
        deltas=insertion_deltas,
        clusters=insertion_clusters,
        n_permutations=n_permutations,
        seed=seed,
    )

    raw_p = {
        "H1": h1["p_value"] if h1["p_value"] is not None else 1.0,
        "H2": h2["p_value"] if h2["p_value"] is not None else 1.0,
    }
    stepdown = holm(raw_p, alpha=_ALPHA)
    holm_rejected: dict[str, bool] = {}
    for name, block in (("H1", h1), ("H2", h2)):
        # Rejection needs both the Holm step and the pre-stated direction.
        rejected = bool(stepdown["rejected"][name] and block["direction_ok"])
        block["rejected"] = rejected
        if block["p_value"] is None:
            block["decision"] = "INCONCLUSIVE"
        elif rejected:
            block["decision"] = "REJECT"
        else:
            block["decision"] = "NOT REJECTED"
        holm_rejected[name] = rejected

    family_size = len(raw_p)
    thresholds = [
        round(_ALPHA / (family_size - rank), 10) for rank in range(family_size)
    ]
    holm_block = {
        "family": ["H1", "H2"],
        "m": family_size,
        "alpha": _ALPHA,
        "thresholds": thresholds,
        "raw": raw_p,
        "adjusted": stepdown["adjusted"],
        "stepdown_rejected": stepdown["rejected"],
        "rejected": holm_rejected,
    }

    control_deltas, _control_clusters = _delta_clusters(
        mismatched, oracle, "real_recall", cluster_key
    )
    control_mean = _mean_or_none(control_deltas)
    positive_control: dict[str, Any] = {
        "contrast": "oracle-200 - mismatched-200",
        "metric": "real_recall",
        "available": bool(oracle),
        "n": len(control_deltas),
        "mean": control_mean,
        "ci_low": None,
        "ci_high": None,
        "direction_ok": bool(control_mean is not None and control_mean > 0),
        "passed": False,
    }
    if len(control_deltas) >= 2:
        ci = cluster_bootstrap_ci(
            control_deltas, statistic=np.mean, n_boot=n_permutations, seed=seed
        )
        positive_control["ci_low"] = float(ci["ci_low"])
        positive_control["ci_high"] = float(ci["ci_high"])
    positive_control["passed"] = bool(
        positive_control["available"]
        and len(control_deltas) >= 2
        and positive_control["direction_ok"]
    )

    result: dict[str, Any] = {
        "h1": h1,
        "h2": h2,
        "holm": holm_block,
        "positive_control": positive_control,
        "mde": _mde_block(
            {
                "real_recall": real_deltas,
                "insertions_per_utterance": insertion_deltas,
            }
        ),
        "n_calls": len(real_deltas),
        "n_calls_by_metric": {
            "real_recall": len(real_deltas),
            "insertions_per_utterance": len(insertion_deltas),
        },
        "cluster_key": cluster_key,
        "n_permutations": n_permutations,
        "seed": seed,
    }
    result["claim_ladder"] = _claim_ladder(h1, h2, positive_control)
    return result
