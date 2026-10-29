"""Configuration management for LexiForge."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class MissingApiKey(Exception):
    """Raised when API key is missing or empty."""

    pass


class Settings(BaseModel):
    api_key: str
    base_url: str = "https://api.vachana.ai"
    db_path: str = "lexiforge.db"
    poll_interval_s: int = 15
    max_rps: int = 1


def _load_dotenv_minimal(path: Path) -> dict[str, str]:
    env = {}
    if not path.exists():
        return env
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key:
                env[key] = value
    except Exception:
        pass
    return env


def load_settings(env_path: Path = Path(".env")) -> Settings:
    # Read from .env first
    env_from_file = _load_dotenv_minimal(env_path)
    
    # Build combined env (file takes precedence if we want, but also fall back to os.environ)
    # "reads a minimal .env (KEY=VALUE, # comments, no external deps), falls back to os.environ"
    def get_env(key: str) -> Optional[str]:
        # Check file first, then environ
        if key in env_from_file and env_from_file[key] != "":
            return env_from_file[key]
        if key in os.environ and os.environ[key].strip() != "":
            return os.environ[key].strip()
        return None
    
    # Try common key names for API key
    api_key = (
        get_env("API_KEY")
        or get_env("GNANI_API_KEY")
        or get_env("LEXIFORGE_API_KEY")
        or get_env("VACHANA_API_KEY")
    )
    
    if not api_key or not str(api_key).strip():
        raise MissingApiKey("API key is missing or empty")
    
    api_key = str(api_key).strip()
    
    base_url = (
        get_env("BASE_URL")
        or get_env("GNANI_BASE_URL")
        or get_env("VACHANA_BASE_URL")
        or "https://api.vachana.ai"
    )
    base_url = str(base_url).strip().rstrip("/")
    
    db_path = get_env("DB_PATH") or get_env("LEXIFORGE_DB") or "lexiforge.db"
    db_path = str(db_path).strip()
    
    poll_interval_s = get_env("POLL_INTERVAL_S") or 15
    try:
        poll_interval_s = int(poll_interval_s)
    except Exception:
        poll_interval_s = 15
    
    max_rps = get_env("MAX_RPS") or 1
    try:
        max_rps = int(max_rps)
    except Exception:
        max_rps = 1
    
    return Settings(
        api_key=api_key,
        base_url=base_url,
        db_path=db_path,
        poll_interval_s=poll_interval_s,
        max_rps=max_rps,
    )


def require_api_key(env_path: Path = Path(".env")) -> str:
    settings = load_settings(env_path)
    return settings.api_key
