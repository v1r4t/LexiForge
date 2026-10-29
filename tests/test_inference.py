"""Tests for lexiforge.analysis.inference (§6)."""

import numpy as np

from lexiforge.analysis.inference import (
    cluster_bootstrap_ci,
    holm,
    mde,
    sign_flip_test,
    wild_cluster_bootstrap_t,
)


def test_holm_rejects_both():
    out = holm({"H1": 0.01, "H2": 0.04}, alpha=0.05)
    assert out["rejected"] == {"H1": True, "H2": True}


def test_holm_rejects_none():
    out = holm({"H1": 0.03, "H2": 0.6}, alpha=0.05)
    assert out["rejected"] == {"H1": False, "H2": False}


def test_sign_flip_all_positive_less_gives_one():
    rng = np.random.default_rng(42)
    deltas = rng.uniform(0.01, 0.2, size=20)  # all positive
    out = sign_flip_test(deltas, alternative="less", n_permutations=10000, seed=0)
    assert out["p_value"] == 1.0
    assert out["n"] == 20


def test_mde_increases_with_se():
    assert mde(0.02) > mde(0.01) > mde(0.0) == 0.0


def test_bootstrap_ci_contains_mean():
    rng = np.random.default_rng(7)
    values = rng.normal(loc=0.5, scale=0.1, size=20)
    out = cluster_bootstrap_ci(values, n_boot=10000, seed=0)
    assert out["ci_low"] <= float(np.mean(values)) <= out["ci_high"]


def test_wild_cluster_bootstrap_t_smoke():
    rng = np.random.default_rng(11)
    deltas = rng.normal(loc=-0.1, scale=0.05, size=20)
    out = wild_cluster_bootstrap_t(deltas, n_boot=999, seed=0)
    assert 0.0 <= out["p_value"] <= 1.0
    assert np.isfinite(out["t_observed"])
    assert out["t_observed"] < 0
