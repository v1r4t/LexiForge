import json
import os
import warnings
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException

app = FastAPI()

_DATA_DIR = Path(__file__).parent / "data"

# Module-level guard for outbound calls in precomputed/demo mode
_DEMO_MODE_DEFAULT = os.environ.get("DEMO_MODE", "precomputed").lower()
if _DEMO_MODE_DEFAULT == "precomputed":

    def _guard_no_outbound_call(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Outbound calls are disabled in precomputed demo mode")

    # Attach a guard that can be imported/checked by tests
    app.state.no_outbound_call = _guard_no_outbound_call
else:
    app.state.no_outbound_call = None


def _load_json(name: str) -> Any:
    path = _DATA_DIR / name
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        warnings.warn(f"Missing data file: {path}")
        return []
    except json.JSONDecodeError:
        warnings.warn(f"Invalid JSON in data file: {path}")
        return []


_CALLS: List[Dict[str, Any]] = []
_TRANSCRIPTS: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
_TERMS: Dict[str, Dict[str, Any]] = {}
_RESULTS: Dict[str, Any] = {}
_DEMO_CONFIG: Dict[str, str] = {"mode": os.environ.get("DEMO_MODE", "precomputed").lower()}


@app.on_event("startup")
def _load_data() -> None:
    global _CALLS, _TRANSCRIPTS, _TERMS, _RESULTS, _DEMO_CONFIG

    # Try to load from files; fall back to empty/defaults if missing
    calls_data = _load_json("calls.json")
    if isinstance(calls_data, list):
        _CALLS = calls_data
    else:
        _CALLS = []

    transcripts_data = _load_json("transcripts.json")
    if isinstance(transcripts_data, dict):
        _TRANSCRIPTS = transcripts_data
    else:
        _TRANSCRIPTS = {}

    terms_data = _load_json("terms.json")
    if isinstance(terms_data, dict):
        _TERMS = terms_data
    else:
        _TERMS = {}

    results_data = _load_json("results.json")
    if isinstance(results_data, dict):
        _RESULTS = results_data
    else:
        _RESULTS = {}

    config_data = _load_json("demo_config.json")
    if isinstance(config_data, dict) and "mode" in config_data:
        _DEMO_CONFIG = {"mode": str(config_data["mode"])}
    else:
        _DEMO_CONFIG = {"mode": os.environ.get("DEMO_MODE", "precomputed").lower()}


@app.get("/health")
def health() -> Dict[str, str]:
    mode = os.environ.get("DEMO_MODE", "precomputed").lower()
    return {"status": "ok", "mode": mode}


@app.get("/calls")
def get_calls() -> List[Dict[str, Any]]:
    return _CALLS


@app.get("/calls/{call_id}/transcripts")
def get_transcripts(call_id: str) -> Dict[str, List[Dict[str, Any]]]:
    if call_id not in _TRANSCRIPTS:
        # Return structure with empty lists if not found
        return {"baseline": [], "mismatched": [], "adaptive": [], "oracle": []}
    data = _TRANSCRIPTS[call_id]
    # Ensure all keys present with correct shape
    result = {
        "baseline": data.get("baseline", []),
        "mismatched": data.get("mismatched", []),
        "adaptive": data.get("adaptive", []),
        "oracle": data.get("oracle", []),
    }
    return result


@app.get("/calls/{call_id}/terms")
def get_terms(call_id: str) -> Dict[str, Any]:
    if call_id not in _TERMS:
        return {"selected": [], "left_out": []}
    data = _TERMS[call_id]
    return {
        "selected": data.get("selected", []),
        "left_out": data.get("left_out", []),
    }


@app.get("/results")
def get_results() -> Dict[str, Any]:
    if not _RESULTS:
        return {"contrasts": [], "control": {}}
    return _RESULTS


@app.get("/demo/config")
def get_demo_config() -> Dict[str, str]:
    return {"mode": os.environ.get("DEMO_MODE", "precomputed").lower()}
