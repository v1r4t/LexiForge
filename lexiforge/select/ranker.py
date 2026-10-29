"""Adaptive context selector (docs/design.md §5).

``select(hypothesis, glossary, call_type, budget=200, *, priors=None)``.

Score: ``S = 0.55*Lex + 0.25*Phon + 0.20*Prior``.

- Lex: max over aliases of
  ``0.7 * char-trigram cosine + 0.3 * normalised BM25-style overlap``,
  plus 0.35 if a canonicalised alias is a substring of the canonicalised
  hypothesis (capped at 1.0).
- Phon: max over aliases and 1-3 token windows of ``skeleton_similarity``,
  vetoed to 0 for declared hard-negative pairs.
- Prior: Laplace-smoothed call_type prior, normalised per call
  (``(c+1) / (total+V)``, sums to 1 per call).

Selection: keep ``S >= tau`` (0.18), MMR with lambda 0.45, skip candidates
with redundancy > 0.85, cap at ``budget``. Returns the NATURAL set with no
padding — the caller pads to the 200-slot budget (design §2 adaptive-200).

Leakage guard: TypeError if any input dict contains a "reference" key.
"""

from __future__ import annotations

import math
import re
from collections import Counter

try:
    from lexiforge.canon import canon
except ImportError:  # pragma: no cover - repo always provides lexiforge.canon
    import unicodedata as _unicodedata

    def canon(text: str) -> str:  # type: ignore[misc]
        if text is None:
            raise TypeError("canon() received None")
        return " ".join(_unicodedata.normalize("NFC", text).casefold().split())


try:
    from lexiforge.select.phonetic import (  # type: ignore[import]
        is_hard_negative_pair as _ext_is_hard_negative_pair,
        skeleton as _ext_skeleton,
        skeleton_similarity as _ext_skeleton_similarity,
    )
except ImportError:
    _ext_skeleton = _ext_skeleton_similarity = _ext_is_hard_negative_pair = None


# --------------------------------------------------------------------------
# Weights and selection policy (frozen per design §5).
# --------------------------------------------------------------------------

W_LEX = 0.55
W_PHON = 0.25
W_PRIOR = 0.20

TRIGRAM_W = 0.7
BM25_W = 0.3
SUBSTRING_BONUS = 0.35

TAU = 0.18
MMR_LAMBDA = 0.45
REDUNDANCY_SKIP = 0.85

# Lexical evidence floor for anchoring a hard-negative veto: the *stronger*
# member of a declared pair must reach this before the weaker member's
# phonetic component is vetoed.
ANCHOR_LEX = 0.4


# --------------------------------------------------------------------------
# Hinglish consonant skeleton fallback (design §5: aspiration collapse,
# retroflex merge, schwa deletion, acronym letter-joining). Used only when
# lexiforge.select.phonetic is unavailable.
# --------------------------------------------------------------------------

_DIGRAPHS = (
    ("ch", "c"),
    ("sh", "s"),
    ("th", "t"),
    ("dh", "d"),
    ("kh", "k"),
    ("gh", "g"),
    ("ph", "p"),
    ("bh", "b"),
    ("jh", "j"),
    ("zh", "z"),
)
_RETROFLEX = str.maketrans(
    {"ṭ": "t", "ḍ": "d", "ṇ": "n", "ṣ": "s", "ś": "s", "ṛ": "r", "ṅ": "n", "ñ": "n"}
)
_VOWELS = frozenset("aeiou")


def _join_single_letters(text: str) -> str:
    toks = text.split()
    out: list[str] = []
    i = 0
    while i < len(toks):
        if len(toks[i]) == 1 and toks[i].isalpha():
            j = i
            while j < len(toks) and len(toks[j]) == 1 and toks[j].isalpha():
                j += 1
            out.append("".join(toks[i:j]))
            i = j
        else:
            out.append(toks[i])
            i += 1
    return " ".join(out)


def _skeleton(text: str) -> str:
    s = text.lower().translate(_RETROFLEX)
    s = _join_single_letters(s)
    for src, dst in _DIGRAPHS:
        s = s.replace(src, dst)
    toks = []
    for tok in s.split():
        if not tok:
            continue
        # Schwa deletion: drop vowels past the first character of each token.
        toks.append(tok[0] + "".join(ch for ch in tok[1:] if ch not in _VOWELS))
    return " ".join(toks)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[len(b)]


def _skeleton_similarity(a: str, b: str) -> float:
    sa, sb = _skeleton(a), _skeleton(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return 1.0 - _levenshtein(sa, sb) / max(len(sa), len(sb))


def skeleton(text: str) -> str:
    """Consonant skeleton; prefers lexiforge.select.phonetic when present."""
    if _ext_skeleton is not None:
        return _ext_skeleton(text)
    return _skeleton(text)


def skeleton_similarity(a: str, b: str) -> float:
    """Skeleton similarity in [0, 1]; prefers lexiforge.select.phonetic."""
    if _ext_skeleton_similarity is not None:
        return float(_ext_skeleton_similarity(a, b))
    return _skeleton_similarity(a, b)


# Registry backing the two-argument is_hard_negative_pair contract; refreshed
# on every select()/score_breakdown() call from the glossary declarations.
_DECLARED: set[frozenset] = set()


def is_hard_negative_pair(a: str, b: str, declared=None) -> bool:
    """True if ``a``/``b`` are a declared hard-negative pair."""
    if a == b:
        return False
    pool = _DECLARED if declared is None else declared
    try:
        if frozenset((a, b)) in pool:
            return True
    except TypeError:
        pass
    if _ext_is_hard_negative_pair is not None:
        try:
            return bool(_ext_is_hard_negative_pair(a, b))
        except Exception:
            return False
    return False


# --------------------------------------------------------------------------
# Input handling and leakage guard.
# --------------------------------------------------------------------------

_ID_KEYS = ("id", "term", "name", "key")
_ALIAS_KEYS = ("aliases", "alias", "variants", "surfaces")
_PAIR_KEYS = ("hard_negatives", "hard_negative_with", "hard_negative_ids", "confusable_with")
_COUNT_KEYS = ("priors", "prior", "counts", "count")
_TEXT_KEYS = ("text", "hypothesis", "transcript", "utt")


def _assert_no_reference(obj) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "reference":
                raise TypeError("leakage guard: input dict contains a 'reference' key")
            _assert_no_reference(v)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for v in obj:
            _assert_no_reference(v)


def _hypothesis_text(hypothesis) -> str:
    if isinstance(hypothesis, str):
        return hypothesis
    if isinstance(hypothesis, dict):
        for k in _TEXT_KEYS:
            if isinstance(hypothesis.get(k), str):
                return hypothesis[k]
        raise ValueError("hypothesis dict has no text under keys %s" % (_TEXT_KEYS,))
    raise TypeError("hypothesis must be str or dict, got %s" % type(hypothesis).__name__)


def _entry_id(entry: dict, idx: int) -> str:
    for k in _ID_KEYS:
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return v
    raise ValueError("glossary entry %d has no id/term/name key" % idx)


def _entry_aliases(entry: dict, tid: str) -> list[str]:
    aliases: list[str] = []
    for k in _ALIAS_KEYS:
        v = entry.get(k)
        if isinstance(v, str):
            aliases.append(v)
        elif isinstance(v, (list, tuple)):
            aliases.extend(x for x in v if isinstance(x, str))
    aliases.append(tid)
    seen: set[str] = set()
    out: list[str] = []
    for a in aliases:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _entry_pairs(entry: dict) -> list[str]:
    out: list[str] = []
    for k in _PAIR_KEYS:
        v = entry.get(k)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, (list, tuple, set, frozenset)):
            out.extend(x for x in v if isinstance(x, str))
    return out


def _entry_count(entry: dict, call_type) -> float:
    for k in _COUNT_KEYS:
        v = entry.get(k)
        if isinstance(v, dict) and isinstance(call_type, str):
            v = v.get(call_type, 0)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def _normalise_glossary(glossary) -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
    """Merge duplicate ids; returns (ordered ids, aliases, declared pairs)."""
    if glossary is None:
        return [], {}, {}
    if not isinstance(glossary, (list, tuple)):
        raise TypeError("glossary must be a list of dicts")
    order: list[str] = []
    aliases: dict[str, list[str]] = {}
    pairs: dict[str, list[str]] = {}
    for idx, entry in enumerate(glossary):
        if not isinstance(entry, dict):
            raise TypeError("glossary entry %d must be a dict" % idx)
        tid = _entry_id(entry, idx)
        if tid not in aliases:
            order.append(tid)
            aliases[tid] = []
            pairs[tid] = []
        for a in _entry_aliases(entry, tid):
            if a not in aliases[tid]:
                aliases[tid].append(a)
        for p in _entry_pairs(entry):
            if p not in pairs[tid]:
                pairs[tid].append(p)
    return order, aliases, pairs


def _prior_counts(order, glossary_entries, priors, call_type) -> dict[str, float]:
    counts: dict[str, float] = {}
    per_call = None
    if (
        isinstance(priors, dict)
        and isinstance(call_type, str)
        and isinstance(priors.get(call_type), dict)
    ):
        per_call = priors[call_type]
    by_id = {tid: e for tid, e in zip(order, glossary_entries)}
    for tid in order:
        c = 0.0
        if per_call is not None:
            v = per_call.get(tid, 0)
            if isinstance(v, bool):
                v = 0
            try:
                c = float(v)
            except (TypeError, ValueError):
                c = 0.0
        elif isinstance(priors, dict) and tid in priors:
            v = priors[tid]
            if isinstance(v, dict) and isinstance(call_type, str):
                v = v.get(call_type, 0)
            if isinstance(v, bool):
                v = 0
            try:
                c = float(v)
            except (TypeError, ValueError):
                c = 0.0
        else:
            entry = by_id.get(tid)
            if isinstance(entry, dict):
                try:
                    c = float(_entry_count(entry, call_type))
                except (TypeError, ValueError):
                    c = 0.0
        if not math.isfinite(c) or c < 0:
            c = 0.0
        counts[tid] = c
    return counts


# --------------------------------------------------------------------------
# Lexical component.
# --------------------------------------------------------------------------

def _trigrams(s: str) -> Counter:
    padded = "  " + s + "  "
    return Counter(padded[i : i + 3] for i in range(len(padded) - 2))


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b.get(t, 0) for t in a)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _lexical(alias_canon: str, hyp_canon: str, hyp_toks: set[str], idf: dict[str, float]) -> float:
    if not alias_canon or not hyp_canon:
        return 0.0
    cos = _cosine(_trigrams(alias_canon), _trigrams(hyp_canon))
    alias_toks = alias_canon.split()
    if not alias_toks:
        return 0.0
    denom = sum(idf.get(t, 0.0) for t in alias_toks)
    if denom <= 0.0:
        bm25 = 1.0 if set(alias_toks) <= hyp_toks else 0.0
    else:
        bm25 = sum(idf.get(t, 0.0) for t in alias_toks if t in hyp_toks) / denom
    return TRIGRAM_W * cos + BM25_W * bm25


def _build_idf(canon_alias_docs: list[list[str]]) -> tuple[dict[str, float], int]:
    n = len(canon_alias_docs)
    df: Counter = Counter()
    for toks in canon_alias_docs:
        for t in set(toks):
            df[t] += 1
    idf = {t: math.log(1.0 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
    return idf, n


def _windows(hyp_toks: list[str]) -> list[str]:
    out: list[str] = []
    for size in (1, 2, 3):
        for i in range(len(hyp_toks) - size + 1):
            out.append(" ".join(hyp_toks[i : i + size]))
    return out


# --------------------------------------------------------------------------
# Scoring.
# --------------------------------------------------------------------------

def score_breakdown(hypothesis, glossary, call_type, priors=None) -> dict[str, dict]:
    """Per-term ``{"S", "lex", "phon", "prior"}`` components (pre-threshold)."""
    _assert_no_reference(hypothesis)
    _assert_no_reference(glossary)
    _assert_no_reference(priors)

    text = _hypothesis_text(hypothesis)
    hyp_canon = canon(text)
    if not hyp_canon:
        return {}
    if not isinstance(call_type, str):
        raise TypeError("call_type must be a string")

    entries = list(glossary) if glossary else []
    order, alias_map, pair_map = _normalise_glossary(entries)
    first_entry: dict[str, dict] = {}
    for idx, entry in enumerate(entries):
        tid = _entry_id(entry, idx)
        if tid not in first_entry:
            first_entry[tid] = entry

    canon_alias: dict[str, list[str]] = {}
    docs: list[list[str]] = []
    for tid in order:
        forms = []
        for a in alias_map[tid]:
            c = canon(a)
            if c and c not in forms:
                forms.append(c)
        if not forms:
            forms = [canon(tid)]
        canon_alias[tid] = forms
        for c in forms:
            docs.append(c.split())
    idf, _ = _build_idf(docs)

    hyp_toks = hyp_canon.split()
    hyp_tok_set = set(hyp_toks)
    wins = _windows(hyp_toks)

    counts = _prior_counts(
        order, [first_entry[tid] for tid in order], priors, call_type
    )
    total = sum(counts.values())
    v = len(order)

    # Declared hard-negative pairs (symmetric closure over known ids).
    global _DECLARED
    _DECLARED = set()
    for tid in order:
        for p in pair_map.get(tid, []):
            if p in alias_map and p != tid:
                _DECLARED.add(frozenset((tid, p)))

    lex: dict[str, float] = {}
    substr: dict[str, bool] = {}
    for tid in order:
        best = 0.0
        hit = False
        for c in canon_alias[tid]:
            best = max(best, _lexical(c, hyp_canon, hyp_tok_set, idf))
            if c and c in hyp_canon:
                hit = True
        if hit:
            best = min(1.0, best + SUBSTRING_BONUS)
        lex[tid] = min(1.0, best)
        substr[tid] = hit

    # Veto: the weaker member of a declared pair loses its phonetic component
    # once the stronger member is lexically anchored.
    vetoed: set[str] = set()
    for pair in sorted(_DECLARED, key=lambda p: sorted(p)):
        a, b = sorted(pair)
        la, lb = lex[a], lex[b]
        if la >= ANCHOR_LEX and la >= lb and lb < la:
            vetoed.add(b)
        elif lb >= ANCHOR_LEX and lb > la:
            vetoed.add(a)

    phon: dict[str, float] = {}
    for tid in order:
        if tid in vetoed:
            phon[tid] = 0.0
            continue
        best = 0.0
        for c in canon_alias[tid]:
            if not c:
                continue
            for w in wins:
                s = skeleton_similarity(c, w)
                if s > best:
                    best = s
                    if best >= 1.0:
                        break
            if best >= 1.0:
                break
        phon[tid] = best

    out: dict[str, dict] = {}
    for tid in order:
        prior = (counts[tid] + 1.0) / (total + v) if v else 0.0
        s = W_LEX * lex[tid] + W_PHON * phon[tid] + W_PRIOR * prior
        out[tid] = {"S": s, "lex": lex[tid], "phon": phon[tid], "prior": prior}
    return out


def _redundancy(counters_a: list[Counter], counters_b: list[Counter]) -> float:
    best = 0.0
    for ca in counters_a:
        for cb in counters_b:
            s = _cosine(ca, cb)
            if s > best:
                best = s
    return best


def select(hypothesis, glossary, call_type, budget=200, *, priors=None) -> list[str]:
    """Select glossary term ids for ``hypothesis``; natural set, no padding."""
    _assert_no_reference(hypothesis)
    _assert_no_reference(glossary)
    _assert_no_reference(priors)

    if budget is not None and budget <= 0:
        return []
    cap = 200 if budget is None else int(budget)

    comp = score_breakdown(hypothesis, glossary, call_type, priors=priors)
    if not comp:
        return []

    # Precompute trigram counters for MMR redundancy (max alias-pair cosine).
    order, alias_map, _ = _normalise_glossary(list(glossary) if glossary else [])
    tri: dict[str, list[Counter]] = {}
    for tid in order:
        if tid not in comp:
            continue
        forms = []
        for a in alias_map[tid]:
            c = canon(a)
            if c:
                forms.append(_trigrams(c))
        tri[tid] = forms or [_trigrams(canon(tid))]

    pool = [
        tid for tid, c in sorted(comp.items(), key=lambda kv: (-kv[1]["S"], kv[0])) if c["S"] >= TAU
    ]
    selected: list[str] = []
    while pool and len(selected) < cap:
        best_tid = None
        best_key = None
        for tid in pool:
            red = 0.0
            for done in selected:
                red = max(red, _redundancy(tri[tid], tri[done]))
            if red > REDUNDANCY_SKIP:
                continue
            mmr = MMR_LAMBDA * comp[tid]["S"] - (1.0 - MMR_LAMBDA) * red
            key = (mmr, -comp[tid]["S"], tid)
            # Deterministic max: higher mmr wins; ties break to higher S, then tid.
            if best_key is None or key[0] > best_key[0] or (
                key[0] == best_key[0] and (key[1], key[2]) < (best_key[1], best_key[2])
            ):
                best_key = key
                best_tid = tid
        if best_tid is None:
            break
        # Drop everything at least as redundant as the skip threshold vs the pick.
        selected.append(best_tid)
        pool = [
            tid
            for tid in pool
            if tid != best_tid and _redundancy(tri[tid], tri[best_tid]) <= REDUNDANCY_SKIP
        ]
    return selected
