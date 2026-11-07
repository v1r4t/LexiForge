"""Tests for Gnani Timbre TTS client. No network: httpx.MockTransport only."""

import unittest

import httpx

from lexiforge.tts.client import SYNTHESIZE_PATH, TimbreClient, TTSResult
from lexiforge.tts.errors import (
    TTSAuthError,
    TTSRateLimitError,
    TTSUnavailableError,
    TTSValidationError,
)


class TestTimbreClient(unittest.TestCase):
    def test_missing_key_raises_before_network(self):
        def handler(request):  # pragma: no cover - must never be called
            raise AssertionError("no request should be sent")

        transport = httpx.MockTransport(handler)
        with self.assertRaises(TTSAuthError):
            TimbreClient(api_key=None, transport=transport)
        with self.assertRaises(TTSAuthError):
            TimbreClient(api_key="", transport=transport)

    def test_empty_text_rejected(self):
        def handler(request):  # pragma: no cover - must never be called
            raise AssertionError("no request should be sent")

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="k", transport=transport)
        with self.assertRaises(TTSValidationError):
            client.synthesize("")
        with self.assertRaises(TTSValidationError):
            client.synthesize("   ")

    def test_synthesize_posts_request_shape(self):
        seen = {}

        def handler(request):
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["headers"] = dict(request.headers)
            seen["body"] = request.read()
            return httpx.Response(
                200,
                content=b"RIFF....WAVE",
                headers={"Content-Type": "audio/wav"},
            )

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="test-key", base_url="https://api.example.test", transport=transport)
        result = client.synthesize("नमस्ते", voice="default", language="hi-IN", fmt="wav")

        self.assertIsInstance(result, TTSResult)
        self.assertEqual(result.audio, b"RIFF....WAVE")
        self.assertEqual(result.fmt, "wav")
        self.assertEqual(result.voice, "default")
        self.assertTrue(seen["path"].endswith(SYNTHESIZE_PATH))
        self.assertEqual(seen["method"], "POST")
        # Should not log key
        body_str = seen["body"].decode("utf-8", "replace")
        self.assertNotIn("test-key", body_str)

    def test_401_maps_to_auth_error(self):
        def handler(request):
            return httpx.Response(401, json={"error": "unauthorized"})

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="k", transport=transport)
        with self.assertRaises(TTSAuthError):
            client.synthesize("hello")

    def test_403_maps_to_auth_error(self):
        def handler(request):
            return httpx.Response(403, json={"error": "forbidden"})

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="k", transport=transport)
        with self.assertRaises(TTSAuthError):
            client.synthesize("hello")

    def test_429_with_retry_after_maps_to_rate_limit(self):
        def handler(request):
            return httpx.Response(429, json={"error": "rate_limited"}, headers={"Retry-After": "10"})

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="k", transport=transport)
        with self.assertRaises(TTSRateLimitError):
            client.synthesize("hello")

    def test_400_maps_to_validation_error(self):
        def handler(request):
            return httpx.Response(400, json={"error": "bad request"})

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="k", transport=transport)
        with self.assertRaises(TTSValidationError):
            client.synthesize("hello")

    def test_500_maps_to_unavailable_error(self):
        def handler(request):
            return httpx.Response(500, json={"error": "server error"})

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="k", transport=transport)
        with self.assertRaises(TTSUnavailableError):
            client.synthesize("hello")

    def test_503_maps_to_unavailable_error(self):
        def handler(request):
            return httpx.Response(503, json={"error": "unavailable"})

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="k", transport=transport)
        with self.assertRaises(TTSUnavailableError):
            client.synthesize("hello")

    def test_timeout_maps_to_unavailable_error(self):
        def handler(request):
            raise httpx.TimeoutException("timeout")

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="k", transport=transport)
        with self.assertRaises(TTSUnavailableError):
            client.synthesize("hello")


if __name__ == "__main__":
    unittest.main()
