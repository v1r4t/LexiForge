"""The fixed ``static-head-200`` context arm (design §2, §4 step 1).

``static-head-200`` is the practice/secondary comparator against ``baseline``:
one glossary list, byte-identical for every call, hypothesis, call type and
process. It is built only from the frozen core-200 term ids plus a padded,
sorted tail drawn from the glossary itself — never from ASR output,
references or scripts (design §4 step 2 draws term assignment before the
author sees core-200). The arm is labelled ``static-head-200`` and is
declared secondary in pre-registration amendment 1.

``data/core200.json`` nests its ids under ``term_ids``; a bare list is also
accepted so callers can pass an in-memory selection.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from lexiforge.canon import canon
from lexiforge.contexts.build import MAX_KEYTERMS, assert_exact_budget

__all__ = ["ARM_NAME", "static_head_from_file", "static_head_terms"]

ARM_NAME = "static-head-200"

_ID_KEYS = ("term_id", "id", "termId")
_SURFACE_KEYS = ("canonical", "term", "name")


def _entry_id(entry: Mapping, idx: int) -> str:
    for key in _ID_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"glossary entry {idx} has no term_id/id key")


def _entry_surface(entry: Mapping, tid: str) -> str:
    for key in _SURFACE_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return tid


def _glossary_index(glossary: Iterable[dict]) -> tuple[dict[str, str], list[str]]:
    """Return ``(id -> surface, canonically sorted unique pool)``."""
    if isinstance(glossary, (str, bytes, Mapping)):
        raise TypeError("glossary must be an iterable of dicts")
    id_to_surface: dict[str, str] = {}
    surfaces: dict[str, str] = {}
    for idx, entry in enumerate(glossary):
        if not isinstance(entry, dict):
            raise TypeError(f"glossary entry {idx} must be a dict")
        tid = _entry_id(entry, idx)
        surface = _entry_surface(entry, tid)
        id_to_surface.setdefault(tid, surface)
        key = canon(surface)
        if key:
            surfaces.setdefault(key, surface)
    pool = sorted(surfaces.values(), key=lambda s: (canon(s), s))
    return id_to_surface, pool


def _term_ids(core200: Any) -> list[str]:
    if isinstance(core200, Mapping):
        ids = core200.get("term_ids")
        if ids is None:
            raise ValueError("core-200 payload has no 'term_ids' list")
    elif isinstance(core200, (list, tuple)):
        ids = core200
    else:
        raise TypeError(
            "core200 must be a mapping with 'term_ids' or a list of ids; "
            "use static_head_from_file() for a JSON path"
        )
    if isinstance(ids, str):
        raise TypeError("core-200 term ids must be an iterable, not a str")
    out: list[str] = []
    for idx, tid in enumerate(ids):
        if not isinstance(tid, str) or not tid.strip():
            raise TypeError(f"core-200 term id {idx} must be a non-empty str")
        out.append(tid.strip())
    return out


def _validate_budget(budget: int) -> None:
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError(f"budget must be an int, got {type(budget).__name__}")
    if budget < 0 or budget > MAX_KEYTERMS:
        raise ValueError(
            f"budget must be between 0 and {MAX_KEYTERMS}, got {budget}"
        )


def static_head_terms(
    core200: Any, glossary: Iterable[dict], *, budget: int = 200
) -> list[str]:
    """Build the fixed ``static-head-200`` list for one budget.

    Core-200 ids keep their payload order and come first; the list is then
    padded from the glossary in ``(canon, surface)`` order, so the result is
    independent of glossary permutation, ``PYTHONHASHSEED`` and the call
    under test. Raises ``ValueError`` for an unknown core-200 id or a
    glossary too small to fill ``budget`` exactly.
    """
    _validate_budget(budget)
    id_to_surface, pool = _glossary_index(glossary)
    term_ids = _term_ids(core200)

    unknown = sorted({tid for tid in term_ids if tid not in id_to_surface})
    if unknown:
        raise ValueError(f"unknown core-200 term id(s): {unknown}")

    chosen: list[str] = []
    seen: set[str] = set()

    def take(surface: str) -> None:
        key = canon(surface)
        if not key or key in seen:
            return
        seen.add(key)
        chosen.append(surface)

    for tid in term_ids:
        if len(chosen) >= budget:
            break
        take(id_to_surface[tid])
    for surface in pool:
        if len(chosen) >= budget:
            break
        take(surface)

    assert_exact_budget(chosen, budget, arm=ARM_NAME)
    return chosen


def static_head_from_file(
    core200_path: str = "data/core200.json",
    glossary_path: str = "data/glossary.json",
    budget: int = 200,
) -> list[str]:
    """Load ``core200.json`` and ``glossary.json`` and build the static arm."""
    core = json.loads(Path(core200_path).read_text(encoding="utf-8"))
    glossary = json.loads(Path(glossary_path).read_text(encoding="utf-8"))
    return static_head_terms(core, glossary, budget=budget)
