"""Gnani v3 conformance validator."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Mapping

FORMATS = ("verbatim", "transcribe", "codemix")
REST_FORMATS = FORMATS + ("transliterate",)


class GnaniValidationError(ValueError):
    def __init__(self, message: str = "", issues: List[str] | None = None):
        self.issues = issues if issues is not None else ([message] if message else [])
        if not self.issues and message:
            self.issues = [message]
        super().__init__(message or "; ".join(self.issues))


class GnaniErrorKind(Enum):
    AUTH = "AUTH"
    VALIDATION = "VALIDATION"
    RATE_LIMIT = "RATE_LIMIT"
    SERVER = "SERVER"
    NETWORK = "NETWORK"
    UNKNOWN = "UNKNOWN"


def validate_keyterms(terms: Any) -> List[str]:
    if terms is None:
        return []
    if isinstance(terms, str):
        # treat as single term? but need to be flexible
        terms_list = [terms]
    elif isinstance(terms, (list, tuple, set)):
        terms_list = list(terms)
    else:
        raise GnaniValidationError(issues=["keyterms must be a list"])

    if len(terms_list) == 0:
        raise GnaniValidationError(issues=["keyterms must be non-empty"])
    if len(terms_list) > 200:
        raise GnaniValidationError(issues=["keyterms exceeds 200"])

    result: List[str] = []
    seen = set()
    for t in terms_list:
        if not isinstance(t, str):
            raise GnaniValidationError(issues=["keyterms must contain strings"])
        if t == "":
            raise GnaniValidationError(issues=["keyterms must be non-empty"])
        if "<|" in t or "|>" in t:
            raise GnaniValidationError(issues=["keyterms contains forbidden tokens"])
        if t in seen:
            raise GnaniValidationError(issues=["keyterms must be unique"])
        seen.add(t)
        result.append(t)
    return result


def validate_topic(topic: Any, *, min_length: int = 30) -> str:
    if not isinstance(topic, str):
        raise GnaniValidationError(issues=["topic must be a string"])
    if len(topic) < min_length or len(topic) > 1600:
        raise GnaniValidationError(issues=["topic length out of range"])
    return topic


def validate_speaker_names(names: Any) -> List[str]:
    if names is None:
        raise GnaniValidationError(issues=["speaker_names required"])
    if isinstance(names, str):
        names_list = [names]
    elif isinstance(names, (list, tuple)):
        names_list = list(names)
    else:
        raise GnaniValidationError(issues=["speaker_names must be a list"])

    if len(names_list) < 1 or len(names_list) > 4:
        raise GnaniValidationError(issues=["speaker_names count out of range"])
    for n in names_list:
        if not isinstance(n, str) or n == "":
            raise GnaniValidationError(issues=["speaker_names must be non-empty strings"])
    # speaker_names must be used alone - validation of combination is done in validate_batch_config
    return names_list


def validate_substitution_map(mapping: Any) -> Dict[str, str]:
    if mapping is None:
        return {}
    if not isinstance(mapping, Mapping):
        raise GnaniValidationError(issues=["substitution_map must be a mapping"])
    if len(mapping) > 10:
        raise GnaniValidationError(issues=["substitution_map exceeds 10 entries"])
    result: Dict[str, str] = {}
    for k, v in mapping.items():
        if not isinstance(k, str) or k == "":
            raise GnaniValidationError(issues=["substitution_map keys must be non-empty strings"])
        if not isinstance(v, str) or v == "":
            raise GnaniValidationError(issues=["substitution_map values must be non-empty strings"])
        if k in result:
            raise GnaniValidationError(issues=["substitution_map keys must be unique"])
        result[k] = v
    return result


def validate_batch_config(config: Any) -> Dict[str, Any]:
    if config is None:
        raise GnaniValidationError(issues=["config required"])
    if isinstance(config, Mapping):
        cfg = dict(config)
    else:
        # try to convert from object
        if hasattr(config, "model_dump"):
            cfg = config.model_dump()
        elif hasattr(config, "dict"):
            cfg = config.dict()
        else:
            raise GnaniValidationError(issues=["config must be a dict"])

    # Strip canon_version if present (build_config injects it, API does not accept)
    if "canon_version" in cfg:
        cfg.pop("canon_version")

    # Check for bad format
    fmt = cfg.get("format") or cfg.get("transcription_format") or cfg.get("mode")
    if fmt is not None:
        if fmt not in FORMATS:
            raise GnaniValidationError(issues=["invalid format"])
    else:
        # format might be required? Let us look up acceptance - "bad format" is mentioned as a test case
        pass

    # Detect features
    has_keyterms = False
    keyterms = cfg.get("keyterms") or cfg.get("vocabulary") or cfg.get("context") or cfg.get("keywords")
    if keyterms is not None:
        validated_keyterms = validate_keyterms(keyterms)
        # normalize to keyterms
        cfg["keyterms"] = validated_keyterms
        has_keyterms = True
    elif cfg.get("keyterms") == [] or (isinstance(cfg.get("vocabulary"), list) and len(cfg.get("vocabulary")) == 0):
        # empty keyterms might be treated as no keyterms?
        pass

    has_topic = "topic" in cfg and cfg.get("topic") is not None
    if has_topic:
        validated_topic = validate_topic(cfg["topic"])
        cfg["topic"] = validated_topic

    has_speaker_names = False
    speaker_names = cfg.get("speaker_names") or cfg.get("speakers") or cfg.get("speakerNames")
    if speaker_names is not None:
        validated_speakers = validate_speaker_names(speaker_names)
        cfg["speaker_names"] = validated_speakers
        has_speaker_names = True

    # Check allowed combinations
    # Allowed: none | keyterms | topic | topic+keyterms | speaker_names
    if has_speaker_names:
        if has_keyterms or has_topic:
            raise GnaniValidationError(issues=["speaker_names cannot be combined with other context"])
    # If has_keyterms and has_topic - that's allowed (topic+keyterms)
    # If neither - that's allowed (none)
    # Any other combination is not in allowed list? For example keyterms alone is allowed, topic alone allowed

    # Validate substitution map if present
    if "substitution_map" in cfg and cfg["substitution_map"] is not None:
        cfg["substitution_map"] = validate_substitution_map(cfg["substitution_map"])
    elif "substitutions" in cfg and cfg["substitutions"] is not None:
        cfg["substitution_map"] = validate_substitution_map(cfg["substitutions"])

    return cfg


def validate_rest_config(config: Any) -> Dict[str, Any]:
    """Validate the REST (synchronous) request config.

    REST supports ``transliterate`` and allows any combination of keyterms,
    topic, previous_text and speaker_names, unlike Batch.
    """
    if config is None:
        raise GnaniValidationError(issues=["config required"])
    if isinstance(config, Mapping):
        cfg = dict(config)
    else:
        raise GnaniValidationError(issues=["config must be a dict"])

    cfg.pop("canon_version", None)
    fmt = cfg.get("format") or cfg.get("transcription_format") or cfg.get("mode")
    if fmt is not None and fmt not in REST_FORMATS:
        raise GnaniValidationError(issues=["invalid format"])

    keyterms = cfg.get("keyterms") or cfg.get("vocabulary") or cfg.get("context") or cfg.get("keywords")
    if keyterms is not None:
        cfg["keyterms"] = validate_keyterms(keyterms)
    if cfg.get("topic") is not None:
        cfg["topic"] = validate_topic(cfg["topic"], min_length=1)
    speakers = cfg.get("speaker_names") or cfg.get("speakers") or cfg.get("speakerNames")
    if speakers is not None:
        cfg["speaker_names"] = validate_speaker_names(speakers)
    if cfg.get("substitution_map") is not None:
        cfg["substitution_map"] = validate_substitution_map(cfg["substitution_map"])
    return cfg


def classify_error(status_code: int, payload: Any = None) -> GnaniErrorKind:
    if not isinstance(status_code, int):
        return GnaniErrorKind.UNKNOWN

    if status_code in (401, 403):
        return GnaniErrorKind.AUTH
    if status_code == 429:
        return GnaniErrorKind.RATE_LIMIT
    if status_code == 400 or status_code == 422:
        return GnaniErrorKind.VALIDATION
    if status_code in (408, 504):
        return GnaniErrorKind.NETWORK
    if 500 <= status_code < 600:
        return GnaniErrorKind.SERVER
    # Also check payload for hints
    if isinstance(payload, dict):
        error = payload.get("error") or payload.get("message") or ""
        if isinstance(error, dict):
            error_str = str(error.get("type") or error.get("code") or "")
        else:
            error_str = str(error)
        error_str_lower = error_str.lower()
        if any(k in error_str_lower for k in ["auth", "unauthorized", "forbidden"]):
            return GnaniErrorKind.AUTH
        if "rate" in error_str_lower or "limit" in error_str_lower:
            return GnaniErrorKind.RATE_LIMIT
        if "validation" in error_str_lower or "invalid" in error_str_lower:
            return GnaniErrorKind.VALIDATION
        if "network" in error_str_lower or "timeout" in error_str_lower:
            return GnaniErrorKind.NETWORK
        if "server" in error_str_lower or "internal" in error_str_lower:
            return GnaniErrorKind.SERVER

    return GnaniErrorKind.UNKNOWN
