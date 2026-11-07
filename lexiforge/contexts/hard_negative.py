"""Phonetic hard negatives for the hard-negative-200 context arm.

Design §2: a fixed-budget list of keyterms that are canonically distinct from
the expected terms but phonetically close to at least one of them. The arm asks
whether the decoder inserts or merges near-miss keyterms, so ``skeleton_
similarity`` is the selection signal.

Candidates are drawn from every surface in the full glossary, never from a
reference script. ``is_hard_negative_pair`` is deliberately not used: two
distinct terms sharing a skeleton are the candidates we want, not a collision
to filter out. Only canonical collisions with an expected surface are excluded.

Selection is deterministic across calls, input order and ``PYTHONHASHSEED``:
candidates rank by descending similarity, then by a seed-derived stable digest
over their canonical form.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from lexiforge.canon import canon
from lexiforge.select.phonetic import skeleton_similarity

_ENTRY_TEXT_KEYS = ("canonical", "term", "text", "value", "name", "surface")
_ENTRY_ALIAS_KEYS = (
    "scoring_aliases",
    "aliases",
    "alias",
    "variants",
    "spoken_forms",
    "surfaces",
)
_ENTRY_ID_KEYS = ("term_id", "id")


def _append_strings(out: list[str], value: Any) -> None:
    if isinstance(value, str):
        if value.strip():
            out.append(value)
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        for item in items:
            if isinstance(item, str) and item.strip():
                out.append(item)


def _entry_surfaces(entry: Any) -> list[str]:
    """Every non-empty keyterm surface carried by one glossary entry."""
    forms: list[str] = []
    if isinstance(entry, str):
        _append_strings(forms, entry)
    elif isinstance(entry, Mapping):
        for key in _ENTRY_TEXT_KEYS:
            _append_strings(forms, entry.get(key))
        for key in _ENTRY_ALIAS_KEYS:
            _append_strings(forms, entry.get(key))
    else:
        raise TypeError(f"glossary entry must be str or mapping, got {type(entry).__name__}")

    out: list[str] = []
    seen: set[str] = set()
    for form in forms:
        key = canon(form)
        if key and key not in seen:
            seen.add(key)
            out.append(form)
    return out


def _entry_id(entry: Any) -> str | None:
    if not isinstance(entry, Mapping):
        return None
    for key in _ENTRY_ID_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _iter_entries(value: Any):
    """Walk a glossary/expected-terms container deterministically.

    Accepts the committed list of entry dicts as well as domain-keyed mappings,
    plain term strings and nested lists. Sets are sorted so iteration order
    never depends on ``PYTHONHASHSEED``.
    """
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        looks_like_entry = any(key in value for key in (*_ENTRY_ID_KEYS, *_ENTRY_TEXT_KEYS))
        if looks_like_entry:
            yield value
        else:
            for key in sorted(value, key=str):
                yield from _iter_entries(value[key])
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        for item in items:
            yield from _iter_entries(item)
        return
    raise TypeError(
        f"glossary/expected terms must contain str or mappings, got {type(value).__name__}"
    )


def _glossary_index(glossary: Any) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for entry in _iter_entries(glossary):
        term_id = _entry_id(entry)
        if term_id is not None and term_id not in index:
            index[term_id] = entry
    return index


def _expected_surfaces(expected_terms: Any, by_id: Mapping[str, Any]) -> list[str]:
    """Expand expected terms to raw surfaces, resolving glossary term IDs."""
    forms: list[str] = []
    seen: set[str] = set()

    for item in _iter_entries(expected_terms):
        if isinstance(item, str):
            resolved = by_id.get(item)
            surfaces = _entry_surfaces(resolved) if resolved is not None else [item]
        else:
            surfaces = _entry_surfaces(item)
            term_id = _entry_id(item)
            if term_id is not None and term_id in by_id:
                surfaces.extend(_entry_surfaces(by_id[term_id]))

        for surface in surfaces:
            key = canon(surface)
            if key and key not in seen:
                seen.add(key)
                forms.append(surface)

    if not forms:
        raise ValueError("expected_terms must contain at least one non-empty term")
    return forms


def _surface_key(surface: str) -> tuple[int, str, str]:
    return (len(surface), surface.casefold(), surface)


def _seed_key(seed: Any, canonical: str) -> str:
    payload = f"{seed}\x1f{canonical}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _check_similarity(min_similarity: Any) -> float:
    try:
        threshold = float(min_similarity)
    except (TypeError, ValueError) as exc:
        raise ValueError("min_similarity must be a number in [0, 1]") from exc
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("min_similarity must be a number in [0, 1]")
    return threshold


def rank_candidates(
    glossary: Any,
    expected_terms: Any,
    *,
    min_similarity: float = 0.55,
    seed: Any = 0,
) -> list[tuple[float, str]]:
    """Rank every canonically distinct, phonetically close glossary surface.

    A surface is eligible when its canonical form differs from every expected
    surface and its best ``skeleton_similarity`` against an expected surface is
    at least ``min_similarity``. Punctuation/case variants collapse to one
    canonical form; the shortest, then lexicographically first, spelling is
    kept.

    Returns ``(similarity, surface)`` pairs sorted by descending similarity,
    with ties broken by a digest of ``(seed, canonical form)`` and then the
    canonical form itself.
    """
    threshold = _check_similarity(min_similarity)
    by_id = _glossary_index(glossary)
    expected = _expected_surfaces(expected_terms, by_id)
    expected_canon = {canon(form) for form in expected}

    best: dict[str, tuple[float, str]] = {}
    for entry in _iter_entries(glossary):
        for surface in _entry_surfaces(entry):
            key = canon(surface)
            if not key or key in expected_canon:
                continue
            score = max(skeleton_similarity(surface, term) for term in expected)
            if score < threshold:
                continue
            current = best.get(key)
            if current is None or _surface_key(surface) < _surface_key(current[1]):
                best[key] = (score, surface)

    ranked = sorted(
        best.items(),
        key=lambda item: (-item[1][0], _seed_key(seed, item[0]), item[0]),
    )
    return [(score, surface) for _, (score, surface) in ranked]


def build_hard_negative(
    glossary: Any,
    expected_terms: Any,
    *,
    budget: int = 200,
    seed: Any = 0,
    min_similarity: float = 0.55,
) -> list[str]:
    """Return exactly ``budget`` unique hard-negative keyterm surfaces.

    Raises ``ValueError`` when fewer than ``budget`` eligible candidates exist;
    silently shrinking the arm would turn an equal-budget contrast into a dose
    comparison.
    """
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError("budget must be an int")
    if budget < 0:
        raise ValueError("budget must be non-negative")
    if budget == 0:
        return []

    ranked = rank_candidates(
        glossary,
        expected_terms,
        min_similarity=min_similarity,
        seed=seed,
    )
    if len(ranked) < budget:
        raise ValueError(
            f"hard-negative pool too small: need {budget} candidates, "
            f"found {len(ranked)}"
        )
    return [surface for _, surface in ranked[:budget]]
