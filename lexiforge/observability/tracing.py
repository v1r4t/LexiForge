"""Lightweight in-process tracing.

This is not OpenTelemetry. It records span name, duration and outcome in a
bounded deque so a run can be inspected (`get_tracer().recent()`) and tests can
assert that instrumentation actually fires. Swapping in OTel later means
replacing :class:`Tracer.span` and :func:`trace`; the call sites do not change.

Usage::

    @trace("run_condition")            # decorator
    def run_condition(...): ...

    with span("wait", {"job": job_id}): # inline block
        ...
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

__all__ = ["Span", "Tracer", "get_tracer", "span", "trace"]


@dataclass
class Span:
    """One completed unit of work."""

    name: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "attributes": dict(self.attributes),
            "duration_ms": round(self.duration_ms, 3),
            "error": self.error,
        }


class Tracer:
    """Bounded in-process span recorder with an optional JSONL sink."""

    def __init__(self, max_spans: int = 1000, sink: Optional[Path] = None) -> None:
        self._spans: deque[Span] = deque(maxlen=max_spans)
        self.enabled = True
        self._sink = sink

    def set_sink(self, path: Optional[Path]) -> None:
        """Append every span to ``path`` as one JSON object per line."""
        self._sink = Path(path) if path is not None else None

    @property
    def sink(self) -> Optional[Path]:
        return self._sink

    @contextmanager
    def span(
        self, name: str, attributes: Optional[Dict[str, Any]] = None
    ) -> Iterator[Span]:
        record = Span(name=name, attributes=dict(attributes or {}))
        started = time.perf_counter()
        try:
            yield record
        except BaseException as exc:
            record.error = type(exc).__name__
            raise
        finally:
            record.duration_ms = (time.perf_counter() - started) * 1000.0
            if self.enabled:
                self._spans.append(record)
            self._write(record)

    def _write(self, record: Span) -> None:
        if self._sink is None:
            return
        try:
            payload = json.dumps(
                {"ts": datetime.now(timezone.utc).isoformat(), **record.as_dict()},
                ensure_ascii=False,
            )
            with self._sink.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
        except OSError:
            # Tracing must never take down a run.
            pass

    def recent(self, limit: int = 50) -> list[Dict[str, Any]]:
        spans = list(self._spans)[-limit:]
        return [s.as_dict() for s in spans]

    def clear(self) -> None:
        self._spans.clear()


_tracer = Tracer(sink=Path(os.environ["LEXIFORGE_TRACE_FILE"]) if os.environ.get("LEXIFORGE_TRACE_FILE") else None)


def get_tracer() -> Tracer:
    """Return the process-wide tracer."""
    return _tracer


@contextmanager
def span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Iterator[Span]:
    """Record an inline span."""
    with _tracer.span(name, attributes) as record:
        yield record


def trace(name: Optional[str] = None, attributes: Optional[Dict[str, Any]] = None):
    """Decorator factory recording a span around each call.

    Works on sync and async callables and preserves the wrapped signature via
    ``functools.wraps``.
    """

    def decorator(func: Callable) -> Callable:
        span_name = name or getattr(func, "__qualname__", "call")

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with _tracer.span(span_name, attributes):
                    return await func(*args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _tracer.span(span_name, attributes):
                return func(*args, **kwargs)

        return wrapper

    return decorator
