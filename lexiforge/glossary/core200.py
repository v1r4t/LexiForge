"""Static core-200 context list (docs/design.md §2, §4 step 1).

``static-head-200`` is the fixed top-frequency 200-term context used as the
practice/secondary comparator against ``baseline``. It is drawn from the
frozen glossary only — never from ASR output, references, or scripts — so
scripts cannot be steered to make it look bad (design §4 step 2 draws term
assignment before the author sees core-200).

Contract
--------
- ``build_core200(glossary, quotas=None, seed=0)`` returns a dict with
  ``term_ids`` (200 entries with default quotas), ``quotas``,
  ``glossary_hash``, ``seed`` and ``built_at``.
- Default quotas are per banking category and sum to 200.
- Within a category, terms rank by ``freq_band`` order, then ``term_id``.
- At most 20 fictional terms (``FICTIONAL_CAP``).
- Declared hard-negative pairs are all-or-nothing: the final list never
  contains exactly one member of a pair whose members both exist in the
  glossary, even when a pair straddles a quota boundary.
- Deterministic: the same ``(glossary, quotas)`` always yields the same
  ``term_ids``. ``seed`` is recorded for provenance; selection itself is
  fully determined by ``(glossary, quotas)`` so no sampling noise can leak
  in from this step.
- ``freeze(path, payload)`` writes the payload as canonical JSON plus a
  ``.sha256`` sidecar; ``verify_freeze(path)`` re-hashes and returns bool.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

__all__ = [
    "DEFAULT_QUOTAS",
    "FICTIONAL_CAP",
    "FREQ_ORDER",
    "build_core200",
    "freeze",
    "verify_freeze",
]

# Twelve banking categories; quotas sum to exactly 200.
DEFAULT_QUOTAS: Dict[str, int] = {
    "upi": 20,
    "cards": 20,
    "loans": 20,
    "kyc": 20,
    "deposits": 20,
    "insurance": 20,
    "forex": 15,
    "branch": 15,
    "collections": 15,
    "mandate": 15,
    "fraud": 10,
    "support": 10,
}

# Lower rank = more frequent = picked first within a category.
FREQ_ORDER: Dict[str, int] = {
    "head": 0,
    "high": 1,
    "core": 1,
    "medium": 2,
    "mid": 2,
    "low": 3,
    "tail": 4,
    "rare": 5,
}

FICTIONAL_CAP = 20

_MISSING_RANK = 99
_UNKNOWN_BAND_RANK = 1000

_ID_KEYS = ("id", "term_id", "term", "name", "key")
_CAT_KEYS = ("category", "domain", "call_type", "topic", "group")
_FREQ_KEYS = ("freq_band", "freq", "band", "priority")
_PAIR_KEYS = (
    "hard_negatives",
    "hard_negative_with",
    "hard_negative_ids",
    "confusable_with",
    "confusable",
    "pair_with",
    "pairs",
)
_FICTIONAL_FLAGS = ("fictional", "is_fictional", "fake", "synthetic")
_FICTIONAL_KINDS = ("kind", "type", "role")
_FICTIONAL_WORDS = frozenset({"fictional", "fake", "synthetic"})


def _assert_no_reference(obj: Any) -> None:
    """Leakage guard: core-200 must never consult references or transcripts."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "reference":
                raise TypeError(
                    "leakage guard: glossary entry contains a 'reference' key"
                )
            _assert_no_reference(value)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for value in obj:
            _assert_no_reference(value)


def _term_id(entry: Any, idx: int) -> str:
    if isinstance(entry, str):
        return entry
    for key in _ID_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError("glossary entry %d has no id/term/name key" % idx)


def _category(entry: Any) -> str:
    if not isinstance(entry, dict):
        return "general"
    for key in _CAT_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return "general"


def _freq_band(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return None
    for key in _FREQ_KEYS:
        if entry.get(key) is not None:
            return entry.get(key)
    return None


def _freq_rank(band: Any) -> float:
    if band is None or isinstance(band, bool):
        return float(_MISSING_RANK)
    if isinstance(band, (int, float)):
        return float(band)  # numeric band numbers: lower (band 1) first
    text = str(band).strip().lower()
    if text in FREQ_ORDER:
        return float(FREQ_ORDER[text])
    try:
        return float(text)
    except ValueError:
        return float(_UNKNOWN_BAND_RANK)


def _is_fictional(entry: Any, category: str) -> bool:
    if category == "fictional":
        return True
    if not isinstance(entry, dict):
        return False
    for key in _FICTIONAL_FLAGS:
        if entry.get(key):
            return True
    for key in _FICTIONAL_KINDS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip().lower() in _FICTIONAL_WORDS:
            return True
    return False


def _declared_pairs(entry: Any) -> List[str]:
    if not isinstance(entry, dict):
        return []
    out: List[str] = []
    for key in _PAIR_KEYS:
        value = entry.get(key)
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, (list, tuple, set, frozenset)):
            out.extend(v for v in value if isinstance(v, str))
    return out


def _coerce_entries(glossary: Any) -> List[Any]:
    """Accept a list of entries, a bare id->meta mapping, or an object
    holding the list under terms/glossary/entries."""
    if isinstance(glossary, dict):
        for field in ("terms", "glossary", "entries"):
            if isinstance(glossary.get(field), list):
                return list(glossary[field])
        if all(isinstance(v, (list, str, dict)) for v in glossary.values()):
            return [{"id": k, **(v if isinstance(v, dict) else {})}
                    for k, v in glossary.items()]
        raise ValueError(
            "unrecognised glossary object keys: %s" % sorted(glossary)
        )
    if isinstance(glossary, (list, tuple)):
        return list(glossary)
    raise TypeError("glossary must be a list of dicts or a mapping")


def _normalise(glossary: Any) -> Dict[str, dict]:
    """Merge to one record per term_id. Order-independent: duplicates merge
    by sorted-choice rules so input order cannot affect the outcome."""
    raw = _coerce_entries(glossary)
    grouped: Dict[str, List[Any]] = {}
    for idx, entry in enumerate(raw):
        if isinstance(entry, str):
            tid = entry
        elif isinstance(entry, dict):
            tid = _term_id(entry, idx)
        else:
            raise TypeError("glossary entry %d must be a dict or str" % idx)
        grouped.setdefault(tid, []).append(entry)

    records: Dict[str, dict] = {}
    for tid in grouped:
        entries = grouped[tid]
        cats = sorted({_category(e) for e in entries})
        bands = [( _freq_rank(_freq_band(e)), str(_freq_band(e))) for e in entries]
        band = min(bands, key=lambda b: (b[0], b[1]))[1]
        fictional = any(_is_fictional(e, c) for e, c in zip(entries, [_category(e) for e in entries]))
        pairs = sorted({p for e in entries for p in _declared_pairs(e) if p != tid})
        records[tid] = {
            "term_id": tid,
            "category": cats[0],
            "freq_band": None if band == "None" else band,
            "freq_rank": min(b[0] for b in bands),
            "fictional": fictional,
            "pairs": pairs,
        }
    return records


def _glossary_hash(records: Dict[str, dict]) -> str:
    canonical = [
        {
            "term_id": tid,
            "category": rec["category"],
            "freq_band": rec["freq_band"],
            "fictional": rec["fictional"],
            "pairs": rec["pairs"],
        }
        for tid, rec in sorted(records.items())
    ]
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_core200(glossary, quotas=None, seed=0) -> dict:
    """Build the frozen static core-200 term list from the glossary only."""
    _assert_no_reference(glossary)
    if quotas is None:
        effective: Dict[str, int] = dict(DEFAULT_QUOTAS)
    else:
        if not isinstance(quotas, dict):
            raise TypeError("quotas must be a mapping of category -> count")
        effective = {}
        for key, value in quotas.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("quota for %r must be an int" % (key,))
            if value < 0:
                raise ValueError("quota for %r must be >= 0" % (key,))
            effective[str(key).strip().lower()] = value

    records = _normalise(glossary)
    present: Set[str] = set(records)
    partners: Dict[str, Set[str]] = {
        tid: {p for p in rec["pairs"] if p in present}
        for tid, rec in records.items()
    }

    by_cat: Dict[str, List[str]] = {}
    for tid, rec in records.items():
        by_cat.setdefault(rec["category"], []).append(tid)
    for tids in by_cat.values():
        tids.sort(key=lambda t: (records[t]["freq_rank"], t))

    selected: Set[str] = set()
    for cat, count in effective.items():
        selected.update(by_cat.get(cat, [])[:count])

    def _drop_closure(sel: Set[str], tid: str) -> None:
        stack = [tid]
        while stack:
            current = stack.pop()
            if current in sel:
                sel.discard(current)
                stack.extend(partners.get(current, ()))

    # Repair: a quota boundary must never split a hard-negative pair.
    while True:
        split = sorted(
            t for t in selected if any(p not in selected for p in partners[t])
        )
        if not split:
            break
        for tid in split:
            _drop_closure(selected, tid)

    # Fictional cap (hard): drop lowest-priority fictionals first.
    while sum(1 for t in selected if records[t]["fictional"]) > FICTIONAL_CAP:
        victims = sorted(
            (t for t in selected if records[t]["fictional"]),
            key=lambda t: (records[t]["freq_rank"], t),
        )
        _drop_closure(selected, victims[-1])

    # Backfill to target without ever splitting a pair or breaching the cap.
    target = sum(effective.values())
    fic_left = FICTIONAL_CAP - sum(1 for t in selected if records[t]["fictional"])
    if len(selected) < target:
        for tid in sorted(records, key=lambda t: (records[t]["freq_rank"], t)):
            if len(selected) >= target:
                break
            if tid in selected:
                continue
            group = {tid} | {p for p in partners[tid] if p not in selected}
            if len(selected) + len(group) > target:
                continue
            need_fic = sum(1 for g in group if records[g]["fictional"])
            if need_fic > fic_left:
                continue
            selected |= group
            fic_left -= need_fic

    return {
        "term_ids": sorted(selected),
        "quotas": dict(effective),
        "glossary_hash": _glossary_hash(records),
        "seed": seed,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def freeze(path, payload) -> str:
    """Write ``payload`` as canonical JSON plus a ``.sha256`` sidecar."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    out.write_bytes(blob)
    Path(str(out) + ".sha256").write_text(
        hashlib.sha256(blob).hexdigest() + "\n", encoding="utf-8"
    )
    return str(out)


def verify_freeze(path) -> bool:
    """Return True iff ``path`` matches its ``.sha256`` sidecar."""
    try:
        blob = Path(path).read_bytes()
        expected = Path(str(Path(path)) + ".sha256").read_text(
            encoding="utf-8").strip().split()[0]
        return hashlib.sha256(blob).hexdigest() == expected
    except Exception:
        return False
