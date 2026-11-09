"""Per-term diff and per-call deltas for the Keyterm Health report.

Implements the per-term appendix required by the product report on top of the
frozen matcher. ``term_diff`` keeps the raw expected and heard surfaces so a
canonical-equal but differently spelled form (``U P I`` vs ``UPI``) is visible
as a **variant** hit rather than silently folded into an exact hit. The
insertion rule is the frozen one from docs/design.md section 5: a hypothesis
term counts only when it aligns to a different reference term or to nothing,
and insertion rows never enter the recall denominator.

``per_call_deltas`` follows docs/design.md section 6: one value per call is
computed before any summary, and deltas are signed ``arm - baseline``. No
pooling across calls.

Stdlib only.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from lexiforge.canon import canon
from lexiforge.score.match import (
    _align_hyp_to_ref,
    _term_aliases,
    _term_id,
    _term_origins,
    _tokenize_with_spans,
    build_alias_map,
    find_spans,
)

__all__ = ["per_call_deltas", "term_diff"]

_HIT_STATUSES = frozenset({"hit", "variant"})
_OUT_OF_DENOMINATOR = frozenset({"insertion", "absent"})


def _entries(glossary) -> list:
    """Materialise a glossary iterable, accepting the alias-map shorthand."""
    if isinstance(glossary, Mapping):
        if all(isinstance(value, str) for value in glossary.values()):
            return [{"id": value, "aliases": [key]} for key, value in glossary.items()]
        return [{"id": str(key), "aliases": [str(key)]} for key in glossary]
    return list(glossary or [])


def _token_range(span: Mapping[str, Any], tokens: list[tuple[str, int, int]]) -> tuple[int, int]:
    """Map a character span back to its inclusive/exclusive token range."""
    lo = next(i for i, (_, start, _) in enumerate(tokens) if start == span["start"])
    hi = next(
        i
        for i, (_, _, end) in enumerate(tokens)
        if end == span["end"] and i >= lo
    )
    return lo, hi + 1


def _resolve_terms(values: Iterable[Any] | None, alias_map: Mapping[str, str], known: set[str]) -> set[str]:
    """Resolve term ids or spoken surfaces to glossary term ids."""
    resolved: set[str] = set()
    for value in values or []:
        if isinstance(value, Mapping):
            value = _term_id(value)
        text = str(value)
        if text in known:
            resolved.add(text)
            continue
        term_id = alias_map.get(canon(text))
        if term_id is not None:
            resolved.add(str(term_id))
    return resolved


def _surface_for(term_id: str, entries: list) -> str | None:
    """Return a stable spoken surface for a term id, for absent-term rows."""
    for entry in entries:
        try:
            if str(_term_id(entry)) != term_id:
                continue
        except KeyError:
            continue
        aliases = _term_aliases(entry)
        for alias in aliases:
            if alias:
                return str(alias)
    return None


def _row(
    *,
    term_id: str,
    origin: str | None,
    expected_surface: str | None,
    heard_surface: str | None,
    status: str,
    variant_of: str | None,
    in_selected: bool,
    in_expected: bool,
) -> dict:
    return {
        "term_id": term_id,
        "origin": origin,
        "expected_surface": expected_surface,
        "heard_surface": heard_surface,
        "status": status,
        "variant_of": variant_of,
        "in_selected": in_selected,
        "in_expected": in_expected,
        "in_denom": status not in _OUT_OF_DENOMINATOR,
    }


def term_diff(
    ref: str,
    hyp: str,
    glossary,
    *,
    selected: Iterable[Any] | None = None,
    expected: Iterable[Any] | None = None,
) -> dict:
    """Diff one reference/hypothesis pair term by term.

    Returns ``{"rows", "counts"}``. One row per reference occurrence carries
    ``hit``/``miss``/``variant``; a variant is the same canonical key spelled
    differently (``U P I`` vs ``UPI``). Unmatched hypothesis terms become
    ``insertion`` rows with ``in_denom=False``. Terms named in ``expected`` but
    absent from both texts become ``absent`` rows, also outside the
    denominator. ``selected`` and ``expected`` accept term ids or surfaces and
    only set the ``in_selected``/``in_expected`` flags.
    """
    ref_text = ref or ""
    hyp_text = hyp or ""
    entries = _entries(glossary)
    origins = _term_origins(entries)
    alias_map = build_alias_map(glossary)
    known = set()
    for entry in entries:
        try:
            known.add(str(_term_id(entry)))
        except KeyError:
            continue
    selected_ids = _resolve_terms(selected, alias_map, known)
    expected_ids = _resolve_terms(expected, alias_map, known)

    ref_spans = find_spans(ref_text, glossary)
    hyp_spans = find_spans(hyp_text, glossary)
    ref_tokens = _tokenize_with_spans(ref_text)
    hyp_tokens = _tokenize_with_spans(hyp_text)
    ref_ranges = [_token_range(span, ref_tokens) for span in ref_spans]
    hyp_ranges = [_token_range(span, hyp_tokens) for span in hyp_spans]
    hyp_to_ref = _align_hyp_to_ref(
        [key for key, _, _ in ref_tokens],
        [key for key, _, _ in hyp_tokens],
    )

    # Pair hypothesis spans to reference spans with the frozen rule: same term
    # id and at least one aligned token. Everything else is an insertion.
    consumed = [False] * len(ref_spans)
    heard_for_ref: dict[int, int] = {}
    insertion_hyp: list[int] = []
    for h_idx, h_span in enumerate(hyp_spans):
        lo, hi = hyp_ranges[h_idx]
        aligned = {hyp_to_ref[t] for t in range(lo, hi) if t in hyp_to_ref}
        hit_idx: int | None = None
        for r_idx, r_span in enumerate(ref_spans):
            if consumed[r_idx] or r_span["term_id"] != h_span["term_id"]:
                continue
            rlo, rhi = ref_ranges[r_idx]
            if aligned & set(range(rlo, rhi)):
                hit_idx = r_idx
                break
        if hit_idx is None:
            insertion_hyp.append(h_idx)
        else:
            consumed[hit_idx] = True
            heard_for_ref[hit_idx] = h_idx

    rows: list[dict] = []
    seen: set[str] = set()
    for r_idx, span in enumerate(ref_spans):
        term_id = str(span["term_id"])
        seen.add(term_id)
        expected_surface = span["surface"]
        h_idx = heard_for_ref.get(r_idx)
        if h_idx is None:
            status = "miss"
            heard_surface = None
            variant_of = None
        else:
            heard_surface = hyp_spans[h_idx]["surface"]
            if heard_surface == expected_surface:
                status = "hit"
                variant_of = None
            elif canon(heard_surface) == canon(expected_surface):
                status = "variant"
                variant_of = expected_surface
            else:
                # Another alias of the same term: correct, but not a spelling
                # variant under the frozen canonical keys.
                status = "hit"
                variant_of = None
        rows.append(
            _row(
                term_id=term_id,
                origin=origins.get(term_id),
                expected_surface=expected_surface,
                heard_surface=heard_surface,
                status=status,
                variant_of=variant_of,
                in_selected=term_id in selected_ids,
                in_expected=term_id in expected_ids,
            )
        )

    for h_idx in insertion_hyp:
        span = hyp_spans[h_idx]
        term_id = str(span["term_id"])
        seen.add(term_id)
        rows.append(
            _row(
                term_id=term_id,
                origin=origins.get(term_id),
                expected_surface=None,
                heard_surface=span["surface"],
                status="insertion",
                variant_of=None,
                in_selected=term_id in selected_ids,
                in_expected=term_id in expected_ids,
            )
        )

    for term_id in sorted(expected_ids - seen):
        rows.append(
            _row(
                term_id=term_id,
                origin=origins.get(term_id),
                expected_surface=_surface_for(term_id, entries) or term_id,
                heard_surface=None,
                status="absent",
                variant_of=None,
                in_selected=term_id in selected_ids,
                in_expected=True,
            )
        )

    by_status = Counter(row["status"] for row in rows)
    n_denominator = (
        by_status["hit"] + by_status["miss"] + by_status["variant"]
    )
    n_hits = by_status["hit"] + by_status["variant"]
    counts = {
        "hit": by_status["hit"],
        "miss": by_status["miss"],
        "variant": by_status["variant"],
        "insertion": by_status["insertion"],
        "absent": by_status["absent"],
        "n_hits": n_hits,
        "n_reference": n_denominator,
        "n_denominator": n_denominator,
        "n_insertions": by_status["insertion"],
        "recall": n_hits / n_denominator if n_denominator else None,
    }
    return {"rows": rows, "counts": counts}


def _recall(rows: Iterable[Mapping[str, Any]]) -> float | None:
    """One call's term recall; insertion/absent rows stay out of the denom."""
    hits = 0
    denominator = 0
    for row in rows:
        status = row.get("status")
        if status in _HIT_STATUSES:
            hits += 1
            denominator += 1
            continue
        if status == "miss":
            denominator += 1
            continue
        if status in _OUT_OF_DENOMINATOR:
            continue
        if not bool(row.get("in_denom", True)):
            continue
        denominator += 1
        if row.get("hit") is True:
            hits += 1
    if denominator == 0:
        return None
    return hits / denominator


def per_call_deltas(
    rows_by_arm: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    baseline: str,
    cluster_key: str = "call_id",
) -> dict:
    """Paired term-recall deltas, one value per call, signed ``arm - baseline``.

    Each call is reduced to a single recall before summarising, per
    docs/design.md section 6 (never collapse across calls). Calls missing from
    either arm, or with no denominator in either arm, are dropped rather than
    imputed.
    """
    if baseline not in rows_by_arm:
        raise ValueError(f"unknown baseline arm: {baseline!r}")

    grouped: dict[str, dict[Any, list[Mapping[str, Any]]]] = {}
    for arm, rows in rows_by_arm.items():
        by_cluster: dict[Any, list[Mapping[str, Any]]] = {}
        for row in rows or []:
            by_cluster.setdefault(row.get(cluster_key), []).append(row)
        grouped[arm] = by_cluster

    baseline_values = {
        cluster: _recall(rows) for cluster, rows in grouped[baseline].items()
    }

    arms: dict[str, dict] = {}
    for arm, by_cluster in grouped.items():
        if arm == baseline:
            continue
        shared = sorted(
            set(baseline_values) & set(by_cluster),
            key=lambda value: (str(type(value)), repr(value)),
        )
        per_call: dict[Any, dict] = {}
        deltas: list[float] = []
        clusters: list[Any] = []
        for cluster in shared:
            value_a = baseline_values[cluster]
            value_b = _recall(by_cluster[cluster])
            if value_a is None or value_b is None:
                continue
            per_call[cluster] = {
                "baseline": value_a,
                "arm": value_b,
                "delta": value_b - value_a,
            }
            deltas.append(value_b - value_a)
            clusters.append(cluster)
        arms[str(arm)] = {
            "per_call": per_call,
            "deltas": deltas,
            "clusters": clusters,
            "n": len(deltas),
            "mean": sum(deltas) / len(deltas) if deltas else None,
        }

    return {"metric": "term_recall", "baseline": baseline, "arms": arms}
