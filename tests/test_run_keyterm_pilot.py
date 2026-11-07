"""Tests for the dry-run-first keyterm pilot orchestrator."""

from __future__ import annotations

import json

import pytest

from scripts.run_keyterm_pilot import ARM_NAMES, run_pilot

CALL = "c00"
TERMS = [f"term-{i:03d}" for i in range(600)]
GLOSSARY = [{"canonical": term, "term_id": f"T{i}"} for i, term in enumerate(TERMS)]
REFERENCE_TEXT = "reference text for the pilot"


def _arms(budget=200):
    return {
        "baseline": [],
        "selected-200": TERMS[:budget],
        "mismatched-200": TERMS[budget : 2 * budget],
        "hard-negative-200": TERMS[2 * budget : 3 * budget],
    }


def _audio(tmp_path):
    path = tmp_path / "c00.wav"
    path.write_bytes(b"RIFF")
    return path


class FakeClient:
    """Fake BatchClient: records every lifecycle call, never touches HTTP."""

    def __init__(self, log=None, transcripts=None):
        self.log = log if log is not None else []
        self.created = []
        self.started = []
        self.waited = []
        self.fetched = []
        self.transcripts = transcripts or {}

    def create_job(self, config, files):
        self.log.append(("create", len(config.get("keyterms") or [])))
        self.created.append((config, list(files)))
        return f"job-{len(self.created)}"

    def start_job(self, job_id):
        self.log.append(("start", job_id))
        self.started.append(job_id)

    def wait(self, job_id, timeout_s=1800, poll_interval=None):
        self.log.append(("wait", job_id))
        self.waited.append((job_id, timeout_s))
        return "COMPLETED"

    def fetch_all_transcripts(self, job_id, status="COMPLETED"):
        self.log.append(("fetch", job_id))
        self.fetched.append(job_id)
        return self.transcripts.get(job_id, {})


def _recording_validator(log):
    def validate(config):
        log.append(("validate", len(config.get("keyterms") or [])))
        assert config["format"] == "transcribe"
        assert config["language_code"] == "hi-IN,en-IN"
        assert len(config.get("keyterms") or []) <= 200
        return dict(config)

    return validate


def _report_builder(seen):
    def build_report(*, call_id, arms, provenance, prereg):
        seen["call"] = call_id
        seen["arms"] = arms
        seen["provenance"] = provenance
        seen["prereg"] = prereg
        return {"call_id": call_id, "arms": arms, "provenance": provenance}

    return build_report


def test_dry_run_writes_plan_and_never_builds_client(tmp_path, monkeypatch):
    monkeypatch.delenv("GNANI_API_KEY", raising=False)

    def explode(*args, **kwargs):
        raise AssertionError("dry run must not construct BatchClient")

    monkeypatch.setattr("lexiforge.api.client.BatchClient", explode)
    monkeypatch.setattr("httpx.Client", explode)
    out_dir = tmp_path / "runs"
    seen = {}

    def arms_builder(**kwargs):
        seen.update(kwargs)
        return _arms(kwargs["budget"])

    result = run_pilot(
        CALL,
        _audio(tmp_path),
        GLOSSARY,
        execute=False,
        arms_builder=arms_builder,
        validator=explode,
        report_builder=explode,
        out_dir=out_dir,
        budget=200,
        seed=7,
        fmt="transcribe",
        language_code="hi-IN,en-IN",
    )

    assert result.dry_run is True
    assert result.job_ids == []
    assert result.statuses == {}
    assert result.credits == 0.0
    assert list(result.arms) == list(ARM_NAMES)
    assert result.arms["baseline"] == []
    assert all(len(result.arms[name]) == 200 for name in ARM_NAMES[1:])
    assert seen["budget"] == 200 and seen["seed"] == 7
    # No transcript exists before the baseline job, so the dry-run plan is explicit
    # that the selected arm is provisional rather than built from reference text.
    assert seen["hypothesis"] == f"call {CALL}"

    plan = json.loads((out_dir / CALL / "plan.json").read_text(encoding="utf-8"))
    assert plan["selection_source"] == "dry-run placeholder"
    assert plan["call_id"] == CALL
    assert plan["execute"] is False
    assert plan["format"] == "transcribe"
    assert plan["language_code"] == "hi-IN,en-IN"
    assert list(plan["arms"]) == list(ARM_NAMES)
    assert len(plan["arms"]["selected-200"]) == 200


def test_execute_validates_before_each_create_and_runs_four_jobs(tmp_path):
    log = []
    client = FakeClient(log=log)
    result = run_pilot(
        CALL,
        _audio(tmp_path),
        GLOSSARY,
        execute=True,
        client=client,
        reference_text=REFERENCE_TEXT,
        validator=_recording_validator(log),
        arms_builder=lambda **kwargs: _arms(kwargs["budget"]),
        report_builder=_report_builder({}),
        renderer=lambda report: "# Keyterm Health\n\nbody",
        out_dir=tmp_path / "runs",
    )

    assert len(client.created) == 4
    assert result.job_ids == ["job-1", "job-2", "job-3", "job-4"]
    assert len(client.started) == 4
    assert len(client.waited) == 4
    assert client.fetched == result.job_ids
    assert result.statuses == {job_id: "COMPLETED" for job_id in result.job_ids}
    assert result.credits == 4.0
    assert result.dry_run is False

    # Exactly one validate immediately before every create (job creation is never retried).
    for index, (kind, _) in enumerate(log):
        if kind == "create":
            assert index > 0 and log[index - 1][0] == "validate"
    assert [kind for kind, _ in log].count("create") == 4
    assert [kind for kind, _ in log].count("validate") == 4

    # One file per job.
    assert all(len(files) == 1 for _, files in client.created)


def test_execute_pins_format_and_language_across_arms(tmp_path):
    client = FakeClient()
    run_pilot(
        CALL,
        _audio(tmp_path),
        GLOSSARY,
        execute=True,
        client=client,
        reference_text=REFERENCE_TEXT,
        validator=lambda config: dict(config),
        arms_builder=lambda **kwargs: _arms(kwargs["budget"]),
        report_builder=_report_builder({}),
        renderer=lambda report: "report",
        out_dir=tmp_path / "runs",
    )

    configs = [config for config, _ in client.created]
    assert [config["format"] for config in configs] == ["transcribe"] * 4
    assert [config["language_code"] for config in configs] == ["hi-IN,en-IN"] * 4
    # baseline carries no keyterms; treated arms carry the exact budget.
    assert "keyterms" not in configs[0]
    assert all(len(config["keyterms"]) == 200 for config in configs[1:])


def test_transcripts_handle_text_segments_and_detected_language(tmp_path):
    client = FakeClient(
        transcripts={
            "job-1": {"fid1": {"text": "hello", "detected_language_code": "hi-IN"}},
            "job-2": {
                "fid2": {
                    "segments": [{"text": "alpha"}, {"text": "beta"}],
                    "detected_language_code": "en-IN",
                }
            },
            "job-3": {"fid3": {"segments": []}},
            "job-4": {},
        }
    )
    result = run_pilot(
        CALL,
        _audio(tmp_path),
        GLOSSARY,
        execute=True,
        client=client,
        reference_text=REFERENCE_TEXT,
        validator=lambda config: dict(config),
        arms_builder=lambda **kwargs: _arms(kwargs["budget"]),
        report_builder=_report_builder({}),
        renderer=lambda report: "report",
        out_dir=tmp_path / "runs",
    )

    assert list(result.rows_by_arm) == list(ARM_NAMES)
    baseline = result.rows_by_arm["baseline"]
    assert baseline["fid1"]["text"] == "hello"
    assert baseline["fid1"]["detected_language_code"] == "hi-IN"
    selected = result.rows_by_arm["selected-200"]
    assert selected["fid2"]["text"] == "alpha beta"
    assert selected["fid2"]["detected_language_code"] == "en-IN"
    assert result.rows_by_arm["mismatched-200"]["fid3"]["text"] == ""


def test_report_is_labelled_internal_only_and_written(tmp_path):
    seen = {}
    result = run_pilot(
        CALL,
        _audio(tmp_path),
        GLOSSARY,
        execute=True,
        client=FakeClient(),
        reference_text=REFERENCE_TEXT,
        validator=lambda config: dict(config),
        arms_builder=lambda **kwargs: _arms(kwargs["budget"]),
        report_builder=_report_builder(seen),
        renderer=lambda report: "# Keyterm Health\n\nbody",
        out_dir=tmp_path / "runs",
        seed=3,
    )

    assert "internal-only" in result.report_markdown.lower()
    assert result.report_path == tmp_path / "runs" / CALL / "report.md"
    assert result.report_path.read_text(encoding="utf-8") == result.report_markdown
    assert seen["call"] == CALL
    assert seen["provenance"]["seed"] == 3
    assert seen["prereg"]["arms"] == list(ARM_NAMES)


def test_execute_builds_arms_from_baseline_transcript_and_script_call_type(tmp_path):
    log = []
    client = FakeClient(
        log=log,
        transcripts={"job-1": {"fid1": {"text": "baseline transcript from pass one"}}},
    )
    seen = {}

    def arms_builder(**kwargs):
        log.append(("arms", kwargs.get("hypothesis")))
        seen.update(kwargs)
        return _arms(kwargs["budget"])

    run_pilot(
        CALL,
        _audio(tmp_path),
        GLOSSARY,
        execute=True,
        client=client,
        validator=lambda config: dict(config),
        arms_builder=arms_builder,
        report_builder=_report_builder({}),
        renderer=lambda report: "report",
        out_dir=tmp_path / "runs",
    )

    # The selector input is the baseline pass-1 transcript, and the call type
    # comes from data/scripts/c00.json, never from a placeholder.
    assert seen["hypothesis"] == "baseline transcript from pass one"
    assert seen["call_type"] == "mandate_fail"

    arms_at = next(index for index, entry in enumerate(log) if entry[0] == "arms")
    assert [kind for kind, _ in log[:arms_at]].count("create") == 1
    assert ("fetch", "job-1") in log[:arms_at]
    assert "keyterms" not in client.created[0][0]
    assert len(client.created) == 4


def test_execute_scores_each_arm_before_real_report_builder(tmp_path):
    scoring_glossary = [
        {"term_id": "R1", "canonical": "Alpha", "origin": "real"},
        {"term_id": "R2", "canonical": "Beta", "origin": "real"},
        {"term_id": "F1", "canonical": "Zeta", "origin": "fictional"},
    ]
    client = FakeClient(
        transcripts={
            "job-1": {"fid": {"text": "Alpha Beta Zeta"}},
            "job-2": {"fid": {"text": "Alpha Beta Zeta"}},
            "job-3": {"fid": {"text": "nothing relevant"}},
            "job-4": {"fid": {"text": "Alpha"}},
        }
    )

    result = run_pilot(
        CALL,
        _audio(tmp_path),
        scoring_glossary,
        execute=True,
        client=client,
        reference_text="Alpha Beta Zeta",
        validator=lambda config: dict(config),
        arms_builder=lambda **kwargs: _arms(kwargs["budget"]),
        out_dir=tmp_path / "runs",
    )

    # Real T9 builder and renderer: the old keyterm-list payload raised
    # AttributeError instead of producing a report.
    assert result.report_path is not None
    assert result.report_path.exists()
    markdown = result.report_markdown
    assert "# Keyterm Health Report" in markdown
    assert "baseline" in markdown
    assert "selected-200" in markdown
    assert "2/2 (100.0%)" in markdown
    assert "internal" in markdown.lower()


def test_execute_without_client_or_key_raises_without_http(tmp_path, monkeypatch):
    monkeypatch.delenv("GNANI_API_KEY", raising=False)

    constructed = []

    def explode_client(*args, **kwargs):
        constructed.append("BatchClient")
        raise AssertionError("BatchClient must not be constructed without a key")

    def explode_http(*args, **kwargs):
        constructed.append("httpx.Client")
        raise AssertionError("no HTTP client may be constructed without a key")

    monkeypatch.setattr("lexiforge.api.client.BatchClient", explode_client)
    monkeypatch.setattr("httpx.Client", explode_http)

    with pytest.raises(ValueError, match="API key"):
        run_pilot(
            CALL,
            _audio(tmp_path),
            GLOSSARY,
            execute=True,
            client=None,
            reference_text=REFERENCE_TEXT,
            validator=lambda config: dict(config),
            arms_builder=lambda **kwargs: _arms(kwargs["budget"]),
            out_dir=tmp_path / "runs",
        )

    assert constructed == []


def test_missing_audio_fails_before_any_job(tmp_path):
    client = FakeClient()
    with pytest.raises(FileNotFoundError):
        run_pilot(
            CALL,
            tmp_path / "missing.wav",
            GLOSSARY,
            execute=True,
            client=client,
            reference_text=REFERENCE_TEXT,
            validator=lambda config: dict(config),
            arms_builder=lambda **kwargs: _arms(kwargs["budget"]),
            out_dir=tmp_path / "runs",
        )
    assert client.created == []


def test_cli_defaults_to_dry_run(tmp_path, monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise AssertionError("CLI dry run must not construct BatchClient")

    monkeypatch.setattr("lexiforge.api.client.BatchClient", explode)
    glossary_path = tmp_path / "glossary.json"
    glossary_path.write_text(json.dumps(GLOSSARY, ensure_ascii=False), encoding="utf-8")
    audio = _audio(tmp_path)
    out_dir = tmp_path / "runs"

    from scripts.run_keyterm_pilot import main

    assert main([CALL, "--audio", str(audio), "--glossary", str(glossary_path),
                 "--out-dir", str(out_dir)]) == 0

    assert (out_dir / CALL / "plan.json").exists()
    output = capsys.readouterr().out
    assert "dry run" in output.lower()
    assert CALL in output
