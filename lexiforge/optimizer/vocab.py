"""Vocabulary-context optimisation built on the frozen selector.

Wraps :func:`lexiforge.select.ranker.select` so the harness can propose a
per-call context list from a larger glossary. This is the same code path the
experiment uses for the ``adaptive-200`` arm, so an optimiser run and an
experimental arm cannot drift apart.

The selector expects glossary entries shaped as ``{"id": ..., "aliases": [...]}``
while ``data/glossary.json`` stores ``term_id`` / ``canonical`` /
``scoring_aliases``. :func:`to_selector_glossary` is the single adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from lexiforge.canon import CANON_VERSION
from lexiforge.select.ranker import score_breakdown, select

__all__ = [
    "OptimizationResult",
    "VocabularyOptimizer",
    "to_selector_glossary",
]


@dataclass
class OptimizationResult:
    """Outcome of one optimisation pass."""

    selected: List[Dict[str, str]] = field(default_factory=list)
    left_out: List[str] = field(default_factory=list)
    budget: int = 200
    mean_score: float = 0.0
    call_type: str = ""
    metrics: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "canon_version": CANON_VERSION,
            "selected": self.selected,
            "left_out": self.left_out,
            "budget": self.budget,
            "mean_score": round(self.mean_score, 6),
            "call_type": self.call_type,
            "metrics": self.metrics,
        }


def _entry_id(entry: Dict[str, Any]) -> str:
    for key in ("term_id", "id", "termId", "term", "name", "key", "canonical"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError(f"glossary entry has no identifier: {entry!r}")


def _entry_aliases(entry: Dict[str, Any], tid: str) -> List[str]:
    forms: List[str] = []
    for key in ("scoring_aliases", "aliases", "alias", "variants", "surfaces"):
        value = entry.get(key)
        if isinstance(value, str):
            forms.append(value)
        elif isinstance(value, (list, tuple)):
            forms.extend(v for v in value if isinstance(v, str))
    for key in ("canonical", "term", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            forms.append(value)
    variants = entry.get("script_variants")
    if isinstance(variants, dict):
        forms.extend(v for v in variants.values() if isinstance(v, str))
    forms.extend(entry.get("spoken_forms") or [])

    seen: set[str] = set()
    out: List[str] = []
    for form in [*forms, tid]:
        if form and form not in seen:
            seen.add(form)
            out.append(form)
    return out


def to_selector_glossary(glossary: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Adapt committed glossary entries to the selector's input contract."""
    adapted: List[Dict[str, Any]] = []
    for entry in glossary:
        if not isinstance(entry, dict):
            raise TypeError(f"glossary entry must be a dict, got {type(entry).__name__}")
        tid = _entry_id(entry)
        adapted.append(
            {
                "id": tid,
                "aliases": _entry_aliases(entry, tid),
                "hard_negatives": entry.get("hard_negatives")
                or entry.get("confusable_with")
                or [],
            }
        )
    return adapted


class VocabularyOptimizer:
    """Select a context list for one call from a full glossary."""

    def __init__(
        self,
        glossary: Optional[Sequence[Dict[str, Any]]] = None,
        *,
        call_type: str = "general",
    ) -> None:
        self._raw_glossary = list(glossary) if glossary else []
        self._selector_glossary = (
            to_selector_glossary(self._raw_glossary) if self._raw_glossary else []
        )
        self.call_type = call_type

    # -- public API ------------------------------------------------------
    def optimize_context(
        self,
        hypothesis: str,
        *,
        glossary: Optional[Sequence[Dict[str, Any]]] = None,
        call_type: Optional[str] = None,
        max_terms: int = 200,
        priors: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return ``{"selected", "left_out", ...}`` for one hypothesis.

        ``hypothesis`` is the pass-1 transcript text (or any call-level text)
        used as selection evidence. Selection is the frozen
        ``S = 0.55*Lex + 0.25*Phon + 0.20*Prior`` rule, so the result is
        directly comparable to the ``adaptive-200`` arm.
        """
        if hypothesis is None:
            raise TypeError("hypothesis must be a string")

        entries = self._prepare(glossary)
        if not entries:
            raise ValueError("glossary is empty; nothing to select from")
        if max_terms <= 0:
            raise ValueError("max_terms must be positive")

        active_call_type = call_type or self.call_type
        ids = select(
            hypothesis,
            entries,
            active_call_type,
            budget=max_terms,
            priors=priors,
        )
        breakdown = score_breakdown(hypothesis, entries, active_call_type, priors=priors)

        aliases = {e["id"]: e["aliases"] for e in entries}
        selected: List[Dict[str, str]] = []
        for tid in ids:
            comp = breakdown.get(tid, {})
            source = "phon" if comp.get("phon", 0.0) > comp.get("lex", 0.0) else "lex"
            selected.append(
                {
                    "term": aliases[tid][0] if aliases.get(tid) else tid,
                    "term_id": tid,
                    "source": source,
                    "score": round(float(comp.get("S", 0.0)), 6),
                }
            )

        chosen = set(ids)
        left_out = [e["aliases"][0] for e in entries if e["id"] not in chosen]
        scores = [float(breakdown.get(tid, {}).get("S", 0.0)) for tid in ids]

        result = OptimizationResult(
            selected=selected,
            left_out=left_out,
            budget=max_terms,
            mean_score=(sum(scores) / len(scores)) if scores else 0.0,
            call_type=active_call_type,
            metrics={
                "glossary_size": float(len(entries)),
                "budget": float(max_terms),
                "coverage": float(len(selected)),
                "budget_utilization": (len(selected) / max_terms) if max_terms else 0.0,
            },
        )
        return result.as_dict()

    def optimize_for_call(
        self,
        call_context: Dict[str, Any],
        current_list: Optional[List[str]] = None,
        budget: int = 200,
        pass1_hypotheses: Optional[Sequence[str]] = None,
    ) -> OptimizationResult:
        """Compatibility wrapper around :meth:`optimize_context`."""
        text = " ".join(pass1_hypotheses or []) or str(call_context.get("topic", ""))
        payload = self.optimize_context(
            text,
            call_type=call_context.get("call_type"),
            max_terms=budget,
        )
        return OptimizationResult(
            selected=payload["selected"],
            left_out=payload["left_out"],
            budget=payload["budget"],
            mean_score=payload["mean_score"],
            call_type=payload["call_type"],
            metrics=payload["metrics"],
        )

    # -- internals -------------------------------------------------------
    def _prepare(
        self, glossary: Optional[Sequence[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        if glossary is None:
            return self._selector_glossary
        raw = list(glossary)
        if raw and isinstance(raw[0], dict) and "id" in raw[0] and "aliases" in raw[0]:
            return raw  # already in selector form
        return to_selector_glossary(raw)
