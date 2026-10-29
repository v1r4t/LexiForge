"""Per-call decoding contexts (design §2, §4).

A context is the ``(topic, keyterms, speaker_names)`` triple attached to one
Batch job. Budgets are enforced client-side before submission:

* ``keyterms``: JSON array, at most 200 items. A multi-word phrase costs ONE
  slot. Duplicates are dropped (server-side too) so the cap is checked after
  dedupe. Values containing ``<|`` or ``|>`` are rejected.
* ``topic``: 30–1600 chars on Batch, held constant per call across conditions,
  derived from call metadata only (never from transcripts/references).
* Accepted combinations only: none | keyterms | topic | topic+keyterms |
  speaker_names. ``topic``-only and ``speaker_names``-only arms are cut from
  the design (no power, no budget) but ``speaker_names`` alone remains the
  only legal use of that field.
"""

from lexiforge.contexts.build import (
    MAX_KEYTERMS,
    TOPIC_MAX,
    TOPIC_MIN,
    ContextBudgetError,
    assert_budget,
    build_config,
    canonicalise_terms,
    context_hash,
    derive_topic,
)

__all__ = [
    "MAX_KEYTERMS",
    "TOPIC_MAX",
    "TOPIC_MIN",
    "ContextBudgetError",
    "assert_budget",
    "build_config",
    "canonicalise_terms",
    "context_hash",
    "derive_topic",
]
