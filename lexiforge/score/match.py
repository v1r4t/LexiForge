"""Exact longest-span term matcher and file scorer (frozen scoring step).

Rules (docs/design.md section 5): canonicalise every surface with the frozen
:func:`lexiforge.canon.canon` rules, match glossary aliases exactly (no fuzzy
or phonetic logic here), longest span first, non-overlapping spans.

Insertions are defined by token-aligning reference to hypothesis: a
hypothesis span is a hit if and only if it aligns to a reference span of the
same term; otherwise it is an insertion. This keeps a correctly transcribed
ordinary word from being scored as an insertion merely because it sounds like
a glossary term (exact matching means such words produce no spans at all,
and same-term alignment turns shared homographs into hits, not insertions).
"""

from __future__ import annotations

import difflib
import json
import unicodedata
from pathlib import Path

from lexiforge.canon import canon

__all__ = [
    "AliasCollision",
    "HardNegativeCollision",
    "assert_hard_negatives_separable",
    "build_alias_map",
    "find_spans",
    "load_glossary",
    "score_file",
]


class AliasCollision(ValueError):
    """Two different term ids canonicalise to the same alias key."""


class HardNegativeCollision(ValueError):
    """A pre-registered hard-negative pair canonicalises to the same key."""


_APOSTROPHES = frozenset("'\u2018\u2019\u02bc`")


def _is_boundary(ch: str) -> bool:
    return ch.isspace() or unicodedata.category(ch)[0] in {"P", "S"}


def _tokenize_with_spans(text: str) -> list[tuple[str, int, int]]:
    """Split ``text`` into ``(canon_key, start, end)`` tokens.

    Mirrors the frozen ``canon`` pipeline (punctuation -> separators,
    apostrophes deleted, acronym letter-runs of 3-6 joined) while tracking
    character offsets into the original string. ``start``/``end`` always
    index ``text`` itself, so ``text[start:end]`` is the raw surface.
    """
    if text is None:
        raise TypeError("text must be str, not None")
    # 1:1 character swap (chandrabindu -> anusvara, as in canon step 3), so
    # indices into the working copy stay valid for the original text.
    work = text.replace("\u0901", "\u0902")
    raw_toks: list[tuple[str, int, int]] = []
    buf: list[str] = []
    start = 0
    for i, ch in enumerate(work):
        if ch in _APOSTROPHES:
            continue  # deleted, never a token boundary (canon step 6)
        if _is_boundary(ch):
            if buf:
                raw = "".join(buf)
                key = canon(raw)
                if key:
                    # Token ran from `start` to the boundary at `i`.
                    raw_toks.append((key, start, i))
                buf = []
            continue
        if not buf:
            start = i
        buf.append(ch)
    if buf:
        raw = "".join(buf)
        key = canon(raw)
        if key:
            raw_toks.append((key, start, len(work)))
    # Acronym letter-joining (canon step 7): runs of 3-6 single letters join.
    out: list[tuple[str, int, int]] = []
    i = 0
    while i < len(raw_toks):
        key, s, _ = raw_toks[i]
        if len(key) == 1 and key.isalpha():
            j = i
            while (
                j < len(raw_toks)
                and len(raw_toks[j][0]) == 1
                and raw_toks[j][0].isalpha()
            ):
                j += 1
            if 3 <= (j - i) <= 6:
                out.append(("".join(k for k, _, _ in raw_toks[i:j]), s, raw_toks[j - 1][2]))
            else:
                out.extend(raw_toks[i:j])
            i = j
        else:
            out.append(raw_toks[i])
            i += 1
    return out


def _term_id(term) -> str:
    if isinstance(term, str):
        return term
    for field in ("id", "term_id", "term", "name", "key"):
        if term.get(field):
            return str(term[field])
    raise KeyError(f"glossary entry has no id field: {term!r}")


def _term_aliases(term) -> list[str]:
    if isinstance(term, str):
        return [term]
    for field in ("aliases", "variants", "surfaces", "alias"):
        if term.get(field):
            value = term[field]
            return [value] if isinstance(value, str) else list(value)
    for field in ("term", "name", "surface", "canonical"):
        if term.get(field):
            return [str(term[field])]
    tid = _term_id(term)
    return [tid]


def load_glossary(path) -> list[dict]:
    """Load a glossary JSON file and return the term-entry list.

    Accepts a bare list of entries, a ``{id: aliases}`` mapping, or an
    object holding the list under ``terms``/``glossary``/``entries``.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        for field in ("terms", "glossary", "entries"):
            if isinstance(raw.get(field), list):
                return list(raw[field])
        if all(isinstance(v, (list, str)) for v in raw.values()):
            return [{"id": k, "aliases": v} for k, v in raw.items()]
        raise ValueError(f"unrecognised glossary object keys: {sorted(raw)}")
    if isinstance(raw, list):
        return list(raw)
    raise ValueError(f"unrecognised glossary top level: {type(raw).__name__}")


def build_alias_map(glossary) -> dict[str, str]:
    """Build the ``canon_key -> term_id`` lookup for a glossary.

    Raises :class:`AliasCollision` if aliases of two different term ids
    canonicalise to the same key.
    """
    if isinstance(glossary, dict) and all(
        isinstance(v, str) for v in glossary.values()
    ):
        return dict(glossary)  # already an alias map
    alias_map: dict[str, str] = {}
    for term in glossary:
        tid = _term_id(term)
        for alias in _term_aliases(term):
            key = canon(alias)
            if not key:
                continue
            owner = alias_map.get(key)
            if owner is not None and owner != tid:
                raise AliasCollision(
                    f"alias key {key!r} shared by term {owner!r} and term {tid!r}"
                )
            alias_map[key] = tid
    return alias_map


def find_spans(text: str, glossary) -> list[dict]:
    """Find non-overlapping glossary-term spans in ``text``.

    Exact alias matching on canonical keys only, longest span first
    (ties broken left to right). Each span is
    ``{start, end, term_id, surface, canon_key}`` with ``start``/``end``
    indexing ``text``. Raises :class:`AliasCollision` if two term ids
    share an alias key.
    """
    alias_map = build_alias_map(glossary)
    if not alias_map:
        return []
    max_n = max(len(key.split()) for key in alias_map)
    toks = _tokenize_with_spans(text)
    keys = [key for key, _, _ in toks]
    # Collect every candidate n-gram, then take longest spans first so a
    # longer alias always beats an overlapping shorter one.
    candidates: list[tuple[int, int, int, str, str]] = []  # (-n, i, n, key, tid)
    for i in range(len(keys)):
        for n in range(min(max_n, len(keys) - i), 0, -1):
            key = " ".join(keys[i : i + n])
            tid = alias_map.get(key)
            if tid is not None:
                candidates.append((-n, i, n, key, tid))
    candidates.sort()
    used = [False] * len(keys)
    spans: list[dict] = []
    for _, i, n, key, tid in candidates:
        if any(used[i : i + n]):
            continue
        for k in range(i, i + n):
            used[k] = True
        spans.append(
            {
                "start": toks[i][1],
                "end": toks[i + n - 1][2],
                "term_id": tid,
                "surface": text[toks[i][1] : toks[i + n - 1][2]],
                "canon_key": key,
            }
        )
    spans.sort(key=lambda s: s["start"])
    return spans


def _align_hyp_to_ref(
    ref_keys: list[str], hyp_keys: list[str]
) -> dict[int, int]:
    """Map hypothesis token index -> reference token index via token alignment."""
    mapping: dict[int, int] = {}
    matcher = difflib.SequenceMatcher(a=ref_keys, b=hyp_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                mapping[j1 + k] = i1 + k
    return mapping


def score_file(
    reference_text: str, hypothesis_text: str, glossary
) -> dict:
    """Score one utterance pair against the glossary.

    A hypothesis span is a hit iff it aligns (on canonical tokens) to a
    reference span of the same term; otherwise it is an insertion. A
    reference span with no matching hypothesis span is a miss.
    """
    ref_spans = find_spans(reference_text, glossary)
    hyp_spans = find_spans(hypothesis_text, glossary)
    ref_keys = [key for key, _, _ in _tokenize_with_spans(reference_text)]
    hyp_keys = [key for key, _, _ in _tokenize_with_spans(hypothesis_text)]
    hyp_to_ref = _align_hyp_to_ref(ref_keys, hyp_keys)

    # Reference token index -> owning reference-span index.
    ref_tok_owner: dict[int, int] = {}
    ref_tok_ranges: list[tuple[int, int]] = []
    hyp_tok_ranges: list[tuple[int, int]] = []
    for toks, spans, ranges in (
        (_tokenize_with_spans(reference_text), ref_spans, ref_tok_ranges),
        (_tokenize_with_spans(hypothesis_text), hyp_spans, hyp_tok_ranges),
    ):
        surfaces = [(s, e) for _, s, e in toks]
        for span in spans:
            lo = next(i for i, (_, s, e) in enumerate(toks) if s == span["start"])
            hi = next(
                i
                for i, (_, s, e) in enumerate(toks)
                if e == span["end"] and i >= lo
            )
            ranges.append((lo, hi + 1))
        _ = surfaces
    for idx, (lo, hi) in enumerate(ref_tok_ranges):
        for t in range(lo, hi):
            ref_tok_owner[t] = idx

    hits = 0
    insertions = 0
    consumed = [False] * len(ref_spans)
    for h_idx, h_span in enumerate(hyp_spans):
        lo, hi = hyp_tok_ranges[h_idx]
        aligned = {hyp_to_ref[t] for t in range(lo, hi) if t in hyp_to_ref}
        hit_idx: int | None = None
        for r_idx, r_span in enumerate(ref_spans):
            if consumed[r_idx] or r_span["term_id"] != h_span["term_id"]:
                continue
            rlo, rhi = ref_tok_ranges[r_idx]
            if aligned & set(range(rlo, rhi)):
                hit_idx = r_idx
                break
        if hit_idx is None:
            insertions += 1
        else:
            consumed[hit_idx] = True
            hits += 1
    misses = sum(1 for c in consumed if not c)
    return {
        "hits": hits,
        "insertions": insertions,
        "misses": misses,
        "n_reference_occurrences": len(ref_spans),
        "n_hypothesis_spans": len(hyp_spans),
    }


def assert_hard_negatives_separable(glossary, pairs) -> None:
    """Assert no hard-negative pair canonicalises to the same key.

    Pair elements may be raw surfaces or glossary term ids (resolved to all
    of that term's alias keys). Raises :class:`HardNegativeCollision`
    naming the shared key.
    """
    build_alias_map(glossary)  # validate the glossary itself first
    by_id: dict[str, list[str]] = {}
    if isinstance(glossary, list):
        for term in glossary:
            try:
                by_id[_term_id(term)] = _term_aliases(term)
            except KeyError:
                continue

    def _keys(element: str) -> set[str]:
        if element in by_id:
            return {canon(a) for a in by_id[element] if canon(a)}
        key = canon(element)
        return {key} if key else set()

    for pair in pairs:
        first, second = pair
        shared = _keys(first) & _keys(second)
        if shared:
            key = sorted(shared)[0]
            raise HardNegativeCollision(
                f"hard-negative pair {first!r} vs {second!r} "
                f"collides on key {key!r}"
            )
