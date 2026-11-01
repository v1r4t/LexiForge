"""FastAPI service for the LexiForge dashboard.

Data directory resolution, in order:

1. ``$LEXIFORGE_WEB_DATA`` if set.
2. ``web/data/`` if it contains ``calls.json`` (measured export).
3. ``web/data/sample/`` (hand-written illustrative sample).

Files are re-read when their modification time changes, so ``lexiforge
export-web`` is picked up without restarting the server.
"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="LexiForge dashboard API")

_WEB_DIR = Path(__file__).parent
_FRONTEND_DIST = _WEB_DIR / "frontend" / "dist"
_AUDIO_DIR = Path(os.environ.get("LEXIFORGE_AUDIO_DIR", "audio"))
_AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".flac", ".ogg")

# Module-level guard for outbound calls in precomputed/demo mode
if os.environ.get("DEMO_MODE", "precomputed").lower() == "precomputed":

    def _guard_no_outbound_call(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Outbound calls are disabled in precomputed demo mode")

    app.state.no_outbound_call = _guard_no_outbound_call
else:
    app.state.no_outbound_call = None


def _resolve_data_dir() -> Path:
    override = os.environ.get("LEXIFORGE_WEB_DATA")
    if override:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(
                f"LEXIFORGE_WEB_DATA points to missing directory: {p}. "
                "Create it or run `lexiforge export-web` to populate web/data/."
            )
        return p
    measured = _WEB_DIR / "data"
    if (measured / "calls.json").exists():
        return measured
    sample = measured / "sample"
    if not sample.exists():
        raise FileNotFoundError(
            f"No web data found. Expected {measured / 'calls.json'} (measured) or {sample} (sample). "
            "Run `lexiforge export-web` to generate measured data, or ensure the sample set exists."
        )
    return sample


_DATA_DIR = _resolve_data_dir()

_CALLS: List[Dict[str, Any]] = []
_TRANSCRIPTS: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
_TERMS: Dict[str, Dict[str, Any]] = {}
_RESULTS: Dict[str, Any] = {}
_CONFIG: Dict[str, Any] = {"mode": "precomputed", "data_source": "illustrative_sample"}
_MTIMES: Dict[str, float] = {}

_EMPTY_TRANSCRIPTS: Dict[str, List[Dict[str, Any]]] = {
    "baseline": [],
    "mismatched": [],
    "adaptive": [],
    "oracle": [],
}


def _load_json(name: str, default: Any) -> Any:
    path = _DATA_DIR / name
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError:
        warnings.warn(f"missing data file: {path}")
        return default
    except json.JSONDecodeError as exc:
        warnings.warn(f"invalid JSON in {path}: {exc}")
        return default


def _refresh(force: bool = False) -> None:
    """Reload any data file whose mtime changed since the last read."""
    global _CALLS, _TRANSCRIPTS, _TERMS, _RESULTS, _CONFIG

    names = ("calls.json", "transcripts.json", "terms.json", "results.json", "demo_config.json")
    stale = force
    for name in names:
        try:
            mtime = (_DATA_DIR / name).stat().st_mtime
        except OSError:
            mtime = -1.0
        if _MTIMES.get(name) != mtime:
            _MTIMES[name] = mtime
            stale = True
    if not stale:
        return

    calls = _load_json("calls.json", [])
    _CALLS = calls if isinstance(calls, list) else []

    transcripts = _load_json("transcripts.json", {})
    _TRANSCRIPTS = transcripts if isinstance(transcripts, dict) else {}

    terms = _load_json("terms.json", {})
    _TERMS = terms if isinstance(terms, dict) else {}

    results = _load_json("results.json", {})
    _RESULTS = results if isinstance(results, dict) else {}

    config = _load_json("demo_config.json", {})
    if isinstance(config, dict) and config:
        _CONFIG = dict(config)
    else:
        _CONFIG = {"mode": "precomputed", "data_source": "illustrative_sample"}
    _CONFIG.setdefault("data_source", "illustrative_sample")
    _CONFIG["is_sample"] = _CONFIG.get("data_source") == "illustrative_sample"


def _conditions() -> List[str]:
    seen: List[str] = []
    for conditions in _TRANSCRIPTS.values():
        if not isinstance(conditions, dict):
            continue
        for key in conditions:
            if key not in seen:
                seen.append(key)
    return seen or list(_EMPTY_TRANSCRIPTS)


def _audio_file(call_id: str) -> Path | None:
    """Locate a call's audio, if the (gitignored) audio directory exists."""
    for suffix in _AUDIO_SUFFIXES:
        candidate = _AUDIO_DIR / f"{call_id}{suffix}"
        if candidate.is_file():
            return candidate
    return None


@app.get("/health")
def health() -> Dict[str, Any]:
    _refresh()
    return {
        "status": "ok",
        "mode": os.environ.get("DEMO_MODE", "precomputed").lower(),
        "data_source": _CONFIG.get("data_source"),
        "data_dir": str(_DATA_DIR),
    }


@app.get("/meta")
def meta() -> Dict[str, Any]:
    """Shape of the dataset the UI is showing."""
    _refresh()
    return {
        "data_source": _CONFIG.get("data_source"),
        "is_sample": bool(_CONFIG.get("is_sample", False)),
        "note": _CONFIG.get("note", ""),
        "mode": os.environ.get("DEMO_MODE", "precomputed").lower(),
        "conditions": _conditions(),
        "call_count": len(_CALLS),
        "audio": [call.get("call_id") for call in _CALLS if _audio_file(str(call.get("call_id")))],
        "data_dir": str(_DATA_DIR),
    }


@app.api_route("/calls/{call_id}/audio", methods=["GET", "HEAD"])
def get_audio(call_id: str):
    """Serve the call recording when the audio directory is present.

    HEAD is declared explicitly: FastAPI does not add it for GET routes, and
    the dashboard probes with HEAD before rendering a player.
    """
    path = _audio_file(call_id)
    if path is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail": "no audio for this call",
                "looked_in": str(_AUDIO_DIR),
                "hint": "audio/ is gitignored; set LEXIFORGE_AUDIO_DIR or place <call_id>.wav there",
            },
        )
    return FileResponse(path)


@app.get("/calls")
def get_calls() -> List[Dict[str, Any]]:
    _refresh()
    return _CALLS


@app.get("/calls/{call_id}/transcripts")
def get_transcripts(call_id: str) -> Dict[str, List[Dict[str, Any]]]:
    _refresh()
    data = _TRANSCRIPTS.get(call_id)
    if not isinstance(data, dict):
        return dict(_EMPTY_TRANSCRIPTS)
    return {key: (data.get(key) or []) for key in _conditions()}


@app.get("/calls/{call_id}/terms")
def get_terms(call_id: str) -> Dict[str, Any]:
    _refresh()
    data = _TERMS.get(call_id)
    if not isinstance(data, dict):
        return {"selected": [], "left_out": []}
    return {
        "selected": data.get("selected", []),
        "left_out": data.get("left_out", []),
    }


@app.get("/results")
def get_results() -> Dict[str, Any]:
    _refresh()
    if not _RESULTS:
        return {"contrasts": [], "control": {}, "is_sample": False}
    return _RESULTS


@app.get("/demo/config")
def get_demo_config() -> Dict[str, Any]:
    _refresh()
    return {"mode": os.environ.get("DEMO_MODE", "precomputed").lower()}


@app.post("/reload")
def reload_data() -> Dict[str, Any]:
    """Force a re-read of the data directory."""
    _refresh(force=True)
    return {"reloaded": True, "calls": len(_CALLS), "data_dir": str(_DATA_DIR)}


# Serve the built dashboard when present. Mounted last so the API routes above
# always win; a missing build leaves the API usable instead of 404-ing it.
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")


@app.exception_handler(404)
async def not_found(request, exc) -> JSONResponse:
    if not _FRONTEND_DIST.exists() and request.url.path in ("/", "/index.html"):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "dashboard build missing",
                "fix": "cd web/frontend && npm install && npm run build",
            },
        )
    return JSONResponse(status_code=404, content={"detail": "not found"})
