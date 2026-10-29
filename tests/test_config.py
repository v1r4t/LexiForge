"""Tests for config module."""

import os
import tempfile
import unittest
from pathlib import Path

from lexiforge.config import MissingApiKey, Settings, load_settings, require_api_key


class TestSettings(unittest.TestCase):
    def test_settings_defaults(self):
        settings = Settings(api_key="test-key")
        self.assertEqual(settings.api_key, "test-key")
        self.assertEqual(settings.base_url, "https://api.vachana.ai")
        self.assertEqual(settings.db_path, "lexiforge.db")
        self.assertEqual(settings.poll_interval_s, 15)
        self.assertEqual(settings.max_rps, 1)
    
    def test_settings_custom_values(self):
        settings = Settings(
            api_key="mykey",
            base_url="https://example.com",
            db_path="custom.db",
            poll_interval_s=30,
            max_rps=2,
        )
        self.assertEqual(settings.api_key, "mykey")
        self.assertEqual(settings.base_url, "https://example.com")
        self.assertEqual(settings.db_path, "custom.db")
        self.assertEqual(settings.poll_interval_s, 30)
        self.assertEqual(settings.max_rps, 2)


class TestLoadSettings(unittest.TestCase):
    def setUp(self):
        # Save original env
        self.original_env = os.environ.copy()
    
    def tearDown(self):
        # Restore original env
        os.environ.clear()
        os.environ.update(self.original_env)
    
    def test_load_from_env(self):
        os.environ["API_KEY"] = "env-key-123"
        settings = load_settings(Path(tempfile.mktemp()))
        self.assertEqual(settings.api_key, "env-key-123")
        self.assertEqual(settings.base_url, "https://api.vachana.ai")
    
    def test_load_from_dotenv(self):
        # Create a temp .env file
        fd, path = tempfile.mkstemp(suffix=".env")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("API_KEY=dotenv-key-456\n")
                f.write("# This is a comment\n")
                f.write("BASE_URL=https://custom.api.com\n")
                f.write("\n")
                f.write("DB_PATH=test.db\n")
            settings = load_settings(Path(path))
            self.assertEqual(settings.api_key, "dotenv-key-456")
            self.assertEqual(settings.base_url, "https://custom.api.com")
            self.assertEqual(settings.db_path, "test.db")
        finally:
            os.unlink(path)
    
    def test_load_fallback_to_os_environ(self):
        os.environ["GNANI_API_KEY"] = "gnani-key"
        fd, path = tempfile.mkstemp(suffix=".env")
        os.close(fd)
        try:
            settings = load_settings(Path(path))
            self.assertEqual(settings.api_key, "gnani-key")
        finally:
            os.unlink(path)
    
    def test_missing_api_key_raises(self):
        # Clear all possible API key env vars
        for key in ["API_KEY", "GNANI_API_KEY", "LEXIFORGE_API_KEY", "VACHANA_API_KEY"]:
            os.environ.pop(key, None)
        fd, path = tempfile.mkstemp(suffix=".env")
        os.close(fd)
        try:
            with self.assertRaises(MissingApiKey):
                load_settings(Path(path))
        finally:
            os.unlink(path)
    
    def test_empty_api_key_raises(self):
        os.environ["API_KEY"] = ""
        fd, path = tempfile.mkstemp(suffix=".env")
        os.close(fd)
        try:
            with self.assertRaises(MissingApiKey):
                load_settings(Path(path))
        finally:
            os.unlink(path)
    
    def test_require_api_key(self):
        os.environ["API_KEY"] = "required-key"
        fd, path = tempfile.mkstemp(suffix=".env")
        os.close(fd)
        try:
            key = require_api_key(Path(path))
            self.assertEqual(key, "required-key")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
