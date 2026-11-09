"""Oracle control arms: spoken terms only, and spoken terms plus padding.

Design §2 defines ``oracle-minimal`` as the terms actually spoken in a call and
``oracle-200`` as those terms followed by seeded non-true padding to an exact
budget. The pair is a positive control, not a confirmatory arm: oracle-200 is
the ceiling a relevant list can reach, so it must contain every expected term,
must never pad with a term that canonicalises to an expected one, and must be
reproducible byte-for-byte in a fresh process (design §5 invariants:
process-stable seeding and exact equal-budget arms).

Padding is drawn from the glossary's canonical surfaces in a stable order and
re-ranked by a sha256 digest of ``(seed, canonical key)``. No set iteration or
filesystem order is consulted, so ``PYTHONHASHSEED`` cannot change the output.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterator, Mapping
from typing import Any

from lexiforge.canon import canon
from lexiforge.contexts.build import MAX_KEYTERMS, assert_exact_budget

_ENTRY_TEXT_KEYS = ("canonical", "term", "name", "surface", "text", "value")
_ENTRY_ID_KEYS = ("term_id", "id", "termId")
_ENTRY_FORM_KEYS = (
    "scoring_aliases",
    "aliases",
    "alias",
    "variants",
    "spoken_forms",
    "surfaces",
)
_ENTRY_KEY_KEYS = (*_ENTRY_TEXT_KEYS, *_ENTRY_ID_KEYS)


def _surface(text: str) -> str:
    """NFC-normalise and collapse whitespace the way the context builder does."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _string_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_surface(value)]
    if isinstance(value, (set, frozenset)):
        return [_surface(item) for item in sorted(value, key=str) if isinstance(item, str)]
    if isinstance(value, (list, tuple)):
        return [_surface(item) for item in value if isinstance(item, str)]
    return []


def _looks_like_entry(value: Mapping) -> bool:
    return any(key in value for key in _ENTRY_KEY_KEYS)


def _walk(value: Any) -> Iterator[Any]:
    """Yield glossary/expected-term entries in a deterministic order."""
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        if _looks_like_entry(value):
            yield value
        else:
            for key in sorted(value, key=str):
                yield from _walk(value[key])
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        for item in items:
            yield from _walk(item)
        return
    raise TypeError(
        "expected terms and glossary entries must be str or mappings, "
        f"got {type(value).__name__}"
    )


def _entry_id(entry: Any) -> str | None:
    if not isinstance(entry, Mapping):
        return None
    for key in _ENTRY_ID_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _entry_surface(entry: Any) -> str:
    if isinstance(entry, str):
        text = _surface(entry)
    elif isinstance(entry, Mapping):
        text = ""
        for key in _ENTRY_TEXT_KEYS:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                text = _surface(value)
                break
        if not text:
            for key in _ENTRY_ID_KEYS:
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    text = _surface(value)
                    break
    else:
        raise TypeError(
            "expected terms and glossary entries must be str or mappings, "
            f"got {type(entry).__name__}"
        )
    if not text:
        raise ValueError("term entry has no non-empty surface")
    return text


def _entry_forms(entry: Any) -> list[str]:
    """Every surface one entry carries: primary, aliases, variants, spoken forms."""
    forms = [_entry_surface(entry)]
    if isinstance(entry, Mapping):
        for key in _ENTRY_FORM_KEYS:
            forms.extend(_string_items(entry.get(key)))
        variants = entry.get("script_variants")
        if isinstance(variants, Mapping):
            forms.extend(_string_items(list(variants.values())))
    return [form for form in forms if form]


def _surface_key(surface: str) -> tuple[int, str, str]:
    """Stable representative choice: shortest, then casefolded, then literal."""
    return (len(surface), surface.casefold(), surface)


def _remember(target: dict[str, str], key: str, surface: str) -> None:
    current = target.get(key)
    if current is None or _surface_key(surface) < _surface_key(current):
        target[key] = surface


class _GlossaryIndex:
    """Normalised, permutation-stable view of the glossary."""

    def __init__(self) -> None:
        self.entries_by_id: dict[str, Any] = {}
        self.canon_to_surface: dict[str, str] = {}
        self.canon_to_entry: dict[str, Any] = {}
        self.pad_pool: dict[str, str] = {}


def _index_glossary(glossary: Any) -> _GlossaryIndex:
    index = _GlossaryIndex()
    for entry in _walk(glossary):
        primary = _entry_surface(entry)
        term_id = _entry_id(entry)
        if term_id is not None:
            index.entries_by_id.setdefault(term_id, entry)

        for form in _entry_forms(entry):
            key = canon(form)
            if not key:
                continue
            _remember(index.canon_to_surface, key, primary)
            current = index.canon_to_entry.get(key)
            if current is None or _surface_key(primary) < _surface_key(
                _entry_surface(current)
            ):
                index.canon_to_entry[key] = entry

        key = canon(primary)
        if key:
            _remember(index.pad_pool, key, primary)
    return index


def _resolve_expected(
    expected_terms: Any, index: _GlossaryIndex
) -> tuple[list[str], set[str]]:
    """Resolve expected terms to one surface each and collect every true key.

    A glossary ID resolves to its canonical surface; any other string keeps its
    spelling, so a caller that passes canonical surfaces gets them back in the
    same order. The key set includes every alias and script variant of a matched
    entry, which is what padding must stay disjoint from.
    """
    surfaces: list[str] = []
    seen: set[str] = set()
    expected_keys: set[str] = set()

    for item in _walk(expected_terms):
        if isinstance(item, str):
            text = _surface(item)
            if not text:
                continue
            matched = index.entries_by_id.get(text) or index.canon_to_entry.get(
                canon(text)
            )
            forms = _entry_forms(matched) if matched is not None else [text]
            primary = _entry_surface(matched) if text in index.entries_by_id else text
        else:
            forms = _entry_forms(item)
            term_id = _entry_id(item)
            matched = index.entries_by_id.get(term_id) if term_id else None
            if matched is not None:
                forms = _entry_forms(matched) + forms
                primary = _entry_surface(matched)
            else:
                primary = _entry_surface(item)

        for form in forms:
            key = canon(form)
            if key:
                expected_keys.add(key)

        key = canon(primary)
        if key and key not in seen:
            seen.add(key)
            surfaces.append(primary)

    if not surfaces:
        raise ValueError("expected_terms must contain at least one non-empty term")
    return surfaces, expected_keys


def _seed_key(seed: Any, canonical: str) -> str:
    payload = f"{seed}\x1f{canonical}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _padding(
    index: _GlossaryIndex, expected_keys: set[str], needed: int, seed: Any
) -> list[str]:
    if needed <= 0:
        return []
    candidates = [
        surface
        for key, surface in index.pad_pool.items()
        if key not in expected_keys
    ]
    if len(candidates) < needed:
        raise ValueError(
            f"oracle-200 padding pool too small: need {needed} non-true terms, "
            f"found {len(candidates)}"
        )
    candidates.sort(key=lambda surface: (_seed_key(seed, canon(surface)), canon(surface), surface))
    return candidates[:needed]


def _validate_budget(budget: Any) -> None:
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError(f"budget must be an int, got {type(budget).__name__}")
    if budget < 0 or budget > MAX_KEYTERMS:
        raise ValueError(f"budget must be between 0 and {MAX_KEYTERMS}, got {budget}")


def build_oracle_minimal(expected_terms: Any) -> list[str]:
    """Return the spoken terms only, deduplicated by frozen canonical key.

    This is the floor control: no padding, so its length is the call's true
    term count and it is never compared as an equal-budget arm.
    """
    result: list[str] = []
    seen: set[str] = set()
    for entry in _walk(expected_terms):
        surface = _entry_surface(entry)
        key = canon(surface)
        if key and key not in seen:
            seen.add(key)
            result.append(surface)
    if not result:
        raise ValueError("expected_terms must contain at least one non-empty term")
    return result


def build_oracle_200(
    expected_terms: Any,
    glossary: Any,
    *,
    budget: int = 200,
    seed: int = 0,
) -> list[str]:
    """Return exactly ``budget`` unique canonical surfaces, true terms first.

    The expected (spoken) surfaces lead in input order. The remainder is
    seeded padding drawn from the glossary with every expected canonical key
    excluded. A glossary too small to fill the arm raises ``ValueError`` rather
    than silently shrinking it.
    """
    _validate_budget(budget)
    index = _index_glossary(glossary)
    expected, expected_keys = _resolve_expected(expected_terms, index)

    if len(expected) > budget:
        raise ValueError(
            f"budget {budget} cannot hold {len(expected)} expected terms: "
            "oracle-200 must contain every spoken term"
        )

    result = expected + _padding(index, expected_keys, budget - len(expected), seed)
    assert_exact_budget(result, budget, arm="oracle-200")
    return result
