"""Tests for the pre-registered H1/H2 analysis (design §6; prereg §3-§4)."""

from __future__ import annotations

import json
import math

import pytest

from lexiforge.analysis import preregistered
from lexiforge.analysis.inference import mde
from lexiforge.analysis.preregistered import analyse_h1_h2


def _call(call_id, *, real=(9, 10), ins=(0, 5)):
    """One per-call aggregate row in the pilot's on-disk shape."""
    return {
        "call_id": call_id,
        "real_recall": {"num": real[0], "den": real[1]},
        "insertions_per_utterance": {"num": ins[0], "den": ins[1]},
    }


def _arms(real_deltas, ins_deltas, *, oracle_extra=0.3):
    """Build baseline/mismatched/oracle rows with the requested per-call deltas."""
    baseline, mismatched, oracle = [], [], []
    for index, (d_real, d_ins) in enumerate(zip(real_deltas, ins_deltas, strict=True)):
        call_id = f"c{index:02d}"
        base_real = (9, 10)
        mis_real = (9 + round(d_real * 10), 10)
        oracle_real = (min(10, mis_real[0] + round(oracle_extra * 10)), 10)
        base_ins = (0, 5)
        mis_ins = (round(d_ins * 5), 5)
        baseline.append(_call(call_id, real=base_real, ins=base_ins))
        mismatched.append(_call(call_id, real=mis_real, ins=mis_ins))
        oracle.append(_call(call_id, real=oracle_real, ins=(0, 5)))
    return {
        "baseline": baseline,
        "mismatched-200": mismatched,
        "oracle-200": oracle,
    }


def _json_ready(result):
    return json.dumps(result, sort_keys=True, allow_nan=False)


def test_h1_h2_reject_and_claim_both():
    arms = _arms([-0.2] * 8, [0.2] * 8, oracle_extra=0.3)
    result = analyse_h1_h2(arms, n_permutations=2000, seed=0)

    assert result["h1"]["metric"] == "real_recall"
    assert result["h1"]["alternative"] == "less"
    assert result["h1"]["mean"] == pytest.approx(-0.2)
    assert result["h1"]["rejected"] is True
    assert result["h2"]["alternative"] == "greater"
    assert result["h2"]["mean"] == pytest.approx(0.2)
    assert result["h2"]["rejected"] is True
    assert result["holm"]["rejected"] == {"H1": True, "H2": True}
    assert result["n_calls"] == 8
    assert result["claim_ladder"] == "H1+H2"


def test_inverted_delta_cannot_reject():
    # H1 moves the wrong way (recall rises) and H2 moves the wrong way; the
    # oracle still beats mismatched, so the ladder failure is not the control.
    baseline = [_call(f"c{index:02d}", real=(5, 10), ins=(2, 5)) for index in range(6)]
    mismatched = [_call(f"c{index:02d}", real=(6, 10), ins=(0, 5)) for index in range(6)]
    oracle = [_call(f"c{index:02d}", real=(8, 10), ins=(0, 5)) for index in range(6)]
    arms = {"baseline": baseline, "mismatched-200": mismatched, "oracle-200": oracle}
    result = analyse_h1_h2(arms, n_permutations=2000, seed=0)

    assert result["h1"]["mean"] > 0
    assert result["h1"]["direction_ok"] is False
    assert result["h1"]["rejected"] is False
    assert result["h2"]["mean"] < 0
    assert result["h2"]["direction_ok"] is False
    assert result["h2"]["rejected"] is False
    assert result["claim_ladder"] == "mechanism only"


def test_holm_uses_0025_then_005(monkeypatch):
    # 0.03 is above the smallest-test threshold of 0.025, so the family stops.
    def fake_test(deltas, *, alternative, n_permutations=10000, seed=0):
        p = 0.03 if alternative == "less" else 0.06
        return {"p_value": p, "statistic": 0.0, "n": len(deltas)}

    monkeypatch.setattr(preregistered, "sign_flip_test", fake_test)
    arms = _arms([-0.2] * 6, [0.2] * 6)
    result = analyse_h1_h2(arms, n_permutations=100)

    assert result["holm"]["thresholds"] == [0.025, 0.05]
    assert result["holm"]["rejected"] == {"H1": False, "H2": False}
    assert result["claim_ladder"] == "mechanism only"


def test_holm_second_test_survives_below_005(monkeypatch):
    def fake_test(deltas, *, alternative, n_permutations=10000, seed=0):
        p = 0.01 if alternative == "less" else 0.049
        return {"p_value": p, "statistic": 0.0, "n": len(deltas)}

    monkeypatch.setattr(preregistered, "sign_flip_test", fake_test)
    arms = _arms([-0.2] * 6, [0.2] * 6)
    result = analyse_h1_h2(arms, n_permutations=100)

    assert result["holm"]["rejected"] == {"H1": True, "H2": True}
    assert result["claim_ladder"] == "H1+H2"


def test_holm_second_test_stops_above_005(monkeypatch):
    def fake_test(deltas, *, alternative, n_permutations=10000, seed=0):
        p = 0.01 if alternative == "less" else 0.051
        return {"p_value": p, "statistic": 0.0, "n": len(deltas)}

    monkeypatch.setattr(preregistered, "sign_flip_test", fake_test)
    arms = _arms([-0.2] * 6, [0.2] * 6)
    result = analyse_h1_h2(arms, n_permutations=100)

    assert result["holm"]["rejected"] == {"H1": True, "H2": False}
    assert result["claim_ladder"] == "H1 alone"


def test_two_calls_is_the_floor_but_one_is_inconclusive():
    two = analyse_h1_h2(_arms([-0.2, -0.3], [0.2, 0.4]), n_permutations=500, seed=0)
    assert two["n_calls"] == 2
    assert two["h1"]["p_value"] is not None
    assert two["h1"]["decision"] == "NOT REJECTED"
    assert two["h2"]["decision"] == "NOT REJECTED"

    one = analyse_h1_h2(_arms([-0.2], [0.2]), n_permutations=500, seed=0)
    assert one["n_calls"] == 1
    assert one["h1"]["p_value"] is None
    assert one["h1"]["decision"] == "INCONCLUSIVE"
    assert one["h2"]["decision"] == "INCONCLUSIVE"
    assert one["holm"]["rejected"] == {"H1": False, "H2": False}


def test_nan_call_drops_the_whole_pair_and_output_is_json_safe():
    arms = _arms([-0.2] * 5, [0.2] * 5)
    arms["mismatched-200"][2]["real_recall"]["num"] = float("nan")
    arms["baseline"][3]["insertions_per_utterance"]["num"] = float("nan")

    result = analyse_h1_h2(arms, n_permutations=500, seed=0)
    assert result["h1"]["n"] == 4
    assert "c02" not in result["h1"]["clusters"]
    assert all(math.isfinite(delta) for delta in result["h1"]["deltas"])
    assert result["h2"]["n"] == 4
    assert "c03" not in result["h2"]["clusters"]
    assert all(math.isfinite(delta) for delta in result["h2"]["deltas"])
    _json_ready(result)


def test_positive_control_has_ci_and_no_p_value():
    arms = _arms([-0.2] * 6, [0.2] * 6, oracle_extra=0.4)
    result = analyse_h1_h2(arms, n_permutations=1000, seed=0)

    control = result["positive_control"]
    assert control["available"] is True
    assert control["n"] == 6
    assert control["mean"] > 0
    assert control["ci_low"] is not None
    assert control["ci_high"] is not None
    assert "p_value" not in control
    assert "p" not in control


def test_failed_positive_control_forces_harness_only():
    # Oracle is no better than mismatched: the pipeline cannot be trusted.
    arms = _arms([-0.2] * 6, [0.2] * 6, oracle_extra=0.0)
    result = analyse_h1_h2(arms, n_permutations=1000, seed=0)

    assert result["positive_control"]["passed"] is False
    assert result["claim_ladder"] == "harness only"


def test_missing_positive_control_is_reported_not_invented():
    arms = _arms([-0.2] * 6, [0.2] * 6)
    arms.pop("oracle-200")
    result = analyse_h1_h2(arms, n_permutations=500, seed=0)

    control = result["positive_control"]
    assert control["available"] is False
    assert control["n"] == 0
    assert "p_value" not in control


def test_deterministic_seed():
    arms = _arms([-0.2, -0.1, -0.3, -0.2, -0.1], [0.2, 0.4, 0.2, 0.2, 0.4])
    first = analyse_h1_h2(arms, n_permutations=1000, seed=7)
    second = analyse_h1_h2(arms, n_permutations=1000, seed=7)

    assert _json_ready(first) == _json_ready(second)
    assert first["holm"]["thresholds"] == [0.025, 0.05]
    assert first["mde"]["real_recall"]["se"] > 0
    assert first["mde"]["real_recall"]["value"] == pytest.approx(
        mde(first["mde"]["real_recall"]["se"], alpha=0.025, power=0.8)
    )


def test_nested_metrics_and_cluster_mapping_input():
    arms = {
        "baseline": {
            "c01": {"metrics": {"real_recall": {"num": 9, "den": 10},
                                "insertions_per_utterance": {"num": 0, "den": 5}}},
            "c02": {"metrics": {"real_recall": {"num": 9, "den": 10},
                                "insertions_per_utterance": {"num": 0, "den": 5}}},
        },
        "mismatched-200": {
            "c01": {"metrics": {"real_recall": {"num": 7, "den": 10},
                                "insertions_per_utterance": {"num": 1, "den": 5}}},
            "c02": {"metrics": {"real_recall": {"num": 6, "den": 10},
                                "insertions_per_utterance": {"num": 2, "den": 5}}},
        },
    }
    result = analyse_h1_h2(arms, n_permutations=100, seed=0)
    assert result["n_calls"] == 2
    assert result["h1"]["mean"] == pytest.approx(-0.25)
    assert result["h2"]["mean"] == pytest.approx(0.3)


def test_missing_mismatched_arm_is_inconclusive_not_an_error():
    arms = {"baseline": [_call("c01"), _call("c02")]}
    result = analyse_h1_h2(arms, n_permutations=100, seed=0)
    assert result["n_calls"] == 0
    assert result["h1"]["decision"] == "INCONCLUSIVE"
    assert result["h2"]["decision"] == "INCONCLUSIVE"
    assert result["holm"]["rejected"] == {"H1": False, "H2": False}


def test_cli_writes_utf8_analysis_artifact(tmp_path):
    from scripts.analyse_preregistered import main

    arms = _arms([-0.2, -0.3], [0.2, 0.4])
    source = tmp_path / "per-call.json"
    source.write_text(json.dumps(arms), encoding="utf-8")
    out = tmp_path / "analysis" / "preregistered.json"

    assert main([str(source), "--out", str(out), "--n-permutations", "100", "--seed", "0"]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert set(written) >= {
        "h1",
        "h2",
        "holm",
        "positive_control",
        "mde",
        "claim_ladder",
        "n_calls",
    }
    assert written["n_calls"] == 2
    assert "p_value" not in written["positive_control"]

