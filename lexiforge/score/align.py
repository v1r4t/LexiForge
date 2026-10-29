"""Token alignment and glossary-span pairing.

Implements docs/design.md §5, "Insertion, defined before the pilot":

* token-align reference to hypothesis;
* a hypothesis span over a glossary term is a hit when it aligns to the SAME
  reference term, and an insertion when it aligns to a DIFFERENT reference
  term or to nothing (an extra hypothesis token);
* a hypothesis span whose tokens ALL match reference tokens exactly is a
  correct transcription -- when no same-term reference span sits there (e.g. a
  matcher false alarm on an ordinary word that merely sounds like a glossary
  term) it is ignored, never scored as an insertion.

Stdlib only.
"""

__all__ = ["align", "pair_terms"]

_MATCH, _SUB, _DEL, _INS = "match", "sub", "del", "ins"


def align(reference_tokens, hypothesis_tokens):
    """Align two token sequences with Levenshtein DP.

    Returns a list of ``(ref_index, hyp_index, op)`` opcodes with ``op`` in
    ``match``/``sub``/``del``/``ins``. ``match``/``sub`` carry both indices,
    ``del`` carries ``(ref_index, None)`` and ``ins`` carries
    ``(None, hyp_index)``. Every reference index appears exactly once (via
    match/sub/del) and every hypothesis index exactly once (via match/sub/ins).

    Ties resolve deterministically in the order: match, then sub, then del,
    then ins (diagonal moves preferred, evaluated from the end of the
    sequences backwards).
    """
    ref = list(reference_tokens)
    hyp = list(hypothesis_tokens)
    n, m = len(ref), len(hyp)
    dist = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dist[i][0] = i
    for j in range(1, m + 1):
        dist[0][j] = j
    for i in range(1, n + 1):
        token = ref[i - 1]
        for j in range(1, m + 1):
            if token == hyp[j - 1]:
                dist[i][j] = dist[i - 1][j - 1]
            else:
                dist[i][j] = min(
                    dist[i - 1][j - 1] + 1, dist[i - 1][j] + 1, dist[i][j - 1] + 1
                )
    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        if (
            i > 0
            and j > 0
            and ref[i - 1] == hyp[j - 1]
            and dist[i][j] == dist[i - 1][j - 1]
        ):
            ops.append((i - 1, j - 1, _MATCH))
            i -= 1
            j -= 1
        elif (
            i > 0
            and j > 0
            and ref[i - 1] != hyp[j - 1]
            and dist[i][j] == dist[i - 1][j - 1] + 1
        ):
            ops.append((i - 1, j - 1, _SUB))
            i -= 1
            j -= 1
        elif i > 0 and dist[i][j] == dist[i - 1][j] + 1:
            ops.append((i - 1, None, _DEL))
            i -= 1
        elif j > 0 and dist[i][j] == dist[i][j - 1] + 1:
            ops.append((None, j - 1, _INS))
            j -= 1
        else:  # Unreachable for a correctly filled DP table.
            raise AssertionError("alignment backtrack reached a dead end")
    ops.reverse()
    return ops


def _norm_span(span):
    """Normalise a span to an ``(start, end, term_id)`` triple.

    Accepts ``{"start": int, "end": int, "term_id": str}`` dicts or
    ``(start, end, term_id)`` tuples/lists. ``start`` is inclusive and ``end``
    exclusive over token indices.
    """
    if isinstance(span, dict):
        return (int(span["start"]), int(span["end"]), span["term_id"])
    start, end, term_id = span
    return (int(start), int(end), term_id)


def _span_dict(triple):
    start, end, term_id = triple
    return {"start": start, "end": end, "term_id": term_id}


def _sort_key(triple):
    return (triple[0], triple[1], str(triple[2]))


def pair_terms(reference_spans, hypothesis_spans, alignment):
    """Pair hypothesis term spans against reference term spans.

    Returns ``{"hits": [...], "insertions": [...], "misses": [...]}`` where
    ``hits``/``insertions`` hold hypothesis spans and ``misses`` holds
    reference spans, each as ``{"start", "end", "term_id"}`` dicts sorted by
    ``(start, end, term_id)``. Rules:

    * hit: the hypothesis span shares at least one diagonal (match/sub)
      token link with a reference span carrying the SAME ``term_id``;
    * insertion: not a hit, and at least one span token is substituted,
      inserted, or absent from the alignment (i.e. aligns to a different
      term token or to nothing);
    * otherwise the span is ignored: every token matches reference text
      exactly but no same-term reference span sits there, i.e. a correct
      transcription of an ordinary word that merely sounds like a glossary
      term -- never an insertion;
    * misses: reference spans linked to no hitting hypothesis span.

    Each input span is counted at most once (exact duplicates are merged),
    and overlapping spans resolve deterministically: a reference token may
    carry several overlapping reference spans, and sharing any one of them
    with the same ``term_id`` is a hit regardless of input order.
    """
    ref_list = sorted(
        {_norm_span(s) for s in (reference_spans or [])}, key=_sort_key
    )
    hyp_list = sorted(
        {_norm_span(s) for s in (hypothesis_spans or [])}, key=_sort_key
    )

    cover = {}
    for start, end, term_id in ref_list:
        for idx in range(start, end):
            cover.setdefault(idx, set()).add(term_id)

    hyp_map = {}
    for ref_idx, hyp_idx, op in alignment:
        if hyp_idx is not None and hyp_idx not in hyp_map:
            hyp_map[hyp_idx] = (ref_idx, op)

    hits, insertions = [], []
    linked_refs = set()
    for hs, he, ht in hyp_list:
        links = [hyp_map.get(i, (None, _INS)) for i in range(hs, he)]
        diagonal = [r for (r, op) in links if r is not None and op in (_MATCH, _SUB)]
        same = [r for r in diagonal if ht in cover.get(r, set())]
        if same:
            hits.append(_span_dict((hs, he, ht)))
            for r in same:
                for triple in ref_list:
                    rs, re, rt = triple
                    if rt == ht and rs <= r < re:
                        linked_refs.add(triple)
        elif any(op != _MATCH for (_, op) in links):
            insertions.append(_span_dict((hs, he, ht)))
        # else: correct transcription of non-term text; ignored by design.

    misses = [_span_dict(t) for t in ref_list if t not in linked_refs]
    return {"hits": hits, "insertions": insertions, "misses": misses}
