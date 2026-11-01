"""Tests for observability: metrics, structured logging and real spans."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from lexiforge.observability import (
    MetricsCollector,
    Tracer,
    get_logger,
    get_metrics,
    get_tracer,
    span,
    trace,
)
from lexiforge.observability.logging import StructuredFormatter


def test_counter_tags_are_part_of_the_key():
    collector = MetricsCollector()
    collector.increment("calls", tags={"condition": "baseline"})
    collector.increment("calls", tags={"condition": "baseline"})
    collector.increment("calls", tags={"condition": "oracle"})
    counters = collector.get_metrics()["counters"]
    assert counters["calls{condition=baseline}"] == 2.0
    assert counters["calls{condition=oracle}"] == 1.0


def test_timer_records_duration_and_error():
    collector = MetricsCollector()
    with collector.timing("job"):
        pass
    assert collector.get_metrics()["histograms"]["job.duration"]["count"] == 1

    with pytest.raises(RuntimeError):
        with collector.timing("job"):
            raise RuntimeError("boom")
    assert collector.get_metrics()["counters"]["job.errors{error=RuntimeError}"] == 1.0


def test_trace_decorator_records_a_span():
    get_tracer().clear()

    @trace("unit")
    def work(value: int) -> int:
        return value * 2

    assert work(3) == 6
    assert [s["name"] for s in get_tracer().recent()] == ["unit"]


def test_trace_decorator_supports_async():
    get_tracer().clear()

    @trace("async-unit")
    async def work() -> int:
        return 7

    assert asyncio.run(work()) == 7
    assert [s["name"] for s in get_tracer().recent()] == ["async-unit"]


def test_trace_preserves_wrapped_signature():
    @trace("named")
    def documented(a, b=2):
        """Docstring survives."""
        return a + b

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Docstring survives."


def test_span_records_error_type_and_duration():
    get_tracer().clear()
    with pytest.raises(ValueError):
        with span("failing"):
            raise ValueError("nope")
    recorded = get_tracer().recent()[-1]
    assert recorded["name"] == "failing"
    assert recorded["error"] == "ValueError"
    assert recorded["duration_ms"] >= 0.0


def test_tracer_is_bounded():
    tracer = Tracer(max_spans=3)
    for index in range(5):
        with tracer.span(f"s{index}"):
            pass
    names = [s["name"] for s in tracer.recent(10)]
    assert names == ["s2", "s3", "s4"]


def test_structured_formatter_emits_json_with_extras():
    record = logging.LogRecord(
        "lexiforge.test", logging.INFO, __file__, 1, "hello", (), None
    )
    record.extra = {"condition": "baseline"}
    payload = json.loads(StructuredFormatter().format(record))
    assert payload["message"] == "hello"
    assert payload["condition"] == "baseline"
    assert payload["level"] == "INFO"
    assert "timestamp" in payload


def test_logger_kwargs_become_extras():
    logger = get_logger("lexiforge.test.unit")
    captured: dict = {}

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.update(getattr(record, "extra", {}))

    target = logger.logger
    previous_level = target.level
    handler = _Capture()
    target.setLevel(logging.INFO)
    target.addHandler(handler)
    try:
        logger.info("message", condition="baseline", n=3)
    finally:
        target.removeHandler(handler)
        target.setLevel(previous_level)

    assert captured == {"condition": "baseline", "n": 3}


def test_runner_span_and_counter_are_recorded():
    from lexiforge.runner import Runner

    get_tracer().clear()
    Runner().run_condition("baseline", ["c01"], {"c01": []}, {"c01": []})
    assert [s["name"] for s in get_tracer().recent()] == ["run_condition"]
    counters = get_metrics().get_metrics()["counters"]
    assert counters["runs_started{condition=baseline}"] >= 1.0
