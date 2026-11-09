from __future__ import annotations

import pytest

from lexiforge.report.keyterm_health import (
    build_report,
    paired_delta,
    render_markdown,
    verdict,
)


def _make_arm(name: str, metrics: dict) -> dict:
    return {"name": name, "metrics": metrics}


def _report_with_bounds(recall_ci, insertion_ci, *, n=4, prereg=None) -> dict:
    return {
        "call_id": "c1",
        "n_calls": n,
        "prereg": prereg or {},
        "paired_deltas": {
            "real_recall": {"ci_low": recall_ci[0], "ci_high": recall_ci[1], "n": n},
            "insertions_per_utterance": {
                "ci_low": insertion_ci[0],
                "ci_high": insertion_ci[1],
                "n": n,
            },
        },
    }


def test_paired_delta_reduces_to_one_value_per_call() -> None:
    rows_a = [
        {"call_id": "c1", "value": 1.0},
        {"call_id": "c1", "value": 2.0},
        {"call_id": "c2", "value": 0.0},
    ]
    rows_b = [
        {"call_id": "c1", "value": 1.5},
        {"call_id": "c1", "value": 2.5},
        {"call_id": "c2", "value": 1.0},
    ]
    res = paired_delta(rows_a, rows_b, "value", cluster_key="call_id", n_boot=100, seed=123)
    assert "deltas" in res
    assert len(res["deltas"]) == 2  # one per call


def test_paired_delta_pools_counts_within_a_call() -> None:
    rows_a = [
        {"call_id": "c1", "real_recall": {"num": 2, "den": 4}},
        {"call_id": "c1", "real_recall": {"num": 3, "den": 6}},
        {"call_id": "c2", "real_recall": {"num": 1, "den": 2}},
    ]
    rows_b = [
        {"call_id": "c1", "real_recall": {"num": 4, "den": 5}},
        {"call_id": "c1", "real_recall": {"num": 0, "den": 5}},
        {"call_id": "c2", "real_recall": {"num": 2, "den": 2}},
    ]
    res = paired_delta(rows_a, rows_b, "real_recall", n_boot=100, seed=0)
    assert res["n"] == 2
    # c1: 5/10 -> 4/10 = -0.1 ; c2: 1/2 -> 2/2 = +0.5
    assert res["deltas"][0] == pytest.approx(-0.1)
    assert res["deltas"][1] == pytest.approx(0.5)


def test_paired_delta_uses_insertion_mean_not_ci_total() -> None:
    rows_a = [
        {
            "call_id": "c1",
            "insertions_per_utterance": {
                "mean": 1.0,
                "total_events": 10,
                "n_utterances": 10,
                "95% interval": (0.0, 90.0),  # interval is on the total, not the mean
            },
        },
        {
            "call_id": "c2",
            "insertions_per_utterance": {"mean": 2.0, "total_events": 20, "n_utterances": 10},
        },
    ]
    rows_b = [
        {
            "call_id": "c1",
            "insertions_per_utterance": {"mean": 1.5, "total_events": 15, "n_utterances": 10},
        },
        {
            "call_id": "c2",
            "insertions_per_utterance": {"mean": 2.0, "total_events": 20, "n_utterances": 10},
        },
    ]
    res = paired_delta(rows_a, rows_b, "insertions_per_utterance", n_boot=100, seed=0)
    assert res["deltas"] == [0.5, 0.0]


def test_verdict_pass_requires_both_ci_bounds() -> None:
    report = _report_with_bounds((-0.01, 0.04), (0.0, 0.2))
    assert verdict(report) == "PASS"


def test_verdict_fails_when_recall_ci_low_breaches_margin() -> None:
    report = _report_with_bounds((-0.10, 0.02), (0.0, 0.2))
    assert verdict(report) == "FAIL"


def test_verdict_fails_when_insertion_ci_high_breaches_cap() -> None:
    report = _report_with_bounds((-0.01, 0.04), (0.0, 0.9))
    assert verdict(report) == "FAIL"


def test_verdict_uses_preregistered_margin() -> None:
    report = _report_with_bounds((-0.03, 0.02), (0.0, 0.2), prereg={"recall_margin": -0.02})
    assert verdict(report) == "FAIL"


def test_verdict_inconclusive_when_ci_missing() -> None:
    report = {"call_id": "c1", "n_calls": 4, "prereg": {}, "paired_deltas": {}}
    assert verdict(report) == "INCONCLUSIVE"


def test_wide_ci_never_defaults_to_pass() -> None:
    report = _report_with_bounds((-0.60, 0.55), (-1.0, 2.0), n=3)
    assert verdict(report) != "PASS"


def test_n_equals_one_is_inconclusive() -> None:
    report = build_report(
        call_id="c1",
        arms=[],
        provenance={"model": "m", "audio_hash": "h"},
        prereg={"recall_margin": -0.05, "insertion_cap": 0.5},
    )
    assert verdict(report) == "INCONCLUSIVE"


def test_single_paired_call_with_planned_n_is_inconclusive() -> None:
    baseline = {
        "name": "baseline",
        "rows": [
            {
                "call_id": "c1",
                "real_recall": {"num": 8, "den": 10},
                "insertions_per_utterance": {"num": 2, "den": 4},
            },
        ],
    }
    selected = {
        "name": "selected-200",
        "rows": [
            {
                "call_id": "c1",
                "real_recall": {"num": 9, "den": 10},
                "insertions_per_utterance": {"num": 2, "den": 4},
            },
        ],
    }
    report = build_report(
        call_id="c1",
        arms=[baseline, selected],
        provenance={"model": "m"},
        prereg={
            "recall_margin": -0.05,
            "insertion_cap": 0.5,
            "planned_calls": 20,
        },
    )
    # One paired call cannot pass, even if the pre-registration planned 20.
    assert report["paired_deltas"]["real_recall"]["n"] == 1
    assert report["n_calls"] == 1
    assert verdict(report) == "INCONCLUSIVE"


def test_verdict_uses_minimum_paired_n_across_metrics() -> None:
    report = _report_with_bounds((-0.01, 0.04), (0.0, 0.2), n=4)
    report["paired_deltas"]["insertions_per_utterance"]["n"] = 1
    assert verdict(report) == "INCONCLUSIVE"


def test_build_report_keeps_counts_for_recall_and_decoder_ignore() -> None:
    report = build_report(
        call_id="c1",
        arms=[
            _make_arm(
                "baseline",
                {
                    "real_recall": {"num": 8, "den": 10},
                    "fictional_recall": {"num": 1, "den": 2},
                    "oov_recall": {"num": 0, "den": 1},
                    "insertions_per_utterance": {"num": 1, "den": 2},
                    "wer": 0.1,
                    "decoder_ignore": {"num": 2, "den": 5},
                },
            ),
        ],
        provenance={"model": "m"},
        prereg={},
    )
    summary = report["metrics_summary"][0]
    assert summary["real_recall"]["num"] == 8
    assert summary["real_recall"]["den"] == 10
    assert summary["fictional_recall"]["num"] == 1
    assert summary["oov_recall"]["den"] == 1
    assert summary["decoder_ignore"]["num"] == 2
    assert summary["decoder_ignore"]["den"] == 5


def test_build_report_computes_paired_deltas_from_per_call_rows() -> None:
    baseline = {
        "name": "baseline",
        "rows": [
            {
                "call_id": "c1",
                "real_recall": {"num": 8, "den": 10},
                "insertions_per_utterance": {"num": 2, "den": 4},
            },
            {
                "call_id": "c2",
                "real_recall": {"num": 9, "den": 10},
                "insertions_per_utterance": {"num": 1, "den": 4},
            },
        ],
    }
    selected = {
        "name": "selected-200",
        "rows": [
            {
                "call_id": "c1",
                "real_recall": {"num": 9, "den": 10},
                "insertions_per_utterance": {"num": 2, "den": 4},
            },
            {
                "call_id": "c2",
                "real_recall": {"num": 9, "den": 10},
                "insertions_per_utterance": {"num": 2, "den": 4},
            },
        ],
    }
    report = build_report(
        call_id="c1",
        arms=[baseline, selected],
        provenance={"model": "m"},
        prereg={"recall_margin": -0.05, "insertion_cap": 0.5},
    )
    paired = report["paired_deltas"]
    assert paired["real_recall"]["n"] == 2
    assert paired["real_recall"]["deltas"] == [pytest.approx(0.1), pytest.approx(0.0)]
    assert paired["insertions_per_utterance"]["n"] == 2
    assert report["n_calls"] == 2


def test_build_report_derives_decoder_ignore_counts_from_rows() -> None:
    rows = [
        {"call_id": "c1", "term_id": "t1", "origin": "real", "hit": True},
        {"call_id": "c1", "term_id": "t2", "origin": "real", "hit": False, "in_context": True},
        {
            "call_id": "c1",
            "term_id": "t3",
            "origin": "real",
            "hit": False,
            "in_context": True,
            "decoder_ignored": True,
        },
        {"call_id": "c1", "term_id": "t4", "origin": "real", "hit": True, "in_context": True},
    ]
    report = build_report(
        call_id="c1",
        arms=[{"name": "baseline", "metrics": {}, "rows": rows}],
        provenance={"model": "m"},
        prereg={},
    )
    decoder = report["metrics_summary"][0]["decoder_ignore"]
    # Denominator is every spoken context term; numerator is those still missed.
    assert decoder["num"] == 2
    assert decoder["den"] == 3
    assert decoder["rate"] == pytest.approx(2 / 3)


def test_markdown_has_seven_sections_and_disclosures() -> None:
    report = build_report(
        call_id="c1",
        arms=[
            _make_arm(
                "baseline",
                {
                    "real_recall": {"num": 9, "den": 10},
                    "fictional_recall": {"num": 1, "den": 1},
                    "oov_recall": {"num": 0, "den": 0},
                    "insertions_per_utterance": {"num": 0, "den": 1},
                    "wer": 0.05,
                    "decoder_ignore": {"num": 1, "den": 10},
                },
            ),
        ],
        provenance={"model": "gnani", "audio_hash": "abc"},
        prereg={"recall_margin": -0.05, "insertion_cap": 0.5},
    )
    md = render_markdown(report)
    for heading in (
        "Provenance",
        "Results per arm",
        "Term-level appendix",
        "Verdict",
        "Descriptive lift",
        "Claims register",
        "Synthetic-audio and circularity disclosure",
    ):
        assert heading in md
    assert "Synthetic" in md or "circularity" in md.lower()
    assert "p-value" not in md.lower()


def test_decoder_ignore_renders_counts() -> None:
    report = build_report(
        call_id="c1",
        arms=[
            _make_arm(
                "baseline",
                {
                    "real_recall": {"num": 8, "den": 10},
                    "fictional_recall": {"num": 1, "den": 2},
                    "oov_recall": {"num": 0, "den": 1},
                    "insertions_per_utterance": {"num": 1, "den": 2},
                    "wer": 0.1,
                    "decoder_ignore": {"num": 2, "den": 5},
                },
            ),
        ],
        provenance={"model": "m"},
        prereg={},
    )
    md = render_markdown(report)
    assert "2/5" in md


def test_decoder_ignore_markdown_shows_spoken_context_denominator() -> None:
    rows = [
        {"call_id": "c1", "term_id": "t1", "origin": "real", "hit": False, "in_context": True},
        {
            "call_id": "c1",
            "term_id": "t2",
            "origin": "real",
            "hit": False,
            "in_context": True,
            "decoder_ignored": True,
        },
        {"call_id": "c1", "term_id": "t3", "origin": "real", "hit": True, "in_context": True},
    ]
    report = build_report(
        call_id="c1",
        arms=[{"name": "baseline", "metrics": {}, "rows": rows}],
        provenance={"model": "m"},
        prereg={},
    )
    md = render_markdown(report)
    assert "2/3" in md
    assert "spoken context terms" in md


def test_markdown_is_labelled_internal_only() -> None:
    report = build_report(
        call_id="c1",
        arms=[],
        provenance={"model": "m"},
        prereg={},
    )
    md = render_markdown(report)
    assert "internal" in md.lower()


def _ab_arms() -> list[dict]:
    return [
        {
            "name": "baseline",
            "rows": [
                {
                    "call_id": "c1",
                    "real_recall": {"num": 8, "den": 10},
                    "insertions_per_utterance": {"num": 1, "den": 4},
                },
                {
                    "call_id": "c2",
                    "real_recall": {"num": 8, "den": 10},
                    "insertions_per_utterance": {"num": 1, "den": 4},
                },
            ],
        },
        {
            "name": "mismatched-200",
            "rows": [
                {
                    "call_id": "c1",
                    "real_recall": {"num": 7, "den": 10},
                    "insertions_per_utterance": {"num": 2, "den": 4},
                },
                {
                    "call_id": "c2",
                    "real_recall": {"num": 8, "den": 10},
                    "insertions_per_utterance": {"num": 1, "den": 4},
                },
            ],
        },
    ]


def test_ab_endpoints_render_requested_pair_as_first_class_rows() -> None:
    report = build_report(
        call_id="c1",
        arms=_ab_arms(),
        provenance={"model": "m"},
        prereg={"recall_margin": -0.05, "insertion_cap": 0.5},
        comparisons=[
            ("baseline", "mismatched-200", "real_recall"),
            ("baseline", "mismatched-200", "insertions_per_utterance"),
        ],
    )
    rows = report["comparisons"]
    assert [row["metric"] for row in rows] == [
        "real_recall",
        "insertions_per_utterance",
    ]
    recall = rows[0]
    assert (recall["arm_a"], recall["arm_b"]) == ("baseline", "mismatched-200")
    assert recall["deltas"] == [pytest.approx(-0.1), pytest.approx(0.0)]
    assert recall["mean"] == pytest.approx(-0.05)
    assert recall["ci_low"] <= recall["mean"] <= recall["ci_high"]

    md = render_markdown(report)
    assert "### Endpoints (A/B)" in md
    assert "mismatched-200 vs baseline" in md
    assert f"[{recall['ci_low']:+.3f}, {recall['ci_high']:+.3f}]" in md
    assert "p-value" not in md.lower()


def test_ab_endpoints_unknown_arm_raises() -> None:
    with pytest.raises(ValueError, match="unknown arm"):
        build_report(
            call_id="c1",
            arms=_ab_arms(),
            provenance={"model": "m"},
            prereg={},
            comparisons=[("baseline", "not-an-arm", "real_recall")],
        )


def test_ab_endpoints_default_to_the_non_inferiority_pair() -> None:
    arms = _ab_arms() + [
        {
            "name": "selected-200",
            "rows": [
                {
                    "call_id": "c1",
                    "real_recall": {"num": 9, "den": 10},
                    "insertions_per_utterance": {"num": 1, "den": 4},
                },
                {
                    "call_id": "c2",
                    "real_recall": {"num": 9, "den": 10},
                    "insertions_per_utterance": {"num": 1, "den": 4},
                },
            ],
        }
    ]
    report = build_report(
        call_id="c1",
        arms=arms,
        provenance={"model": "m"},
        prereg={"recall_margin": -0.05, "insertion_cap": 0.5},
    )
    assert [
        (row["arm_a"], row["arm_b"], row["metric"]) for row in report["comparisons"]
    ] == [
        ("baseline", "selected-200", "real_recall"),
        ("baseline", "selected-200", "insertions_per_utterance"),
    ]
    assert report["comparisons"][0]["mean"] == pytest.approx(
        report["paired_deltas"]["real_recall"]["mean"]
    )


def test_ab_endpoints_do_not_change_the_verdict() -> None:
    kwargs = {
        "call_id": "c1",
        "arms": _ab_arms(),
        "provenance": {"model": "m"},
        "prereg": {"recall_margin": -0.05, "insertion_cap": 0.5},
    }
    plain = build_report(**kwargs)
    extended = build_report(
        **kwargs,
        comparisons=[("mismatched-200", "baseline", "real_recall")],
    )
    assert extended["paired_deltas"] == plain["paired_deltas"]
    assert extended["verdict"] == plain["verdict"]
