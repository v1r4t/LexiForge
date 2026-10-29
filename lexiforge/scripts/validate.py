"""Mechanical validation for synthetic call scripts (design §4 step 3)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from lexiforge.canon import canon

EXPECTED_ORDER = ["AGT", "CUS", "AGT", "CUS", "AGT"]

WORDS_PER_SECOND = 2.2
SECONDS_OFFSET = 1.5
MAX_SECONDS = 30.0
WORD_LIMIT = 45

REAL_MIN, REAL_MAX = 4, 5
FICT_MIN, FICT_MAX = 3, 4

MAX_TERMS_PER_TURN = 2
GLOSS_MARKERS = ("means", "full form")

REQUIRED_METADATA = ("call_id", "call_type", "channel", "language")

CORPUS_SIZE = 20
HARD_NEG_TARGET = 10
OOV_TARGET = 6

# Real bank / brand names that must never surface (design §3, notes §1).
# Matching is token-span based (word boundaries), not raw substring, so short
# entries such as "Fi" cannot fire on ordinary words like "five".
BLOCKLIST = (
    "PhonePe", "Paytm", "GPay", "Google Pay", "BHIM", "Amazon Pay",
    "Razorpay", "Cashfree", "BillDesk", "CCAvenue", "MobiKwik",
    "Freecharge", "ZestMoney", "KredX", "Jupiter", "Fi", "Slice",
    "Niyo", "Open", "IndiaMART Pay",
    "SBI", "State Bank of India", "HDFC", "HDFC Bank", "ICICI",
    "ICICI Bank", "Axis Bank", "Kotak", "Kotak Mahindra",
    "Punjab National Bank", "PNB", "Bank of Baroda", "Canara Bank",
    "Union Bank", "IDBI", "Yes Bank", "IndusInd", "Bandhan Bank",
    "Federal Bank", "RBL", "Citibank", "HSBC", "Standard Chartered", "DBS",
)

RESERVED_FILES = frozenset({
    "assignment.json", "assignments.json", "glossary.json",
    "real_lexicon.json", "real-lexicon.json",
    "mismatched.json", "mismatch.json",
})


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _canon_str(term: Any) -> str:
    return canon(str(term))


def _coerce_terms(obj: Any) -> list[str]:
    """Coerce glossary/lexicon/mismatched inputs to a list of strings."""
    if obj is None:
        return []
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, Mapping):
        for key in ("terms", "glossary", "ids", "keyterms", "expected"):
            val = obj.get(key)
            if isinstance(val, (list, tuple, set)):
                return [str(t) for t in val if isinstance(t, (str, int, float))]
        return [str(k) for k in obj.keys()]
    if isinstance(obj, (list, tuple, set)):
        return [str(t) for t in obj if isinstance(t, (str, int, float))]
    return []


def _canon_set(terms: Iterable[Any]) -> set[str]:
    out: set[str] = set()
    for t in _coerce_terms(terms):
        c = _canon_str(t)
        if c:
            out.add(c)
    return out


def _canon_tokens(text: str) -> list[str]:
    return canon(text).split()


def _span_count(hay: Sequence[str], needle: Sequence[str]) -> int:
    """Count non-overlapping contiguous token-span occurrences."""
    if not needle or len(needle) > len(hay):
        return 0
    n = len(needle)
    count, i = 0, 0
    while i <= len(hay) - n:
        if list(hay[i:i + n]) == list(needle):
            count += 1
            i += n
        else:
            i += 1
    return count


def _span_present(hay: Sequence[str], needle: Sequence[str]) -> bool:
    return _span_count(hay, needle) > 0


def _terms_in_text(text: str, glossary_canons: set[str]) -> dict[str, int]:
    """Map glossary canon -> span-occurrence count within one turn."""
    toks = _canon_tokens(text)
    found: dict[str, int] = {}
    for c in glossary_canons:
        k = _span_count(toks, c.split())
        if k:
            found[c] = k
    return found


def estimate_seconds(text: str) -> float:
    """Estimated turn duration: words/2.2 + 1.5s."""
    return len(str(text).split()) / WORDS_PER_SECOND + SECONDS_OFFSET


def _call_id(call: Mapping) -> str:
    for key in ("call_id", "id", "name"):
        val = call.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "<unknown>"


def _turn_speaker(turn: Any) -> str:
    if isinstance(turn, Mapping):
        for key in ("speaker", "role", "who"):
            val = turn.get(key)
            if isinstance(val, str):
                return val.strip().upper()
    return ""


def _turn_text(turn: Any) -> Any:
    if isinstance(turn, Mapping):
        for key in ("text", "utterance", "line", "content"):
            if key in turn:
                return turn[key]
    return ""


def _expected_lists(assignment: Any, call: Any) -> tuple[list[str], list[str]]:
    """Return (real terms, fictional terms) from assignment, else call."""
    real: list[str] = []
    fict: list[str] = []
    for src in (assignment, call):
        if isinstance(src, Mapping):
            r = src.get("expected_real_terms", src.get("real_terms", src.get("real")))
            f = src.get(
                "expected_fictional_terms",
                src.get("fictional_terms", src.get("fictional")),
            )
            if r and not real:
                real = _coerce_terms(r)
            if f and not fict:
                fict = _coerce_terms(f)
    return real, fict


def _hard_negative(assignment: Any, call: Any) -> tuple[bool, list[str]]:
    pair: list[str] = []
    assigned: bool | None = None
    for src in (assignment, call):
        if isinstance(src, Mapping):
            p = src.get("hard_negative_pair", src.get("hard_negative"))
            if p and not pair:
                pair = _coerce_terms(p)
            flag = src.get("hard_negative_assigned", src.get("hard_negative_present"))
            if isinstance(flag, bool) and assigned is None:
                assigned = flag
    if assigned is None:
        assigned = bool(pair)
    return assigned, pair


def _oov(assignment: Any, call: Any) -> tuple[bool, list[str]]:
    terms: list[str] = []
    assigned: bool | None = None
    for src in (assignment, call):
        if isinstance(src, Mapping):
            o = src.get("oov_terms", src.get("oov"))
            if o and not terms:
                terms = _coerce_terms(o)
            flag = src.get("oov_assigned", src.get("oov_present"))
            if isinstance(flag, bool) and assigned is None:
                assigned = flag
    if assigned is None:
        assigned = bool(terms)
    return assigned, terms


def _mismatched_for_call(
    mismatched_terms: Any, assignment: Any, call: Any
) -> list[str] | None:
    """Per-call mismatched context; None when no data is available."""
    if mismatched_terms is not None:
        coerced = _coerce_terms(mismatched_terms)
        # An explicitly passed empty mapping/list means "no data", not "empty".
        if coerced or isinstance(mismatched_terms, (list, tuple, set)):
            return coerced
    for src in (assignment, call):
        if isinstance(src, Mapping):
            for key in ("mismatched_terms", "mismatched", "mismatched_context"):
                if src.get(key):
                    return _coerce_terms(src[key])
    return None


# ---------------------------------------------------------------------------
# Per-call validation
# ---------------------------------------------------------------------------

def validate_script(
    call: Mapping,
    assignment: Mapping | None,
    glossary_ids: Iterable[str] | Mapping,
    mismatched_terms: Iterable[str] | Mapping | None,
) -> list[str]:
    """Validate one call's script against the ten mechanical checks.

    Returns a list of violation strings, each prefixed with its stable code
    (``S1``..``S10``). An empty list means the call passes.
    """
    violations: list[str] = []
    assignment = assignment if isinstance(assignment, Mapping) else {}
    call = call if isinstance(call, Mapping) else {}
    cid = _call_id(call) if call else _call_id(assignment)
    glossary = _canon_set(glossary_ids if glossary_ids is not None else [])

    turns = call.get("turns") if isinstance(call, Mapping) else None
    turn_list = list(turns) if isinstance(turns, (list, tuple)) else None

    # S1: exactly 5 turns, 2 speakers, strict AGT/CUS/AGT/CUS/AGT order.
    if turn_list is None or len(turn_list) != 5:
        got = "missing" if turn_list is None else str(len(turn_list))
        violations.append(f"S1 {cid}: expected exactly 5 turns, got {got}")
        turn_list = turn_list if turn_list is not None else []
    else:
        speakers = [_turn_speaker(t) for t in turn_list]
        if set(speakers) != {"AGT", "CUS"}:
            violations.append(
                f"S1 {cid}: expected exactly 2 speakers {{AGT, CUS}}, "
                f"got {sorted(set(speakers))}"
            )
        if speakers != EXPECTED_ORDER:
            violations.append(
                f"S1 {cid}: speaker order must be "
                f"{'/'.join(EXPECTED_ORDER)}, got {'/'.join(speakers)}"
            )

    texts: list[str] = []
    for t in turn_list:
        txt = _turn_text(t)
        texts.append(txt if isinstance(txt, str) else "")

    # S2: every turn estimated <30s (words/2.2 + 1.5s); reject >45 words.
    for i, txt in enumerate(texts):
        if not isinstance(txt, str) or not txt.strip():
            continue
        nwords = len(txt.split())
        est = estimate_seconds(txt)
        if nwords > WORD_LIMIT:
            violations.append(
                f"S2 {cid}: turn {i + 1} has {nwords} words "
                f"(>{WORD_LIMIT} word cap, ~{est:.1f}s)"
            )
        elif est >= MAX_SECONDS:
            violations.append(
                f"S2 {cid}: turn {i + 1} estimated {est:.1f}s "
                f"(>={MAX_SECONDS:.0f}s cap)"
            )

    # S3: 4-5 real-term and 3-4 fictional-term occurrences per call.
    real_terms, fict_terms = _expected_lists(assignment, call)
    if not real_terms or not fict_terms:
        violations.append(
            f"S10 {cid}: assignment incomplete, missing "
            f"expected_real_terms/expected_fictional_terms"
        )
    else:
        real_canons = [_canon_str(t) for t in real_terms]
        fict_canons = [_canon_str(t) for t in fict_terms]
        if set(real_canons) & set(fict_canons):
            violations.append(
                f"S3 {cid}: term listed as both real and fictional: "
                f"{sorted(set(real_canons) & set(fict_canons))}"
            )
        canon_texts = [_canon_tokens(t) for t in texts]
        real_occ = sum(
            _span_count(toks, rc.split())
            for toks in canon_texts
            for rc in real_canons
        )
        fict_occ = sum(
            _span_count(toks, fc.split())
            for toks in canon_texts
            for fc in fict_canons
        )
        if not (REAL_MIN <= real_occ <= REAL_MAX):
            violations.append(
                f"S3 {cid}: {real_occ} real-term occurrences "
                f"(need {REAL_MIN}-{REAL_MAX})"
            )
        if not (FICT_MIN <= fict_occ <= FICT_MAX):
            violations.append(
                f"S3 {cid}: {fict_occ} fictional-term occurrences "
                f"(need {FICT_MIN}-{FICT_MAX})"
            )

    # S4: turn 1 contains zero glossary terms.
    if texts and isinstance(texts[0], str) and texts[0].strip() and glossary:
        found_t1 = _terms_in_text(texts[0], glossary)
        if found_t1:
            violations.append(
                f"S4 {cid}: turn 1 must contain zero glossary terms, "
                f"found {sorted(found_t1)}"
            )

    # S5: zero overlap between mismatched context and expected terms.
    mism = _mismatched_for_call(mismatched_terms, assignment, call)
    if mism is not None and real_terms and fict_terms:
        expected = {_canon_str(t) for t in real_terms + fict_terms if _canon_str(t)}
        overlap = sorted(_canon_set(mism) & expected)
        if overlap:
            violations.append(
                f"S5 {cid}: mismatched context overlaps expected "
                f"real/fictional terms: {overlap}"
            )

    # S6: hard-negative pair present iff assigned.
    hn_assigned, hn_pair = _hard_negative(assignment, call)
    if hn_assigned:
        if len(hn_pair) != 2 or any(not _canon_str(p) for p in hn_pair):
            violations.append(
                f"S6 {cid}: hard-negative assigned but pair is not "
                f"exactly 2 terms: {hn_pair}"
            )
        elif texts:
            canon_texts = [_canon_tokens(t) for t in texts]
            missing = [
                p for p in hn_pair
                if not any(
                    _span_present(toks, _canon_str(p).split())
                    for toks in canon_texts
                )
            ]
            if missing:
                violations.append(
                    f"S6 {cid}: assigned hard-negative pair {hn_pair} "
                    f"not fully surfaced, missing {missing}"
                )
    elif len(hn_pair) == 2 and texts:
        canon_texts = [_canon_tokens(t) for t in texts]
        if all(
            any(_span_present(toks, _canon_str(p).split()) for toks in canon_texts)
            for p in hn_pair
        ):
            violations.append(
                f"S6 {cid}: unassigned hard-negative pair {hn_pair} "
                f"surfaces in full"
            )

    # S7: OOV surfaces iff designated, and is absent from the glossary.
    oov_assigned, oov_terms = _oov(assignment, call)
    if oov_terms and glossary:
        in_gloss = sorted(_canon_set(oov_terms) & glossary)
        if in_gloss:
            violations.append(
                f"S7 {cid}: OOV terms must be absent from the glossary, "
                f"found {in_gloss}"
            )
    if oov_assigned:
        if not oov_terms:
            violations.append(
                f"S7 {cid}: OOV designated but no oov_terms listed"
            )
        elif texts:
            canon_texts = [_canon_tokens(t) for t in texts]
            surfaced = [
                o for o in oov_terms
                if any(
                    _span_present(toks, _canon_str(o).split())
                    for toks in canon_texts
                )
            ]
            if not surfaced:
                violations.append(
                    f"S7 {cid}: designated OOV {oov_terms} never surfaces"
                )
    elif oov_terms and texts:
        canon_texts = [_canon_tokens(t) for t in texts]
        stray = [
            o for o in oov_terms
            if any(
                _span_present(toks, _canon_str(o).split())
                for toks in canon_texts
            )
        ]
        if stray:
            violations.append(
                f"S7 {cid}: undesigned OOV surfaces: {stray}"
            )

    # S8: no real bank or brand name (blocklist).
    if texts:
        canon_texts = [_canon_tokens(t) for t in texts]
        for i, toks in enumerate(canon_texts):
            for brand in BLOCKLIST:
                if _span_present(toks, _canon_str(brand).split()):
                    violations.append(
                        f"S8 {cid}: turn {i + 1} contains blocklisted "
                        f"bank/brand name {brand!r}"
                    )

    # S9: <=2 glossary terms per turn, no in-turn repeat, no glossing.
    if glossary:
        for i, txt in enumerate(texts):
            if not isinstance(txt, str) or not txt.strip():
                continue
            found = _terms_in_text(txt, glossary)
            if len(found) > MAX_TERMS_PER_TURN:
                violations.append(
                    f"S9 {cid}: turn {i + 1} has {len(found)} glossary "
                    f"terms (>{MAX_TERMS_PER_TURN}): {sorted(found)}"
                )
            repeated = sorted(c for c, k in found.items() if k > 1)
            if repeated:
                violations.append(
                    f"S9 {cid}: turn {i + 1} repeats term(s): {repeated}"
                )
    for i, txt in enumerate(texts):
        if not isinstance(txt, str):
            continue
        toks = _canon_tokens(txt)
        for marker in GLOSS_MARKERS:
            if _span_present(toks, marker.split()):
                violations.append(
                    f"S9 {cid}: turn {i + 1} contains appositive "
                    f"glossing ({marker!r})"
                )

    # S10: metadata complete and consistent.
    metadata = call.get("metadata") if isinstance(call, Mapping) else None
    if not isinstance(metadata, Mapping):
        violations.append(f"S10 {cid}: missing metadata mapping")
    else:
        for key in REQUIRED_METADATA:
            val = metadata.get(key)
            if not isinstance(val, str) or not val.strip():
                violations.append(
                    f"S10 {cid}: metadata missing required key {key!r}"
                )
        if (
            isinstance(metadata.get("call_id"), str)
            and metadata["call_id"].strip()
            and metadata["call_id"].strip() != cid
            and cid != "<unknown>"
        ):
            violations.append(
                f"S10 {cid}: metadata call_id "
                f"{metadata['call_id'].strip()!r} != call call_id {cid!r}"
            )
        if isinstance(assignment, Mapping) and isinstance(
            assignment.get("call_id"), str
        ):
            if assignment["call_id"].strip() and assignment["call_id"].strip() != cid \
                    and cid != "<unknown>":
                violations.append(
                    f"S10 {cid}: assignment call_id "
                    f"{assignment['call_id'].strip()!r} != call call_id {cid!r}"
                )
        speakers_meta = metadata.get("speakers")
        if isinstance(speakers_meta, (list, tuple)) and turn_list:
            actual = sorted({_turn_speaker(t) for t in turn_list})
            if sorted(s.upper() for s in speakers_meta if isinstance(s, str)) != actual:
                violations.append(
                    f"S10 {cid}: metadata speakers {list(speakers_meta)} "
                    f"inconsistent with turn speakers {actual}"
                )
        if isinstance(metadata.get("num_turns"), int) and turn_list:
            if metadata["num_turns"] != len(turn_list):
                violations.append(
                    f"S10 {cid}: metadata num_turns "
                    f"{metadata['num_turns']} != {len(turn_list)} turns"
                )

    return violations


# ---------------------------------------------------------------------------
# Corpus-level validation
# ---------------------------------------------------------------------------

def _normalise_calls(calls: Any) -> list[Mapping]:
    if isinstance(calls, Mapping):
        return [v for v in calls.values() if isinstance(v, Mapping)]
    if isinstance(calls, (list, tuple)):
        return [c for c in calls if isinstance(c, Mapping)]
    return []


def _normalise_assignments(assignments: Any) -> dict[str, Mapping]:
    out: dict[str, Mapping] = {}
    items: list[Any] = []
    if isinstance(assignments, Mapping):
        if isinstance(assignments.get("assignments"), (Mapping, list)):
            return _normalise_assignments(assignments["assignments"])
        for key, val in assignments.items():
            if isinstance(val, Mapping):
                merged = dict(val)
                merged.setdefault("call_id", key)
                out[str(key)] = merged
            else:
                items.append(val)
        return out
    if isinstance(assignments, (list, tuple)):
        items = list(assignments)
    for a in items:
        if isinstance(a, Mapping) and isinstance(a.get("call_id"), str):
            out[a["call_id"]] = a
    return out


def validate_corpus(
    calls: Any,
    assignments: Any,
    glossary_ids: Iterable[str] | Mapping,
    real_lexicon: Iterable[str] | Mapping,
) -> list[str]:
    """Validate a whole corpus: per-call checks plus corpus-level S6/S7/S10.

    Returns violation strings with stable ``S1``..``S10`` code prefixes.
    """
    violations: list[str] = []
    call_list = _normalise_calls(calls)
    assign_map = _normalise_assignments(assignments)
    glossary = _canon_set(glossary_ids if glossary_ids is not None else [])
    real_set = _canon_set(real_lexicon if real_lexicon is not None else [])

    seen: set[str] = set()
    for call in call_list:
        cid = _call_id(call)
        if cid in seen and cid != "<unknown>":
            violations.append(f"S10 {cid}: duplicate call_id in corpus")
        seen.add(cid)

    for call in call_list:
        cid = _call_id(call)
        assignment = assign_map.get(cid)
        if assignment is None:
            violations.append(f"S10 {cid}: no assignment entry for call")
            assignment = {}
        mism = _mismatched_for_call(None, assignment, call)
        violations.extend(validate_script(call, assignment, glossary, mism))

    # Corpus-level S3: assignment term classes must agree with real_lexicon.
    if real_set:
        for cid, assignment in assign_map.items():
            real_terms, fict_terms = _expected_lists(assignment, {})
            for t in real_terms:
                if _canon_str(t) not in real_set:
                    violations.append(
                        f"S3 {cid}: real term {t!r} not in real lexicon"
                    )
            for t in fict_terms:
                if _canon_str(t) in real_set:
                    violations.append(
                        f"S3 {cid}: fictional term {t!r} collides "
                        f"with real lexicon"
                    )

    # Corpus-level S6: present set must equal assigned set (+10/20 rule).
    known_pairs: list[list[str]] = []
    for assignment in assign_map.values():
        _, pair = _hard_negative(assignment, {})
        if len(pair) == 2:
            known_pairs.append(pair)
    assigned_hn = {
        cid for cid, a in assign_map.items() if _hard_negative(a, {})[0]
    }
    present_hn = set()
    for call in call_list:
        cid = _call_id(call)
        toks_list = [_canon_tokens(t) for t in [
            _turn_text(x) for x in (call.get("turns") or [])] if isinstance(t, str)]
        pairs_to_check = known_pairs or [
            p for _, p in [_hard_negative(assign_map.get(cid, {}), call)]
            if len(p) == 2
        ]
        for pair in pairs_to_check:
            if all(
                any(_span_present(toks, _canon_str(p).split()) for toks in toks_list)
                for p in pair
            ):
                present_hn.add(cid)
                break
    if assigned_hn != present_hn:
        violations.append(
            f"S6 corpus: hard-negative present in {sorted(present_hn)} "
            f"but assigned to {sorted(assigned_hn)}"
        )
    if len(call_list) == CORPUS_SIZE and len(assigned_hn) != HARD_NEG_TARGET:
        violations.append(
            f"S6 corpus: {len(assigned_hn)} calls carry a hard-negative "
            f"pair (need exactly {HARD_NEG_TARGET}/{CORPUS_SIZE})"
        )

    # Corpus-level S7: OOV present set must equal designated set (+6/20 rule).
    known_oov = _canon_set(
        [o for a in assign_map.values() for o in _oov(a, {})[1]]
    )
    assigned_oov = {
        cid for cid, a in assign_map.items() if _oov(a, {})[0]
    }
    present_oov = set()
    for call in call_list:
        cid = _call_id(call)
        toks_list = [_canon_tokens(t) for t in [
            _turn_text(x) for x in (call.get("turns") or [])] if isinstance(t, str)]
        _, own_oov = _oov(assign_map.get(cid, {}), call)
        check = {_canon_str(o) for o in own_oov} | known_oov
        for oc in check:
            if any(_span_present(toks, oc.split()) for toks in toks_list):
                present_oov.add(cid)
                break
    if assigned_oov != present_oov:
        violations.append(
            f"S7 corpus: OOV surfaces in {sorted(present_oov)} "
            f"but designated for {sorted(assigned_oov)}"
        )
    if len(call_list) == CORPUS_SIZE and len(assigned_oov) != OOV_TARGET:
        violations.append(
            f"S7 corpus: {len(assigned_oov)} calls designated OOV "
            f"(need exactly {OOV_TARGET}/{CORPUS_SIZE})"
        )

    return violations


# ---------------------------------------------------------------------------
# Directory CLI: `python -m lexiforge.scripts.validate <dir>`
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_terms_file(path: Path) -> list[str]:
    return _coerce_terms(_load_json(path))


def load_directory(directory: str | Path) -> tuple[list[dict], dict, list[str], list[str]]:
    """Load calls, assignments, glossary ids and real lexicon from a dir."""
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"not a directory: {root}")
    assignment_path = root / "assignment.json"
    if not assignment_path.exists() and (root / "assignments.json").exists():
        assignment_path = root / "assignments.json"
    assignments: dict = {}
    if assignment_path.exists():
        raw = _load_json(assignment_path)
        assignments = _normalise_assignments(raw)

    glossary_ids: list[str] = []
    if (root / "glossary.json").exists():
        glossary_ids = _load_terms_file(root / "glossary.json")

    real_lexicon: list[str] = []
    for name in ("real_lexicon.json", "real-lexicon.json"):
        if (root / name).exists():
            real_lexicon = _load_terms_file(root / name)
            break

    mismatch_map: dict[str, list[str]] = {}
    for name in ("mismatched.json", "mismatch.json"):
        if (root / name).exists():
            raw = _load_json(root / name)
            if isinstance(raw, Mapping):
                mismatch_map = {
                    str(k): _coerce_terms(v) for k, v in raw.items()
                }
            break

    calls: list[dict] = []
    for path in sorted(root.glob("*.json")):
        if path.name in RESERVED_FILES:
            continue
        raw = _load_json(path)
        items = raw if isinstance(raw, list) else [raw]
        for item in items:
            if not isinstance(item, Mapping):
                continue
            call = dict(item)
            call.setdefault("call_id", path.stem)
            if mismatch_map.get(call["call_id"]):
                call.setdefault(
                    "mismatched_terms", mismatch_map[call["call_id"]]
                )
            calls.append(call)
            if call["call_id"] not in assignments and (
                call.get("expected_real_terms") or call.get("real_terms")
            ):
                assignments.setdefault(call["call_id"], {
                    "call_id": call["call_id"],
                    "expected_real_terms": call.get("expected_real_terms", []),
                    "expected_fictional_terms": call.get(
                        "expected_fictional_terms", []),
                    "hard_negative_pair": call.get("hard_negative_pair"),
                    "hard_negative_assigned": call.get(
                        "hard_negative_assigned", False),
                    "oov_terms": call.get("oov_terms", []),
                    "oov_assigned": call.get("oov_assigned", False),
                })
    return calls, assignments, glossary_ids, real_lexicon


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lexiforge.scripts.validate",
        description="Validate script directory against checks S1-S10.",
    )
    parser.add_argument("directory", help="directory of call JSON files")
    args = parser.parse_args(argv)
    try:
        calls, assignments, glossary_ids, real_lexicon = load_directory(
            args.directory
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not calls:
        print(f"error: no call files in {args.directory}", file=sys.stderr)
        return 2
    violations = validate_corpus(calls, assignments, glossary_ids, real_lexicon)
    for v in violations:
        print(v)
    print(
        f"{len(violations)} violation(s) across {len(calls)} call(s)",
        file=sys.stderr,
    )
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
