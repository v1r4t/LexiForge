"""Tests for lexiforge.api.client. No network: httpx.MockTransport only."""

import json
import unittest

import httpx

from lexiforge.api.client import BatchApiError, BatchClient, TERMINAL_STATUSES


def make_client(handler, **kwargs):
    kwargs.setdefault("poll_interval", 0)
    kwargs.setdefault("backoff_base", 0)
    transport = httpx.MockTransport(handler)
    return BatchClient({"base_url": "https://api.example.test", "api_key": "k"}, transport=transport, **kwargs)


def json_response(status, payload, request=None):
    return httpx.Response(status, json=payload)


class TestCreateJob(unittest.TestCase):
    def test_posts_multipart_config_and_files(self):
        seen = {}

        def handler(request):
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["content_type"] = request.headers.get("content-type", "")
            seen["body"] = request.read()
            return json_response(200, {"job_id": "job-1"})

        with make_client(handler) as client:
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as tmp:
                a = Path(tmp) / "c01_t01.wav"
                b = Path(tmp) / "c01_t02.wav"
                a.write_bytes(b"RIFF-a")
                b.write_bytes(b"RIFF-b")
                job_id = client.create_job({"model": "m", "language": "hi"}, [a, b])
        self.assertEqual(job_id, "job-1")
        self.assertEqual(seen["method"], "POST")
        self.assertTrue(seen["path"].endswith("/stt/v3/batch/jobs"), seen["path"])
        self.assertIn("multipart/form-data", seen["content_type"])
        body = seen["body"].decode("utf-8", "replace")
        self.assertIn('name="config"', body)
        self.assertIn('name="files"', body)
        self.assertIn("c01_t01.wav", body)

    def test_config_is_json_string(self):
        bodies = []

        def handler(request):
            bodies.append(request.read())
            return json_response(200, {"job_id": "j"})

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.wav"
            f.write_bytes(b"x")
            with make_client(handler) as client:
                client.create_job({"a": 1}, [f])
        # multipart encodes the JSON string; it must parse back to the config.
        raw = bodies[0].decode("utf-8", "replace")
        start = raw.index('name="config"')
        encoded = raw[start:].split("\r\n\r\n", 1)[1].split("\r\n", 1)[0]
        self.assertEqual(json.loads(encoded), {"a": 1})

    def test_does_not_retry_job_creation(self):
        calls = []

        def handler(request):
            calls.append(request)
            return json_response(429, {"code": "RATE_LIMITED", "message": "slow down"})

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.wav"
            f.write_bytes(b"x")
            with make_client(handler) as client:
                with self.assertRaises(BatchApiError) as ctx:
                    client.create_job({}, [f])
        self.assertEqual(len(calls), 1)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_invalid_config_error_surfaces_code(self):
        def handler(request):
            return json_response(400, {"code": "INVALID_CONFIG", "message": "bad topic"})

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.wav"
            f.write_bytes(b"x")
            with make_client(handler) as client:
                with self.assertRaises(BatchApiError) as ctx:
                    client.create_job({}, [f])
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.code, "INVALID_CONFIG")

    def test_enforces_limits(self):
        def handler(request):  # pragma: no cover - must never be called
            raise AssertionError("no request should be sent")

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.wav"
            big.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
            with make_client(handler) as client:
                with self.assertRaises(ValueError):
                    client.create_job({}, [big])
                with self.assertRaises(ValueError):
                    client.create_job({}, [Path(tmp) / "missing.wav"] * 2)
                with self.assertRaises(ValueError):
                    client.create_job({}, [Path(tmp) / "missing.wav"] * 101)


class TestJobControl(unittest.TestCase):
    def test_start_job_posts_start_path(self):
        seen = {}

        def handler(request):
            seen["method"] = request.method
            seen["path"] = request.url.path
            return json_response(200, {"status": "QUEUED"})

        with make_client(handler) as client:
            self.assertIsNone(client.start_job("job-9"))
        self.assertEqual(seen["method"], "POST")
        self.assertTrue(seen["path"].endswith("/stt/v3/batch/jobs/job-9/start"), seen["path"])

    def test_auth_header(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers.get("X-API-Key-ID")
            return json_response(200, {"job_id": "j", "status": "QUEUED"})

        with make_client(handler) as client:
            client.get_job("j")
        self.assertEqual(seen["auth"], "k")

    def test_get_job_returns_dict(self):
        def handler(request):
            return json_response(200, {"job_id": "j", "status": "PROCESSING"})

        with make_client(handler) as client:
            job = client.get_job("j")
        self.assertEqual(job["status"], "PROCESSING")

    def test_terminal_set_matches_spec(self):
        self.assertEqual(
            TERMINAL_STATUSES,
            {"COMPLETED", "PARTIAL_FAILURE", "FAILED", "START_FAILED", "CANCELLED"},
        )

    def test_wait_returns_terminal_status(self):
        states = [{"status": "PROCESSING"}, {"status": "PROCESSING"}, {"status": "PARTIAL_FAILURE"}]
        calls = []

        def handler(request):
            calls.append(request.url.path)
            return json_response(200, states.pop(0))

        with make_client(handler) as client:
            status = client.wait("j", timeout_s=30)
        self.assertEqual(status, "PARTIAL_FAILURE")
        self.assertEqual(len(calls), 3)

    def test_wait_times_out(self):
        def handler(request):
            return json_response(200, {"status": "PROCESSING"})

        with make_client(handler) as client:
            with self.assertRaises(TimeoutError):
                client.wait("j", timeout_s=0.01, poll_interval=0)

    def test_wait_survives_transient_429(self):
        seq = [
            json_response(429, {"code": "RATE_LIMITED"}),
            json_response(200, {"status": "COMPLETED"}),
        ]

        def handler(request):
            return seq.pop(0)

        with make_client(handler) as client:
            self.assertEqual(client.wait("j", timeout_s=30), "COMPLETED")


class TestFilesAndTranscripts(unittest.TestCase):
    def test_list_files_with_status(self):
        seen = {}

        def handler(request):
            seen["query"] = dict(request.url.params)
            return json_response(200, {"files": [{"file_id": "f1", "transcript_url": "https://t/x"}]})

        with make_client(handler) as client:
            files = client.list_files("j", status="COMPLETED")
        self.assertEqual(seen["query"], {"status": "COMPLETED"})
        self.assertEqual(files, [{"file_id": "f1", "transcript_url": "https://t/x"}])

    def test_fetch_transcript_no_auth(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers.get("X-API-Key-ID")
            return json_response(200, {"text": "hello"})

        with make_client(handler) as client:
            payload = client.fetch_transcript("https://cdn.example.test/t1")
        self.assertEqual(payload, {"text": "hello"})
        self.assertIsNone(seen["auth"])

    def test_expired_url_refetches_file_list_once(self):
        calls = []

        def handler(request):
            calls.append(request.url.path)
            host = request.url.host
            if host == "cdn.example.test" and request.url.path == "/old":
                return json_response(403, {"code": "TRANSCRIPT_URL_EXPIRED"})
            if request.url.path.endswith("/files"):
                return json_response(
                    200, {"files": [{"file_id": "f1", "transcript_url": "https://cdn.example.test/new"}]}
                )
            if host == "cdn.example.test" and request.url.path == "/new":
                return json_response(200, {"text": "fresh"})
            raise AssertionError(f"unexpected {request.url}")

        with make_client(handler) as client:
            payload = client.fetch_file_transcript(
                "j", {"file_id": "f1", "transcript_url": "https://cdn.example.test/old"}
            )
        self.assertEqual(payload, {"text": "fresh"})
        self.assertEqual(calls.count("/stt/v3/batch/jobs/j/files"), 1)


if __name__ == "__main__":
    unittest.main()
