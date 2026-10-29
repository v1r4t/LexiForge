"""Build and validate per-call decoding contexts.

Pipeline position (design §4 step 6): ``contexts/<condition>/c##.json`` —
JSON array, NFC, one fixed sort key, deduped before the 200-cap.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Iterable, Mapping, Optional

MAX_KEYTERMS = 200
TOPIC_MIN = 30
TOPIC_MAX = 1600

_FORBIDDEN_SUBSTRINGS = ("<|", "|>")

# Any key that would smuggle transcript/reference content into the topic.
_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "transcript",
        "reference",
        "ref",
        "refs",
        "text",
        "utterance",
        "utterances",
        "script",
        "scripts",
        "hypothesis",
        "transcription",
    }
)

_ALLOWED_METADATA_KEYS = frozenset({"call_type", "channel", "language"})

_WS_RE = re.compile(r"\s+")


class ContextBudgetError(ValueError):
    """Raised when canonicalised keyterms exceed the 200-slot budget."""

    def __init__(self, count: int, limit: int = MAX_KEYTERMS) -> None:
        super().__init__(
            f"keyterm budget exceeded: {count} terms > {limit} slot limit"
        )
        self.count = count
        self.limit = limit


def _canonical_one(term: str) -> str:
    text = unicodedata.normalize("NFC", term)
    text = text.strip()
    text = _WS_RE.sub(" ", text)
    return text


def canonicalise_terms(terms: Optional[Iterable[str]]) -> list[str]:
    """NFC, trim, collapse whitespace, drop empties, dedupe, fixed sort.

    Sort key is ``(casefold, original)`` so output order is independent of
    input permutation. Raises ``ValueError`` on ``<|`` / ``|>`` and
    ``TypeError`` on non-string entries.
    """
    if terms is None:
        return []
    seen: dict[str, None] = {}
    for raw in terms:
        if not isinstance(raw, str):
            raise TypeError(
                f"keyterm must be str, got {type(raw).__name__}"
            )
        cand = _canonical_one(raw)
        if not cand:
            continue
        for bad in _FORBIDDEN_SUBSTRINGS:
            if bad in cand:
                raise ValueError(f"keyterm contains forbidden {bad!r}: {cand!r}")
        seen.setdefault(cand, None)
    return sorted(seen.keys(), key=lambda s: (s.casefold(), s))


# American-spelling alias; the canonical name is ``canonicalise_terms``.
canonicalize_terms = canonicalise_terms


def assert_budget(keyterms: Optional[Iterable[str]]) -> int:
    """Raise :class:`ContextBudgetError` (with the count) if over budget."""
    items = list(keyterms) if keyterms is not None else []
    count = len(items)
    if count > MAX_KEYTERMS:
        raise ContextBudgetError(count)
    return count


def _check_topic(topic: str) -> str:
    if not isinstance(topic, str):
        raise TypeError(f"topic must be str, got {type(topic).__name__}")
    n = len(topic)
    if n < TOPIC_MIN or n > TOPIC_MAX:
        raise ValueError(
            f"topic must be {TOPIC_MIN}-{TOPIC_MAX} chars, got {n}"
        )
    return topic


def build_config(
    *,
    topic: Optional[str] = None,
    keyterms: Optional[Iterable[str]] = None,
    speaker_names: Optional[Iterable[str]] = None,
) -> dict:
    """Build a context config with only allowed fields.

    Accepted combinations: none | keyterms | topic | topic+keyterms |
    speaker_names. Anything else raises ``ValueError``.
    """
    has_topic = topic is not None
    has_keyterms = keyterms is not None
    has_speakers = speaker_names is not None

    combo = (has_topic, has_keyterms, has_speakers)
    allowed = {
        (False, False, False),  # none
        (False, True, False),  # keyterms
        (True, False, False),  # topic
        (True, True, False),  # topic+keyterms
        (False, False, True),  # speaker_names
    }
    if combo not in allowed:
        raise ValueError(
            "invalid context combination: allowed are none | keyterms | "
            f"topic | topic+keyterms | speaker_names, got topic={has_topic}, "
            f"keyterms={has_keyterms}, speaker_names={has_speakers}"
        )

    config: dict = {}
    if has_topic:
        assert topic is not None
        config["topic"] = _check_topic(topic)
    if has_keyterms:
        assert keyterms is not None
        canon = canonicalise_terms(keyterms)
        assert_budget(canon)
        config["keyterms"] = canon
    if has_speakers:
        assert speaker_names is not None
        if isinstance(speaker_names, str):
            raise TypeError("speaker_names must be a list of str, not str")
        names = list(speaker_names)
        if not names:
            raise ValueError("speaker_names must be non-empty")
        cleaned: list[str] = []
        for n in names:
            if not isinstance(n, str):
                raise TypeError(
                    f"speaker_name must be str, got {type(n).__name__}"
                )
            c = n.strip()
            if not c:
                raise ValueError("speaker_names entries must be non-empty")
            cleaned.append(c)
        config["speaker_names"] = cleaned
    return config


def context_hash(config: Mapping) -> str:
    """sha256 over canonical JSON (sorted keys, ``ensure_ascii=False``)."""
    blob = json.dumps(
        dict(config), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def derive_topic(call_metadata: Mapping) -> str:
    """Derive the per-call constant topic from metadata only.

    Built ONLY from ``call_type``, ``channel`` and ``language``. Raises
    ``TypeError`` if any transcript/reference field (e.g. ``reference``) or
    any other unexpected key is passed, so transcript content can never leak
    into the topic arm.
    """
    if not isinstance(call_metadata, Mapping):
        raise TypeError(
            f"call_metadata must be a mapping, got {type(call_metadata).__name__}"
        )
    for key in call_metadata:
        if key in _FORBIDDEN_METADATA_KEYS:
            raise TypeError(
                f"derive_topic() must not receive transcript/reference "
                f"field {key!r}: built ONLY from call_type, channel, language"
            )
        if key not in _ALLOWED_METADATA_KEYS:
            raise TypeError(
                f"derive_topic() accepts only call_type, channel, language; "
                f"got unexpected key {key!r}"
            )
    call_type = str(call_metadata.get("call_type", "general")).strip() or "general"
    channel = str(call_metadata.get("channel", "phone")).strip() or "phone"
    language = str(call_metadata.get("language", "Hinglish")).strip() or "Hinglish"
    return (
        f"Banking customer support call about {call_type} "
        f"conducted over {channel} in {language}."
    )
