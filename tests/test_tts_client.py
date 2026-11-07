"""Tests for Gnani Timbre TTS client. No network: httpx.MockTransport only."""

import io
import json
import struct
import unittest
import wave

import httpx

from lexiforge.tts.client import TimbreClient, TTSResult, normalize_wav
from lexiforge.tts.errors import (
    TTSAuthError,
    TTSRateLimitError,
    TTSUnavailableError,
    TTSValidationError,
)


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00\x00" * 8)
    return buffer.getvalue()


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
            seen["json"] = request.read()
            return httpx.Response(
                200,
                content=_wav_bytes(),
                headers={"Content-Type": "audio/wav"},
            )

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="test-key", base_url="https://api.example.test", transport=transport)
        result = client.synthesize("नमस्ते")

        self.assertIsInstance(result, TTSResult)
        self.assertEqual(result.audio, _wav_bytes())
        self.assertEqual(result.fmt, "wav")
        self.assertEqual(result.voice, "Poorvi")
        self.assertEqual(result.sample_rate, 8000)
        self.assertEqual(seen["path"], "/api/v1/tts/inference")
        self.assertEqual(seen["method"], "POST")
        self.assertNotIn("authorization", seen["headers"])
        self.assertEqual(seen["headers"].get("x-api-key-id"), "test-key")

        payload = json.loads(seen["json"])
        self.assertEqual(payload["voice"], "Poorvi")
        self.assertEqual(payload["model"], "timbre-v2.5")
        self.assertEqual(payload["language"], "hi-en")
        self.assertEqual(
            payload["audio_config"],
            {
                "sample_rate": 8000,
                "num_channels": 1,
                "sample_width": 2,
                "encoding": "linear_pcm",
                "container": "wav",
            },
        )
        # Should not include the key in the body
        self.assertNotIn("test-key", seen["json"].decode("utf-8", "replace"))

    def test_custom_voice_model_language_and_sample_rate(self):
        seen = {}

        def handler(request):
            seen["json"] = request.read()
            return httpx.Response(200, content=b"audio")

        transport = httpx.MockTransport(handler)
        client = TimbreClient(api_key="k", transport=transport)
        result = client.synthesize(
            "hello", voice="Nalini", model="timbre-v3.0", language="hi-IN", sample_rate=16000
        )

        payload = json.loads(seen["json"])
        self.assertEqual(payload["voice"], "Nalini")
        self.assertEqual(payload["model"], "timbre-v3.0")
        self.assertEqual(payload["language"], "hi-IN")
        self.assertEqual(payload["audio_config"]["sample_rate"], 16000)
        self.assertEqual(result.sample_rate, 16000)

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


    def test_normalize_streaming_wav_header(self):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(b"\x00\x00" * 800)
        raw = bytearray(buffer.getvalue())
        raw[4:8] = struct.pack("<I", 0xFFFFFFFF)
        data_pos = raw.find(b"data")
        raw[data_pos + 4 : data_pos + 8] = struct.pack("<I", 0xFFFFFFFF)

        fixed = normalize_wav(bytes(raw))
        with wave.open(io.BytesIO(fixed), "rb") as wf:
            self.assertEqual(wf.getnframes(), 800)
            self.assertEqual(wf.getframerate(), 8000)


if __name__ == "__main__":
    unittest.main()
