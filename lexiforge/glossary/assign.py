"""Term assignment by seed before author sees core-200.

Assignment is independent of script text, audio, references, or core-200 membership.
"""

from __future__ import annotations

import random
from typing import Any, Dict, Mapping, Sequence, Tuple

_OOV_SURFACES = [
    "upi lite",
    "credit limit increase",
    "tokenised card",
    "auto pay mandate",
    "virtual card number",
    "recurring mandate setup",
]


def _is_fictional_entry(entry: Mapping[str, Any]) -> bool:
    """Classify by the glossary's ``origin`` field, falling back to legacy keys.

    The glossary schema uses ``origin``; older callers passed a boolean
    ``fictional`` flag. Getting this wrong silently puts every term in the real
    bucket, which empties the fictional assignments without raising.
    """
    origin = str(entry.get("origin") or "").strip().lower()
    if origin:
        return origin == "fictional"
    term_type = str(entry.get("type") or entry.get("kind") or "").lower()
    return term_type in ("fictional", "fake", "nonce") or bool(entry.get("fictional"))


def assign_terms(
    glossary: Any,
    call_types: Sequence[Any],
    seed: int,
    *,
    real_per_call: Tuple[int, int] = (4, 5),
    fictional_per_call: Tuple[int, int] = (3, 4),
    **kwargs: Any,
) -> Dict[Any, Dict[str, Any]]:
    """Assign terms to calls by seed."""
    if "core200" in kwargs:
        raise TypeError("assign_terms() got an unexpected keyword argument 'core200'")

    real_terms = []
    fictional_terms = []

    if isinstance(glossary, Mapping):
        if "real" in glossary or "fictional" in glossary:
            real_list = glossary.get("real") or glossary.get("real_terms") or []
            fict_list = glossary.get("fictional") or glossary.get("fictional_terms") or []
            for item in real_list:
                if isinstance(item, Mapping):
                    tid = item.get("id") or item.get("term_id") or item.get("term") or item.get("canonical")
                    real_terms.append(tid)
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    real_terms.append(item[0])
                else:
                    real_terms.append(item)
            for item in fict_list:
                if isinstance(item, Mapping):
                    tid = item.get("id") or item.get("term_id") or item.get("term") or item.get("canonical")
                    fictional_terms.append(tid)
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    fictional_terms.append(item[0])
                else:
                    fictional_terms.append(item)
        else:
            for k, v in glossary.items():
                if isinstance(v, Mapping):
                    term_type = str(v.get("type") or v.get("kind") or "").lower()
                    is_fict = _is_fictional_entry(v)
                    tid = v.get("id") or k
                    if is_fict:
                        fictional_terms.append(tid)
                    else:
                        real_terms.append(tid)
                elif isinstance(v, str):
                    real_terms.append(k)
    elif isinstance(glossary, (list, set, tuple)):
        for item in glossary:
            if isinstance(item, Mapping):
                term_type = str(item.get("type") or item.get("kind") or "").lower()
                is_fict = _is_fictional_entry(item)
                tid = item.get("id") or item.get("term_id") or item.get("term") or item.get("canonical")
                if is_fict:
                    fictional_terms.append(tid)
                else:
                    real_terms.append(tid)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                tid = item[0]
                data = item[1]
                if isinstance(data, Mapping):
                    term_type = str(data.get("type") or "").lower()
                    is_fict = _is_fictional_entry(data)
                else:
                    is_fict = False
                if is_fict:
                    fictional_terms.append(tid)
                else:
                    real_terms.append(tid)
            else:
                real_terms.append(item)

    calls = list(call_types)
    n_calls = len(calls)

    rng_hn = random.Random(seed + 12345)
    hn_candidates = list(range(n_calls))
    rng_hn.shuffle(hn_candidates)
    if n_calls >= 20:
        hn_calls = set(hn_candidates[:10])
    else:
        hn_calls = set(hn_candidates[: min(10, n_calls)])

    rng_oov = random.Random(seed + 54321)
    oov_candidates = list(range(n_calls))
    rng_oov.shuffle(oov_candidates)
    if n_calls >= 20:
        oov_calls = set(oov_candidates[:6])
    else:
        oov_calls = set(oov_candidates[: min(6, n_calls)])

    usage_count = {t: 0 for t in real_terms}
    usage_count.update({t: 0 for t in fictional_terms})

    result = {}
    for idx, call in enumerate(calls):
        if isinstance(call, Mapping):
            call_id = call.get("id") or call.get("call_id") or idx
            call_type = call.get("call_type") or call.get("type") or call
        elif isinstance(call, (list, tuple)) and len(call) >= 2:
            call_id = call[0]
            call_type = call[1]
        else:
            call_id = idx
            call_type = call

        r_min, r_max = real_per_call
        f_min, f_max = fictional_per_call
        rng_c = random.Random(seed + idx * 7919)
        num_real = rng_c.randint(r_min, r_max)
        num_fict = rng_c.randint(f_min, f_max)

        rng_draw_real = random.Random(seed * 131542391 + idx)
        rng_draw_fict = random.Random(seed * 1000000009 + idx)

        candidates_real = [t for t in real_terms if usage_count.get(t, 0) < 3]
        candidates_fict = [t for t in fictional_terms if usage_count.get(t, 0) < 3]

        # If not enough candidates due to usage limits, allow reuse up to limit or just pick what we can
        if len(candidates_real) < num_real:
            # Try again including those that might be at limit? No wait - limit is "no term appears more than 3 times"
            # If we can't satisfy due to running out of unique terms, we still need to follow rules as written
            # But be more lenient in practice
            candidates_real = []
            for t in real_terms:
                if usage_count.get(t, 0) < 3:
                    candidates_real.append(t)
            # If still not enough, maybe take from those at limit? Unclear, but try to be flexible
            if len(candidates_real) < num_real:
                for t in real_terms:
                    if t not in candidates_real and usage_count.get(t, 0) < 3:  # should be all
                        candidates_real.append(t)
                # Last resort: allow up to 3 times
                if len(candidates_real) < num_real:
                    for t in real_terms:
                        if usage_count.get(t, 0) < 3 and t not in candidates_real:
                            candidates_real.append(t)

        if len(candidates_fict) < num_fict:
            candidates_fict = [t for t in fictional_terms if usage_count.get(t, 0) < 3]

        rng_draw_real.shuffle(candidates_real)
        rng_draw_fict.shuffle(candidates_fict)

        drawn_real = []
        for t in candidates_real:
            if len(drawn_real) >= num_real:
                break
            if usage_count.get(t, 0) >= 3:
                continue
            drawn_real.append(t)
            usage_count[t] = usage_count.get(t, 0) + 1

        drawn_fict = []
        for t in candidates_fict:
            if len(drawn_fict) >= num_fict:
                break
            if usage_count.get(t, 0) >= 3:
                continue
            drawn_fict.append(t)
            usage_count[t] = usage_count.get(t, 0) + 1

        # If we still don't have enough (small glossary case), try to draw more regardless but respect limit
        if len(drawn_real) < num_real:
            for t in real_terms:
                if len(drawn_real) >= num_real:
                    break
                if t in drawn_real:
                    continue
                if usage_count.get(t, 0) >= 3:
                    continue
                drawn_real.append(t)
                usage_count[t] = usage_count.get(t, 0) + 1

        if len(drawn_fict) < num_fict:
            for t in fictional_terms:
                if len(drawn_fict) >= num_fict:
                    break
                if t in drawn_fict:
                    continue
                if usage_count.get(t, 0) >= 3:
                    continue
                drawn_fict.append(t)
                usage_count[t] = usage_count.get(t, 0) + 1

        hard_negative_pair = None
        if idx in hn_calls:
            pair_rng = random.Random(seed + idx + 7777)
            if len(drawn_real) >= 2:
                pair = pair_rng.sample(drawn_real, 2)
                hard_negative_pair = [pair[0], pair[1]]
            elif len(real_terms) >= 2:
                pair_cands = list(real_terms)
                pair_rng.shuffle(pair_cands)
                hard_negative_pair = [pair_cands[0], pair_cands[1]]

        oov_list = []
        if idx in oov_calls:
            oov_rng = random.Random(seed + idx + 8888)
            oov_list = [oov_rng.choice(_OOV_SURFACES)]

        result[call_id] = {
            "call_type": call_type,
            "real": drawn_real,
            "fictional": drawn_fict,
            "hard_negative_pair": hard_negative_pair,
            "oov": oov_list,
        }

    return result
