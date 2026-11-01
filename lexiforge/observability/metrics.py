"""Metrics collection for LexiForge."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, Optional


class MetricsCollector:
    """Simple metrics collector."""
    
    def __init__(self):
        self.counters: Dict[str, float] = defaultdict(float)
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, list] = defaultdict(list)
    
    def increment(self, name: str, value: float = 1.0, tags: Optional[dict] = None):
        """Increment a counter."""
        key = self._make_key(name, tags)
        self.counters[key] += value
    
    def gauge(self, name: str, value: float, tags: Optional[dict] = None):
        """Set a gauge value."""
        key = self._make_key(name, tags)
        self.gauges[key] = value
    
    def observe(self, name: str, value: float, tags: Optional[dict] = None):
        """Observe a histogram value."""
        key = self._make_key(name, tags)
        self.histograms[key].append(value)
    
    def timing(self, name: str, tags: Optional[dict] = None):
        """Context manager for timing."""
        return Timer(self, name, tags)
    
    def _make_key(self, name: str, tags: Optional[dict] = None) -> str:
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"
    
    def get_metrics(self) -> dict:
        """Get all metrics."""
        return {
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
            "histograms": {k: {"count": len(v), "sum": sum(v), "avg": sum(v)/len(v) if v else 0} 
                          for k, v in self.histograms.items()}
        }


class Timer:
    """Timer context manager."""
    
    def __init__(self, collector: MetricsCollector, name: str, tags: Optional[dict] = None):
        self.collector = collector
        self.name = name
        self.tags = tags
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.collector.observe(f"{self.name}.duration", duration, self.tags)
            if exc_type:
                self.collector.increment(f"{self.name}.errors", tags={**(self.tags or {}), "error": exc_type.__name__})


_metrics = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """Get the global metrics collector."""
    return _metrics
