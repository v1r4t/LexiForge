"""Alias and transliteration audit for the glossary.

Design references: ``docs/design.md`` §4.1 (alias sources) and §5 (the frozen
canonicaliser). The audit is read-only: it never edits the glossary and its
transliteration map is a *proposal aid only* — the frozen matcher keeps
Devanagari and Latin in separate namespaces.

Aliases may originate only from the three allowed sources (design §4.1):
authoring variants, rule-generated transliterations, and pre-freeze attested
lists. ASR output is never an alias source; any surface tagged with another
source raises :class:`ValueError` before the audit runs.

The audit is pairwise on purpose: :func:`lexiforge.score.match.build_alias_map`
raises on the first collision, which would hide every later one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from lexiforge.canon import CANON_VERSION, canon

__all__ = ["ALLOWED_ALIAS_SOURCES", "audit_glossary"]

ALLOWED_ALIAS_SOURCES = frozenset(
    {"authoring variant", "rule transliteration", "pre-freeze attested"}
)

_DEVANAGARI_RANGE = (0x0900, 0x097F)

_ALIAS_FIELDS = ("scoring_aliases", "aliases", "variants", "surfaces", "alias")

_ID_FIELDS = ("term_id", "id", "termId")
_CANONICAL_FIELDS = ("canonical", "term", "name", "surface", "keyterm")
_SURFACE_FIELDS = ("surface", "text", "value", "term", "alias", "canonical")
_SOURCE_FIELDS = ("source", "provenance", "origin")

# Character-level Devanagari -> Latin map. It mirrors the rule generator used
# to build ``script_variants`` (one Latin letter per Devanagari letter, no
# inherent vowel), so transliterating a generated variant recovers the Latin
# surface. Never used for scoring.
_DEVA_TO_LATN = {
    "अ": "a",
    "आ": "aa",
    "इ": "i",
    "ई": "ii",
    "उ": "u",
    "ऊ": "uu",
    "ऋ": "ri",
    "ए": "e",
    "ऐ": "ai",
    "ओ": "o",
    "औ": "au",
    "क": "k",
    "ख": "kh",
    "ग": "g",
    "घ": "gh",
    "ङ": "n",
    "च": "ch",
    "छ": "chh",
    "ज": "j",
    "झ": "jh",
    "ञ": "n",
    "ट": "t",
    "ठ": "th",
    "ड": "d",
    "ढ": "dh",
    "ण": "n",
    "त": "t",
    "थ": "th",
    "द": "d",
    "ध": "dh",
    "न": "n",
    "प": "p",
    "फ": "ph",
    "ब": "b",
    "भ": "bh",
    "म": "m",
    "य": "y",
    "र": "r",
    "ल": "l",
    "व": "v",
    "श": "sh",
    "ष": "sh",
    "स": "s",
    "ह": "h",
    "ळ": "l",
    "ा": "a",
    "ि": "i",
    "ी": "ii",
    "ु": "u",
    "ू": "uu",
    "ृ": "ri",
    "े": "e",
    "ै": "ai",
    "ो": "o",
    "ौ": "au",
    "ं": "n",
    "ँ": "n",
    "ः": "h",
    "्": "",
    "़": "",
    "०": "0",
    "१": "1",
    "२": "2",
    "३": "3",
    "४": "4",
    "५": "5",
    "६": "6",
    "७": "7",
    "८": "8",
    "९": "9",
}


def _script_of(text: str) -> str:
    if any(_DEVANAGARI_RANGE[0] <= ord(ch) <= _DEVANAGARI_RANGE[1] for ch in text):
        return "deva"
    return "latn"


def _transliterate_devanagari(text: str) -> str:
    return "".join(_DEVA_TO_LATN.get(ch, ch) for ch in text)


def _translit_key(surface: str) -> str:
    if _script_of(surface) == "deva":
        return canon(_transliterate_devanagari(surface))
    return canon(surface)


def _term_id(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return None
    for field in _ID_FIELDS:
        value = entry.get(field)
        if value not in (None, ""):
            return str(value)
    return None


def _canonical(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return None
    for field in _CANONICAL_FIELDS:
        value = entry.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _surface_and_source(value: Any, *, term_id: str) -> tuple[str, str | None]:
    """Return ``(surface, declared_source)`` from a string or structured alias."""
    if isinstance(value, str):
        return value, None
    if isinstance(value, dict):
        surface = next(
            (
                value[field]
                for field in _SURFACE_FIELDS
                if isinstance(value.get(field), str) and value[field]
            ),
            None,
        )
        if surface is None:
            raise ValueError(f"term {term_id!r} has an alias with no surface: {value!r}")
        source = next(
            (
                value[field]
                for field in _SOURCE_FIELDS
                if isinstance(value.get(field), str) and value[field]
            ),
            None,
        )
        return surface, source
    raise ValueError(f"term {term_id!r} has a non-string alias: {value!r}")


def _check_source(source: str | None, *, term_id: str, surface: str) -> str | None:
    if source is None:
        return None
    normalised = " ".join(source.strip().lower().split())
    if normalised not in ALLOWED_ALIAS_SOURCES:
        allowed = ", ".join(sorted(ALLOWED_ALIAS_SOURCES))
        raise ValueError(
            f"term {term_id!r} surface {surface!r} has disallowed alias source "
            f"{source!r}; allowed sources: {allowed}"
        )
    return normalised


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _term_surfaces(entry: Any) -> list[dict[str, str]]:
    """Declared surfaces for one entry, with their field and source."""
    term_id = _term_id(entry)
    if term_id is None:
        return []
    surfaces: list[dict[str, str]] = []

    canonical = _canonical(entry)
    if canonical:
        surfaces.append({"surface": canonical, "field": "canonical", "source": "authoring variant"})

    if not isinstance(entry, dict):
        return surfaces

    for field in _ALIAS_FIELDS:
        if field not in entry:
            continue
        label = "scoring_alias" if field == "scoring_aliases" else "alias"
        for value in _as_list(entry[field]):
            surface, source = _surface_and_source(value, term_id=term_id)
            surfaces.append(
                {
                    "surface": surface,
                    "field": label,
                    "source": _check_source(source, term_id=term_id, surface=surface)
                    or "authoring variant",
                }
            )

    variants = entry.get("script_variants")
    if isinstance(variants, dict):
        for script in sorted(variants):
            surface, source = _surface_and_source(variants[script], term_id=term_id)
            surfaces.append(
                {
                    "surface": surface,
                    "field": f"script_variant:{script}",
                    "source": _check_source(source, term_id=term_id, surface=surface)
                    or "rule transliteration",
                }
            )

    for value in _as_list(entry.get("spoken_forms")):
        surface, source = _surface_and_source(value, term_id=term_id)
        surfaces.append(
            {
                "surface": surface,
                "field": "spoken_form",
                "source": _check_source(source, term_id=term_id, surface=surface)
                or "pre-freeze attested",
            }
        )
    return surfaces


def _dedupe_surfaces(surfaces: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for item in surfaces:
        marker = (item["surface"], item["field"])
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def _used_terms(scripts_dir: Path) -> dict[str, list[str]]:
    """Map term id -> sorted call ids that reference it in committed scripts."""
    if not scripts_dir.exists():
        raise FileNotFoundError(f"scripts directory not found: {scripts_dir}")
    used: dict[str, set[str]] = {}
    for path in sorted(scripts_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        call = str(payload.get("call_id") or path.stem)
        ids: list[str] = []
        for turn in payload.get("turns") or []:
            if isinstance(turn, dict):
                ids.extend(str(t) for t in _as_list(turn.get("glossary_terms")) if t is not None)
        for key in ("expected_real", "expected_fictional"):
            ids.extend(str(t) for t in _as_list(payload.get(key)) if t is not None)
        for term_id in ids:
            used.setdefault(term_id, set()).add(call)
    return {term_id: sorted(calls) for term_id, calls in used.items()}


def audit_glossary(
    glossary: Iterable[Any], *, scripts_dir: str | Path | None = None
) -> dict[str, Any]:
    """Audit a glossary for alias collisions and transliteration hazards.

    Returns ``{"collisions", "missing_spoken_forms", "cross_script_dupes",
    "proposed_aliases", "summary"}`` with deterministic ordering. The glossary
    is only read. ``scripts_dir`` makes the audit usage-driven: it reports
    spoken-form gaps and alias proposals for terms the committed scripts
    actually use. Raises :class:`ValueError` for any surface tagged with a
    disallowed alias source (for example ASR output).
    """
    by_term: dict[str, Any] = {}
    surfaces_by_term: dict[str, list[dict[str, str]]] = {}
    for entry in glossary:
        term_id = _term_id(entry)
        if term_id is None:
            continue
        by_term.setdefault(term_id, entry)
        surfaces_by_term.setdefault(term_id, []).extend(_term_surfaces(entry))

    # Pairwise exact-key collisions across different term ids.
    owners: dict[str, dict[str, list[dict[str, str]]]] = {}
    for term_id in sorted(surfaces_by_term):
        for item in _dedupe_surfaces(surfaces_by_term[term_id]):
            key = canon(item["surface"])
            if not key:
                continue
            per_term = owners.setdefault(key, {})
            per_term.setdefault(term_id, []).append(item)

    collisions: list[dict[str, Any]] = []
    for key in sorted(owners):
        per_term = owners[key]
        if len(per_term) < 2:
            continue
        terms = [
            {
                "term_id": term_id,
                "surface": sorted((item["surface"], item["field"]) for item in items)[0][0],
                "field": sorted((item["surface"], item["field"]) for item in items)[0][1],
            }
            for term_id, items in sorted(per_term.items())
        ]
        collisions.append({"canon_key": key, "terms": terms})

    # Cross-script hazards: a Devanagari surface and a Latin surface that only
    # collide after rule transliteration. Plain ``canon`` cannot see these.
    translit_owners: dict[str, dict[str, set[tuple[str, str]]]] = {}
    for term_id in sorted(surfaces_by_term):
        for item in _dedupe_surfaces(surfaces_by_term[term_id]):
            surface = item["surface"]
            key = _translit_key(surface)
            if not key:
                continue
            per_term = translit_owners.setdefault(key, {})
            per_term.setdefault(term_id, set()).add((surface, _script_of(surface)))

    cross_script_dupes: list[dict[str, Any]] = []
    for key in sorted(translit_owners):
        per_term = translit_owners[key]
        if len(per_term) < 2:
            continue
        scripts = {script for found in per_term.values() for _, script in found}
        if len(scripts) < 2:
            continue
        terms = [
            {
                "term_id": term_id,
                "surface": sorted(surface for surface, _ in found)[0],
                "script": sorted(script for _, script in found)[0],
            }
            for term_id, found in sorted(per_term.items())
        ]
        cross_script_dupes.append({"translit_key": key, "terms": terms})

    # Usage-driven gaps and proposals.
    used: dict[str, list[str]] = {}
    if scripts_dir is not None:
        used = _used_terms(Path(scripts_dir))
    candidates = sorted(set(used) & set(by_term)) if scripts_dir is not None else sorted(by_term)

    missing_spoken_forms: list[dict[str, Any]] = []
    for term_id in candidates:
        entry = by_term[term_id]
        has_spoken = False
        if isinstance(entry, dict):
            has_spoken = any(
                (isinstance(value, str) and bool(value)) or isinstance(value, dict)
                for value in _as_list(entry.get("spoken_forms"))
            )
        if has_spoken:
            continue
        missing_spoken_forms.append(
            {
                "term_id": term_id,
                "canonical": _canonical(entry) or "",
                "calls": used.get(term_id, []),
            }
        )

    proposed_aliases: list[dict[str, str]] = []
    for term_id in candidates:
        entry = by_term[term_id]
        if not isinstance(entry, dict):
            continue
        declared = {canon(item["surface"]) for item in surfaces_by_term[term_id]}
        declared.discard("")
        variants = entry.get("script_variants")
        if not isinstance(variants, dict):
            continue
        alias_keys = {canon(_canonical(entry) or "")}
        for field in _ALIAS_FIELDS:
            for value in _as_list(entry.get(field)):
                surface, _ = _surface_and_source(value, term_id=term_id)
                alias_keys.add(canon(surface))
        for value in _as_list(entry.get("spoken_forms")):
            surface, _ = _surface_and_source(value, term_id=term_id)
            alias_keys.add(canon(surface))
        alias_keys.discard("")

        for script in sorted(variants):
            surface, _ = _surface_and_source(variants[script], term_id=term_id)
            key = canon(surface)
            if not key or key in alias_keys or key not in declared:
                continue
            owners_of_key = owners.get(key, {})
            if any(other != term_id for other in owners_of_key):
                continue
            proposed_aliases.append(
                {
                    "term_id": term_id,
                    "surface": surface,
                    "canon_key": key,
                    "source": "rule transliteration",
                }
            )
    proposed_aliases.sort(key=lambda item: (item["term_id"], item["surface"]))

    summary = {
        "n_terms": len(by_term),
        "n_collisions": len(collisions),
        "n_missing_spoken_forms": len(missing_spoken_forms),
        "n_cross_script_dupes": len(cross_script_dupes),
        "n_proposed_aliases": len(proposed_aliases),
        "ok": not collisions and not cross_script_dupes,
        "canon_version": CANON_VERSION,
    }
    return {
        "collisions": collisions,
        "missing_spoken_forms": missing_spoken_forms,
        "cross_script_dupes": cross_script_dupes,
        "proposed_aliases": proposed_aliases,
        "summary": summary,
    }
