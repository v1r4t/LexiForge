"""Tests for Prisma client."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from lexiforge.api.prisma import PrismaClient


class TestPrismaClient:
    @patch("lexiforge.api.prisma.httpx.Client")
    def test_init(self, mock_client):
        client = PrismaClient(api_key="test-key", base_url="https://api.test.com")
        assert client.api_key == "test-key"
        assert client.base_url == "https://api.test.com"

    @patch("lexiforge.api.prisma.httpx.Client")
    def test_create_job(self, mock_http_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"job_id": "job123"}
        mock_http_client.return_value.post.return_value = mock_response

        client = PrismaClient(api_key="test-key")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake audio")
            temp_path = Path(f.name)

        try:
            job_id = client.create_job(files=[temp_path], config={"model": "prisma-v3.0"})
            assert job_id == "job123"
        finally:
            temp_path.unlink()
