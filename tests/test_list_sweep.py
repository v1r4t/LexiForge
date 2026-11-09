"""Tests for the list-size sweep runner (design §2 dose-response sweep, P20).

One keyterm list per (call, budget, arm) at 5/50/200 slots; an arm that cannot
be filled is recorded ``underfilled`` with the requested budget intact, never
shrunk. The sweep is descriptive only: no p-values at the small budgets.
"""

from __future__ import annotations

import csv
import json

import pytest

from lexiforge.canon import canon
from scripts.run_list_sweep import main, sweep

CATEGORIES = ("payments", "cards", "loans")


def _glossary(n: int = 320) -> list[dict]:
    return [
        {
            "term_id": f"T{i:04d}",
            "canonical": f"term {i:04d}",
            "category": CATEGORIES[i % len(CATEGORIES)],
            "origin": "fictional" if i % 4 == 3 else "real",
        }
        for i in range(n)
    ]


def _call(
    call_id: str = "t01",
    *,
    audio: str | None = None,
    expected: list[str] | None = None,
) -> dict:
    spec = {
        "call_id": call_id,
        "call_type": "payments",
        "expected_terms": expected or ["T0000", "T0001"],
        "reference_text": "term 0000",
    }
    if audio is not None:
        spec["audio"] = audio
    return spec


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class FakeClient:
    """Records lifecycle calls; never touches HTTP."""

    def __init__(self, transcript: str = "term 0000") -> None:
        self.transcript = transcript
        self.created: list[tuple[dict, list]] = []
        self.started: list[str] = []
        self.waited: list[str] = []

    def create_job(self, config, files):
        self.created.append((config, list(files)))
        return f"job-{len(self.created)}"

    def start_job(self, job_id):
        self.started.append(job_id)

    def wait(self, job_id, timeout_s=1800, poll_interval=None):
        self.waited.append(job_id)
        return "COMPLETED"

    def fetch_all_transcripts(self, job_id, status="COMPLETED"):
        return {"f1": {"text": self.transcript}}


def test_one_list_per_cell_and_exact_budget():
    result = sweep(
        (5, 50, 200),
        [_call("t01", expected=["T0000"])],
        _glossary(201),
    )

    assert set(result) == {"rows", "dose_response"}
    rows = result["rows"]
    assert len(rows) == 3 * 3
    for row in rows:
        assert row["status"] == "ok"
        assert row["n_terms"] == row["budget"]
        assert len(row["terms"]) == row["budget"]
        assert len({canon(term) for term in row["terms"]}) == row["budget"]
        assert "reference" not in row


def test_requested_arms_are_the_only_arms_in_the_matrix():
    result = sweep((5,), [_call()], _glossary(), arms=("mismatched",))
    assert {row["arm"] for row in result["rows"]} == {"mismatched"}
    assert result["rows"][0]["status"] == "ok"
    assert result["dose_response"][0]["n_lists"] == 1


def test_underfilled_arm_is_recorded_and_budget_is_not_shrunk():
    result = sweep((50,), [_call()], _glossary(8))

    rows = result["rows"]
    assert len(rows) == 3
    for row in rows:
        assert row["status"] == "underfilled"
        assert row["budget"] == 50
        assert row["n_terms"] < 50
        assert "exact 50-term arm" in row["error"]

    summary = result["dose_response"][0]
    assert summary["budget"] == 50
    assert summary["n_underfilled"] == 3
    assert summary["n_filled"] == 0


def test_only_the_unfillable_arm_is_marked_underfilled():
    glossary = [
        {"term_id": f"T{i}", "canonical": term, "category": "payments"}
        for i, term in enumerate(
            ["Xylophone", "quartz", "fjord", "nymph", "glyph", "zebra"]
        )
    ]
    result = sweep(
        (5,),
        [_call(expected=["T0"])],
        glossary,
        arms=("selected", "mismatched", "hard-negative"),
    )

    by_arm = {row["arm"]: row for row in result["rows"]}
    assert by_arm["selected"]["status"] == "ok"
    assert by_arm["mismatched"]["status"] == "ok"
    assert by_arm["hard-negative"]["status"] == "underfilled"
    assert by_arm["hard-negative"]["budget"] == 5
    assert len(by_arm["hard-negative"]["terms"]) < 5
    assert "hard-negative pool too small" in by_arm["hard-negative"]["error"]
    summary = result["dose_response"][0]
    assert (summary["n_filled"], summary["n_underfilled"]) == (2, 1)


def test_sweep_is_deterministic_across_runs():
    first = sweep((5, 50), [_call()], _glossary(60), seed=0)
    second = sweep((5, 50), [_call()], _glossary(60), seed=0)
    assert first == second


def test_unknown_arm_raises():
    with pytest.raises(ValueError, match="unknown arm"):
        sweep((5,), [_call()], _glossary(), arms=("baseline",))


@pytest.mark.parametrize("budget", [0, 201])
def test_budget_outside_range_raises(budget):
    with pytest.raises(ValueError, match="budget"):
        sweep((budget,), [_call()], _glossary())


def test_execute_without_api_key_raises(monkeypatch):
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GNANI_API_KEY"):
        sweep((5,), [_call()], _glossary(), execute=True)


def test_execute_uses_one_job_per_cell_and_scores_recall(tmp_path):
    audio = tmp_path / "t01.wav"
    audio.write_bytes(b"RIFF")
    client = FakeClient("term 0000")

    result = sweep(
        (5,),
        [_call(audio=str(audio))],
        _glossary(20),
        arms=("selected",),
        execute=True,
        client=client,
    )

    assert len(client.created) == 1
    config, files = client.created[0]
    assert files == [audio]
    assert config["keyterms"] == result["rows"][0]["terms"]
    row = result["rows"][0]
    assert row["job_id"] == "job-1"
    assert row["job_status"] == "COMPLETED"
    assert row["metrics"]["real_recall"]["rate"] == 1.0
    assert row["metrics"]["real_recall"]["denominator"] == 1
    assert result["dose_response"][0]["arms"]["selected"]["mean_real_recall"] == 1.0


def test_cli_writes_json_and_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_json(tmp_path / "data" / "glossary.json", _glossary(60))
    _write_json(
        tmp_path / "data" / "scripts" / "t01.json",
        {
            "call_id": "t01",
            "call_type": "payments",
            "turns": [{"idx": 1, "text": "term 0000", "glossary_terms": ["T0000"]}],
            "expected_real": ["T0000"],
            "expected_fictional": [],
        },
    )

    code = main(["--budgets", "5,50", "--calls", "t01", "--out", "runs/sweep"])

    assert code == 0
    out = tmp_path / "runs" / "sweep"
    payload = json.loads((out / "sweep.json").read_text(encoding="utf-8"))
    assert len(payload["rows"]) == 6
    assert payload["meta"]["seed"] == 0
    assert {row["status"] for row in payload["rows"]} == {"ok"}

    with (out / "sweep.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert len(rows) == 6
    assert {"call_id", "budget", "arm", "status", "n_terms", "terms"} <= set(reader.fieldnames)
    assert json.loads(rows[0]["terms"]) == payload["rows"][0]["terms"]

    with (out / "dose_response.csv").open(encoding="utf-8", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 2


def test_cli_execute_without_key_returns_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
    _write_json(tmp_path / "data" / "glossary.json", _glossary())

    code = main(["--budgets", "5", "--calls", "t01", "--out", "runs/sweep", "--execute"])

    assert code == 2
    assert not (tmp_path / "runs" / "sweep" / "sweep.json").exists()
