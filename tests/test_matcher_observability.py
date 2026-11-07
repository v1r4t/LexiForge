"""Tests for matcher instrumentation: spans and counters."""

from __future__ import annotations

import json

import pytest

from lexiforge.observability import get_metrics, get_tracer
from lexiforge.score.match import AliasCollision, find_spans


def _counter(name: str) -> float:
    return get_metrics().get_metrics()["counters"].get(name, 0.0)


def _neft_glossary() -> list[dict]:
    return [{"id": "NEFT", "aliases": ["NEFT", "N.E.F.T."]}]


def test_find_spans_records_a_span_with_attributes():
    get_tracer().clear()
    text = "send money through NEFT today"

    spans = find_spans(text, _neft_glossary())

    assert len(spans) == 1
    recorded = get_tracer().recent()
    matcher = [s for s in recorded if s["name"] == "matcher.find_spans"]
    assert len(matcher) == 1
    attributes = matcher[0]["attributes"]
    assert attributes["text_length"] == len(text)
    assert attributes["glossary_size"] == 1
    assert attributes["spans_found"] == 1


def test_spans_found_counter_increments_by_number_of_spans():
    glossary = [
        {"id": "ALPHA", "aliases": ["alpha"]},
        {"id": "BETA", "aliases": ["beta"]},
    ]
    before = _counter("matcher.spans_found")

    spans = find_spans("alpha then beta", glossary)

    assert len(spans) == 2
    assert _counter("matcher.spans_found") - before == 2.0


def test_alias_collision_increments_counter():
    glossary = [
        {"id": "A", "aliases": ["same"]},
        {"id": "B", "aliases": ["same"]},
    ]
    before = _counter("matcher.alias_collisions")

    with pytest.raises(AliasCollision):
        find_spans("same", glossary)

    assert _counter("matcher.alias_collisions") - before == 1.0


def test_span_is_recorded_without_a_sink():
    # Existing tracer convention: spans are kept in memory even with no sink.
    previous = get_tracer().sink
    get_tracer().set_sink(None)
    get_tracer().clear()
    try:
        find_spans("NEFT", _neft_glossary())
    finally:
        get_tracer().set_sink(previous)

    assert [s["name"] for s in get_tracer().recent()] == ["matcher.find_spans"]


def test_span_is_written_to_the_sink(tmp_path):
    sink = tmp_path / "trace.jsonl"
    previous = get_tracer().sink
    get_tracer().set_sink(sink)
    get_tracer().clear()
    try:
        find_spans("NEFT", _neft_glossary())
    finally:
        get_tracer().set_sink(previous)

    payloads = [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines()]
    matcher = [p for p in payloads if p["name"] == "matcher.find_spans"]
    assert len(matcher) == 1
    assert matcher[0]["attributes"]["spans_found"] == 1
