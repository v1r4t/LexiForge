"""Tests for retry utilities."""

import random
import time
import unittest
from unittest.mock import Mock

from lexiforge.api.retry import RateLimiter, RetryExhausted, backoff, with_retries


class TestBackoff(unittest.TestCase):
    def test_backoff_exponential_with_jitter(self):
        rng = random.Random(12345)
        # base * 2^attempt, capped, multiplied by uniform(0.8, 1.2)
        result = backoff(0, base=1.0, cap=60.0, jitter=rng)
        # 1.0 * 1.0 = 1.0, multiplied by jitter in [0.8,1.2]
        self.assertGreaterEqual(result, 0.8)
        self.assertLessEqual(result, 1.2)
        
        result = backoff(1, base=1.0, cap=60.0, jitter=rng)
        self.assertGreaterEqual(result, 1.6)  # 2.0 * 0.8
        self.assertLessEqual(result, 2.4)    # 2.0 * 1.2
        
        result = backoff(2, base=1.0, cap=60.0, jitter=rng)
        self.assertGreaterEqual(result, 3.2)
        self.assertLessEqual(result, 4.8)
    
    def test_backoff_capped(self):
        rng = random.Random(42)
        result = backoff(10, base=1.0, cap=60.0, jitter=rng)
        # 1.0 * 2^10 = 1024, capped to 60, then * jitter
        self.assertGreaterEqual(result, 48.0)
        self.assertLessEqual(result, 72.0)
    
    def test_backoff_deterministic_with_seeded_rng(self):
        rng1 = random.Random(999)
        rng2 = random.Random(999)
        results1 = [backoff(i, jitter=rng1) for i in range(5)]
        results2 = [backoff(i, jitter=rng2) for i in range(5)]
        self.assertEqual(results1, results2)


class MockResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class HTTPError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        self.response = MockResponse(status_code)
        super().__init__(f"HTTP {status_code}")


class TestWithRetries(unittest.TestCase):
    def test_retries_on_429_with_jittered_backoff(self):
        delays = []
        def fake_sleep(d):
            delays.append(d)
        
        rng = random.Random(123)
        call_count = 0
        def failing_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise HTTPError(429)
            return "success"
        
        result = with_retries(failing_fn, retries=3, on=(429, 504), backoff_fn=lambda attempt: backoff(attempt, jitter=rng), sleep=fake_sleep)
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)
        self.assertEqual(len(delays), 2)  # retried twice
        # Check delays are jittered
        for d in delays:
            self.assertGreater(d, 0)
    
    def test_504_gets_one_retry_maximum(self):
        delays = []
        def fake_sleep(d):
            delays.append(d)
        
        call_count = 0
        def failing_fn():
            nonlocal call_count
            call_count += 1
            raise HTTPError(504)
        
        with self.assertRaises(RetryExhausted):
            with_retries(failing_fn, retries=5, on=(429, 504), backoff_fn=lambda attempt: backoff(attempt, jitter=random.Random(1)), sleep=fake_sleep, retries_504=1)
        self.assertEqual(call_count, 2)  # initial + 1 retry for 504
        self.assertEqual(len(delays), 1)
    
    def test_no_retry_on_other_status_codes(self):
        call_count = 0
        def failing_fn():
            nonlocal call_count
            call_count += 1
            raise HTTPError(400)
        
        with self.assertRaises(HTTPError):
            with_retries(failing_fn, retries=3, on=(429, 504), backoff_fn=backoff, sleep=time.sleep)
        self.assertEqual(call_count, 1)
    
    def test_returns_final_result_or_raises_retry_exhausted(self):
        call_count = 0
        def failing_fn():
            nonlocal call_count
            call_count += 1
            raise HTTPError(429)
        
        delays = []
        with self.assertRaises(RetryExhausted):
            with_retries(failing_fn, retries=2, on=(429, 504), backoff_fn=lambda attempt: backoff(attempt, jitter=random.Random(5)), sleep=lambda d: delays.append(d))
        self.assertEqual(call_count, 3)  # initial + 2 retries


class TestRateLimiter(unittest.TestCase):
    def test_rate_limiter_blocks_until_token_available(self):
        current_time = [0.0]
        sleep_calls = []
        
        def fake_clock():
            return current_time[0]
        
        def fake_sleep(d):
            sleep_calls.append(d)
            current_time[0] += d
        
        limiter = RateLimiter(max_per_minute=2, clock=fake_clock, sleep=fake_sleep)
        # First two should not block
        limiter.acquire()
        limiter.acquire()
        self.assertEqual(len(sleep_calls), 0)
        # Third should block until refill
        limiter.acquire()
        self.assertTrue(len(sleep_calls) > 0)
    
    def test_rate_limiter_thread_safe(self):
        import threading
        current_time = [0.0]
        def fake_clock():
            return current_time[0]
        def fake_sleep(d):
            current_time[0] += d
        
        limiter = RateLimiter(max_per_minute=10, clock=fake_clock, sleep=fake_sleep)
        results = []
        def acquire_one():
            limiter.acquire()
            results.append(1)
        
        threads = [threading.Thread(target=acquire_one) for _ in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 15)
    
    def test_rate_limiter_testable_with_fake_clock_and_sleep(self):
        current_time = [100.0]
        sleep_calls = []
        def fake_clock():
            return current_time[0]
        def fake_sleep(d):
            sleep_calls.append(d)
            current_time[0] += d
        
        limiter = RateLimiter(max_per_minute=60, clock=fake_clock, sleep=fake_sleep)
        for _ in range(60):
            limiter.acquire()
        self.assertEqual(len(sleep_calls), 0)
        limiter.acquire()  # Should trigger refill wait
        self.assertTrue(len(sleep_calls) > 0)
        self.assertAlmostEqual(sleep_calls[0], 60.0, places=5)


if __name__ == "__main__":
    unittest.main()
