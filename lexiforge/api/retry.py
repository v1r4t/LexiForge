"""Retry utilities for API calls."""

from __future__ import annotations

import random
import threading
import time
from typing import Any, Callable, Iterable


class RetryExhausted(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, last_exception: Exception | None = None):
        self.last_exception = last_exception
        super().__init__(str(last_exception) if last_exception is not None else "Retries exhausted")


class RateLimiter:
    def __init__(self, max_per_minute: int, clock: Callable[[], float] | None = None, sleep: Callable[[float], Any] | None = None):
        self.max_per_minute = max_per_minute
        self.clock = clock if clock is not None else time.monotonic
        self.sleep = sleep if sleep is not None else time.sleep
        self._lock = threading.Lock()
        self._tokens = max_per_minute
        self._last_refill = self.clock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self.clock()
                elapsed = now - self._last_refill
                if elapsed >= 60.0:
                    # Refill tokens
                    periods = elapsed // 60.0
                    self._tokens = self.max_per_minute
                    self._last_refill = now
                if self._tokens > 0:
                    self._tokens -= 1
                    return
                # Calculate wait time until next refill
                wait_time = 60.0 - elapsed
            if wait_time < 0:
                wait_time = 0
            self.sleep(wait_time)


def backoff(
    attempt: int,
    base: float = 1.0,
    cap: float = 60.0,
    jitter: random.Random | None = None,
) -> float:
    if jitter is None:
        jitter = random.Random()
    # base * 2**attempt, capped, multiplied by uniform(0.8, 1.2)
    value = base * (2 ** attempt)
    if value > cap:
        value = cap
    factor = jitter.uniform(0.8, 1.2)
    return value * factor


def with_retries(
    fn: Callable[[], Any],
    *,
    retries: int = 3,
    on: Iterable[int] = (429, 504),
    backoff_fn: Callable[..., float] = backoff,
    sleep: Callable[[float], Any] = time.sleep,
    retries_504: int = 1,
) -> Any:
    on_set = set(on)
    attempts = 0
    last_exception = None
    # Track 504-specific retries
    retries_504_count = 0
    max_total_attempts = retries + 1  # initial attempt + retries
    while attempts < max_total_attempts:
        try:
            result = fn()
            return result
        except Exception as e:
            last_exception = e
            # Check if it's a retryable status code
            status_code = getattr(e, "status_code", None)
            if status_code is None and hasattr(e, "response"):
                status_code = getattr(e.response, "status_code", None)
            
            if status_code not in on_set:
                raise
            
            # Special handling for 504 - max retries_504 times
            if status_code == 504:
                if retries_504_count >= retries_504:
                    raise RetryExhausted(last_exception)
                retries_504_count += 1
            else:
                # For other retryable codes (like 429), use general retries
                pass
            
            # Check if we've exhausted general retries
            if attempts >= retries and status_code != 504:  # 504 handled separately
                raise RetryExhausted(last_exception)
            if status_code == 504 and retries_504_count > retries_504:
                raise RetryExhausted(last_exception)
            
            attempts += 1
            # Calculate backoff
            delay = backoff_fn(attempts - 1)  # attempt index for backoff
            sleep(delay)
            continue
    
    raise RetryExhausted(last_exception)
