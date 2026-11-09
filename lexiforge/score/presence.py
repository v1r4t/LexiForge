"""Term-present-anywhere sensitivity metric (task P03).

The frozen matcher scores recall by token alignment: a hypothesis span is a
hit only if it aligns to a reference span of the same term. That is the right
definition for H1 (``docs/preregistration.md`` section 3), but it is harsh on
a hypothesis that contains every term in a different order, and it can hide a
recognition failure behind a positional one.

This module adds a descriptive **sensitivity** metric: each reference term
occurrence counts as present when the same term appears anywhere in the
hypothesis, at a token boundary. It is reported next to H1/H2 and never
replaces them; ``lexiforge.report.keyterm_health.verdict()`` does not read it.
The metric is pure and the frozen :func:`lexiforge.score.match.score_file`
is untouched.

Definitions (per term id, occurrences counted separately):

* ``reference`` -- glossary-term spans found in the reference.
* ``hypothesis`` -- glossary-term spans found in the hypothesis.
* ``strict_hits`` -- reference occurrences the frozen matcher pairs with an
  aligned hypothesis span (the H1 numerator).
* ``anywhere_hits`` -- ``min(reference, hypothesis)``; a hypothesis repeat
  cannot satisfy two reference occurrences.
* ``strict`` / ``anywhere`` -- hits divided by ``reference``; ``None`` when a
  term has no reference occurrence, matching the ``term_recall`` convention.

Overall rates sum over term ids, so the unit is the (utterance, term
occurrence) pair. Token-boundary matching comes from
:func:`lexiforge.score.match.find_spans`; a suffix such as ``NEFTAA`` is not
an occurrence of ``NEFT``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from lexiforge.score.match import find_spans, score_file_detail

__all__ = ["presence_score"]


def _rate(numerator: int, denominator: int) -> float | None:
    """Return ``numerator / denominator``, or ``None`` for an empty stratum."""
    if denominator == 0:
        return None
    return numerator / denominator


def presence_score(
    reference_text: str,
    hypothesis_text: str,
    glossary: Sequence[dict] | Mapping[str, Any],
) -> dict[str, Any]:
    """Score term presence in ``hypothesis_text`` against ``reference_text``.

    Returns ``{"strict", "anywhere", "by_term"}``. ``strict`` is exactly the
    frozen aligned-recall numerator over its occurrence denominator, so it can
    be compared with :func:`lexiforge.score.match.score_file`. ``anywhere``
    ignores ordering and alignment. ``by_term`` maps every term id seen in
    either text to its counts and rates, sorted by term id.

    Raises :class:`lexiforge.score.match.AliasCollision` if the glossary has
    two term ids sharing an alias key, as the frozen matcher does.
    """
    ref_spans = find_spans(reference_text, glossary)
    hyp_spans = find_spans(hypothesis_text, glossary)
    detail = score_file_detail(reference_text, hypothesis_text, glossary)

    ref_counts = Counter(str(span["term_id"]) for span in ref_spans)
    hyp_counts = Counter(str(span["term_id"]) for span in hyp_spans)
    strict_hits = Counter(
        str(row["term_id"])
        for row in detail["rows"]
        if row["in_denom"] and row["hit"]
    )

    by_term: dict[str, dict[str, Any]] = {}
    for term_id in sorted(ref_counts.keys() | hyp_counts.keys()):
        n_reference = ref_counts[term_id]
        n_hypothesis = hyp_counts[term_id]
        n_strict = strict_hits[term_id]
        n_anywhere = min(n_reference, n_hypothesis)
        by_term[term_id] = {
            "reference": n_reference,
            "hypothesis": n_hypothesis,
            "strict_hits": n_strict,
            "anywhere_hits": n_anywhere,
            "strict": _rate(n_strict, n_reference),
            "anywhere": _rate(n_anywhere, n_reference),
        }

    total_reference = len(ref_spans)
    total_strict = sum(strict_hits.values())
    total_anywhere = sum(row["anywhere_hits"] for row in by_term.values())
    return {
        "strict": _rate(total_strict, total_reference),
        "anywhere": _rate(total_anywhere, total_reference),
        "by_term": by_term,
    }
