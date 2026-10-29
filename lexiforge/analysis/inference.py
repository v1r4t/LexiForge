"""Cluster-aware inference for LexiForge (§6).

Primary inference is a paired sign-flip permutation across conversations
(design-based: mismatched-domain assignment was seeded per call). The wild
cluster bootstrap-t is a cross-check; on disagreement the permutation governs.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

__all__ = [
    "sign_flip_test",
    "holm",
    "cluster_bootstrap_ci",
    "wild_cluster_bootstrap_t",
    "mde",
]


def sign_flip_test(deltas, *, alternative="less", n_permutations=10000, seed=0) -> dict:
    """Paired sign-flip permutation test across conversations.

    ``deltas`` are per-conversation paired differences. The statistic is the
    mean; ``alternative="less"`` tests that it is negative.
    """
    if alternative not in ("less", "greater", "two-sided"):
        raise ValueError(f"alternative must be 'less', 'greater' or 'two-sided', got {alternative!r}.")
    if n_permutations < 1:
        raise ValueError("n_permutations must be >= 1.")
    arr = np.asarray(deltas, dtype=float).ravel()
    arr = arr[~np.isnan(arr)]
    n = int(arr.size)
    if n == 0:
        raise ValueError("deltas is empty.")
    observed = float(np.mean(arr))
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(int(n_permutations), n))
    perm_stats = (signs * arr).mean(axis=1)
    if alternative == "less":
        count = int(np.sum(perm_stats <= observed))
    elif alternative == "greater":
        count = int(np.sum(perm_stats >= observed))
    else:
        count = int(np.sum(np.abs(perm_stats) >= abs(observed)))
    p_value = (count + 1) / (int(n_permutations) + 1)
    return {
        "statistic": observed,
        "p_value": float(p_value),
        "n": n,
        "n_permutations": int(n_permutations),
        "alternative": alternative,
    }


def holm(p_values: dict, alpha=0.05) -> dict:
    """Stepwise Holm procedure over a family of p-values.

    Sorts ascending and compares the smallest to ``alpha / m``, proceeding
    only while rejecting. Returns Holm-adjusted p-values and reject flags.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1).")
    keys = list(p_values.keys())
    raw = np.array([float(p_values[k]) for k in keys], dtype=float)
    if np.any(~np.isfinite(raw)) or np.any(raw < 0) or np.any(raw > 1):
        raise ValueError("p-values must be finite and in [0, 1].")
    m = len(keys)
    if m == 0:
        empty: dict = {}
        return {
            "adjusted": empty,
            "adjusted_p_values": empty,
            "rejected": empty,
            "alpha": float(alpha),
        }
    order = np.argsort(raw, kind="stable")
    rejected = {k: False for k in keys}
    for rank, idx in enumerate(order):
        threshold = alpha / (m - rank)
        if raw[idx] <= threshold:
            rejected[keys[idx]] = True
        else:
            break  # stepwise: stop at the first non-rejection
    # Holm-adjusted p-values with monotonicity enforced outward from smallest.
    adj_ordered = np.minimum(raw[order] * (m - np.arange(m)), 1.0)
    adj_ordered = np.maximum.accumulate(adj_ordered)
    adjusted = {keys[order[i]]: float(adj_ordered[i]) for i in range(m)}
    return {
        "adjusted": adjusted,
        "adjusted_p_values": adjusted,
        "adjusted_pvalues": adjusted,
        "rejected": rejected,
        "reject": rejected,
        "alpha": float(alpha),
    }


def cluster_bootstrap_ci(values, *, statistic=np.mean, n_boot=10000, seed=0) -> dict:
    """Percentile bootstrap CI resampling whole conversations.

    Resamples ``values`` (one entry per conversation) with replacement and
    reports the 2.5/97.5 percentiles of the bootstrapped statistic.
    """
    if n_boot < 1:
        raise ValueError("n_boot must be >= 1.")
    arr = np.asarray(values, dtype=float).ravel()
    arr = arr[~np.isnan(arr)]
    n = int(arr.size)
    if n == 0:
        raise ValueError("values is empty.")
    observed = float(statistic(arr))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(int(n_boot), n))
    sample = arr[idx]
    try:
        boot = np.asarray(statistic(sample, axis=1), dtype=float)
        if boot.shape != (int(n_boot),):
            raise ValueError
    except TypeError:
        boot = np.array([float(statistic(row)) for row in sample], dtype=float)
    ci_low, ci_high = (float(v) for v in np.percentile(boot, [2.5, 97.5]))
    return {
        "statistic": observed,
        "observed": observed,
        "estimate": observed,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "low": ci_low,
        "high": ci_high,
        "lower": ci_low,
        "upper": ci_high,
        "n": n,
        "n_boot": int(n_boot),
    }


def _studentise(mean, se) -> float:
    if se == 0 or not np.isfinite(se):
        if mean == 0:
            return 0.0
        return float(np.copysign(np.inf, mean))
    return float(mean / se)


def wild_cluster_bootstrap_t(deltas_by_cluster, n_boot=9999, seed=0) -> dict:
    """Wild cluster bootstrap-t with Rademacher weights (two-sided).

    Accepts either a 1-D array of per-cluster deltas or a mapping of
    cluster id to item-level values (each cluster reduced to its mean).
    Studentised with the cluster-robust SE; on disagreement with the
    sign-flip permutation, the permutation governs (§6).
    """
    if isinstance(deltas_by_cluster, dict):
        if len(deltas_by_cluster) == 0:
            raise ValueError("deltas_by_cluster is empty.")
        arr = np.array(
            [float(np.nanmean(np.asarray(v, dtype=float))) for v in deltas_by_cluster.values()],
            dtype=float,
        )
    else:
        arr = np.asarray(deltas_by_cluster, dtype=float).ravel()
        arr = arr[~np.isnan(arr)]
    n = int(arr.size)
    if n < 2:
        raise ValueError("need at least 2 clusters for the bootstrap-t.")
    if n_boot < 1:
        raise ValueError("n_boot must be >= 1.")
    mean_obs = float(np.mean(arr))
    se_obs = float(np.std(arr, ddof=1) / np.sqrt(n))
    t_obs = _studentise(mean_obs, se_obs)
    rng = np.random.default_rng(seed)
    weights = rng.choice([-1.0, 1.0], size=(int(n_boot), n))
    flipped = weights * arr
    boot_means = flipped.mean(axis=1)
    boot_ses = flipped.std(axis=1, ddof=1) / np.sqrt(n)
    with np.errstate(divide="ignore", invalid="ignore"):
        t_boot = np.where(
            boot_ses == 0,
            np.where(boot_means == 0, 0.0, np.copysign(np.inf, boot_means)),
            boot_means / np.where(boot_ses == 0, 1.0, boot_ses),
        ).astype(float)
    p_value = (int(np.sum(np.abs(t_boot) >= abs(t_obs))) + 1) / (int(n_boot) + 1)
    return {
        "t_observed": float(t_obs),
        "t_obs": float(t_obs),
        "p_value": float(p_value),
        "p": float(p_value),
        "n": n,
        "n_boot": int(n_boot),
    }


def mde(se, alpha=0.025, power=0.8) -> float:
    """Minimum detectable effect for a given standard error."""
    se = float(se)
    if se < 0:
        raise ValueError("se must be >= 0.")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1).")
    if not 0 < power < 1:
        raise ValueError("power must be in (0, 1).")
    return float((norm.ppf(1 - alpha) + norm.ppf(power)) * se)
