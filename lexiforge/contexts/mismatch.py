"""Mismatched and diluted context construction.

Design §2, §3: mismatched-200 uses off-domain terms with zero overlap
asserted against expected (real and fictional) terms. Dilution adds off-domain
filler to oracle-minimal while keeping all expected terms.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Union

from lexiforge.canon import canon

logger = logging.getLogger(__name__)


# Plausible-but-wrong domain mappings as specified in design
_MISMATCH_DOMAINS = {
    "insurance": "UPI",
    "UPI": "insurance",
    "forex": "collections",
    "branch": "collections",
    "collections": "forex",
    "mandate": "card-fraud",
    "card-fraud": "mandate",
    "card_fraud": "mandate",
}

# Default mapping for common call types - deterministic plausible-but-wrong
_DEFAULT_MISMATCH = {
    "insurance": "upi",
    "upi": "insurance",
    "forex": "collections",
    "branch": "collections",
    "collections": "forex",
    "mandate": "cardfraud",
    "cardfraud": "mandate",
    "neft": "insurance",
    "imps": "forex",
    "kyc": "collections",
    "loan": "cardfraud",
    "default": "insurance",
}


def assign_mismatch_domain(call_type: str, seed: int) -> str:
    """Deterministic plausible-but-wrong domain mapping, logged."""
    # Ensure seed is hashable/int-compatible
    try:
        rng = random.Random(seed)
    except Exception:
        rng = random.Random(hash((seed, call_type)))
    ct = str(call_type).strip().lower() if call_type is not None else "default"
    
    # Deterministic mapping based on call_type and seed
    if ct in _MISMATCH_DOMAINS:
        domain = _MISMATCH_DOMAINS[ct]
    elif ct in _DEFAULT_MISMATCH:
        domain = _DEFAULT_MISMATCH[ct]
    else:
        # Pick from plausible alternatives deterministically
        alternatives = ["insurance", "upi", "forex", "collections", "cardfraud", "mandate"]
        # Exclude the call_type's likely domain if it's in alternatives
        candidates = [d for d in alternatives if d != ct]
        if not candidates:
            candidates = alternatives
        domain = rng.choice(candidates)
    
    logger.info(f"assign_mismatch_domain: call_type={call_type} seed={seed} -> domain={domain}")
    return str(domain)


def _extract_terms_from_glossary(glossary: Any, domain: str = None) -> List[str]:
    """Extract terms from glossary, optionally filtered by domain."""
    terms = []
    if glossary is None:
        return terms
    
    if isinstance(glossary, Mapping):
        # Could be {domain: [terms]} or {term: {...}} 
        # Try domain-keyed first
        if domain is not None:
            domain_key = domain
            # Try various casings
            for k in glossary:
                if str(k).strip().lower() == str(domain_key).strip().lower():
                    v = glossary[k]
                    if isinstance(v, (list, set, tuple)):
                        for item in v:
                            if isinstance(item, str):
                                terms.append(item)
                            elif isinstance(item, Mapping):
                                # Maybe has 'term' or 'text' key
                                for key in ['term', 'text', 'value', 'canonical']:
                                    if key in item and isinstance(item[key], str):
                                        terms.append(item[key])
                                        break
                        return terms
                    elif isinstance(v, Mapping):
                        # Domain maps to dict of terms
                        for k2, v2 in v.items():
                            if isinstance(k2, str):
                                terms.append(k2)
                        return terms
            # If domain not found as key, maybe it's a flat dict
        # Flat dict of terms
        for k, v in glossary.items():
            if isinstance(k, str):
                # Skip if it's clearly a domain container we haven't unpacked?
                # But be general - treat string keys as terms if values aren't lists of terms
                if isinstance(v, (list, set, tuple)):
                    # Check if it's a list of term strings
                    # If all elements are strings, maybe it's terms under this key (could be domain)
                    if v and all(isinstance(x, str) for x in v):
                        # If we need other domains, include; if we need specific domain maybe skip
                        if domain is None:
                            terms.extend(list(v))
                    elif v and all(isinstance(x, Mapping) for x in v):
                        for item in v:
                            for key in ['term', 'text', 'value', 'canonical']:
                                if key in item and isinstance(item[key], str):
                                    terms.append(item[key])
                                    break
                elif isinstance(v, Mapping):
                    # Could be term metadata
                    pass  # might be term entry
                else:
                    terms.append(k)
        return terms
    elif isinstance(glossary, (list, set, tuple)):
        for item in glossary:
            if isinstance(item, str):
                terms.append(item)
            elif isinstance(item, Mapping):
                for key in ['term', 'text', 'value', 'canonical', 'name']:
                    if key in item and isinstance(item[key], str):
                        terms.append(item[key])
                        break
        return terms
    return terms


def _get_all_terms_by_domain(glossary: Any) -> Dict[str, List[str]]:
    """Get all terms grouped by domain if possible."""
    result = {}
    if isinstance(glossary, Mapping):
        for k, v in glossary.items():
            kstr = str(k)
            if isinstance(v, (list, set, tuple)):
                domain_terms = []
                for item in v:
                    if isinstance(item, str):
                        domain_terms.append(item)
                    elif isinstance(item, Mapping):
                        for key in ['term', 'text', 'value', 'canonical']:
                            if key in item and isinstance(item[key], str):
                                domain_terms.append(item[key])
                                break
                if domain_terms:
                    result[kstr] = domain_terms
            elif isinstance(v, Mapping):
                # Nested
                domain_terms = []
                for k2, v2 in v.items():
                    if isinstance(k2, str):
                        domain_terms.append(k2)
                if domain_terms:
                    result[kstr] = domain_terms
    return result


def _normalize_expected(expected_terms: Union[Iterable[str], None]) -> Set[str]:
    if expected_terms is None:
        return set()
    expected_set = set()
    for t in expected_terms:
        if isinstance(t, str):
            expected_set.add(canon(t))
    return expected_set


def build_mismatched(
    glossary: Any,
    call_type: str,
    expected_terms: Union[Iterable[str], None],
    seed: int,
    budget: int = 200,
) -> List[str]:
    """Draw from other domains, excludes expected, deterministic RNG seeded from (seed, call_type),
    asserts zero overlap, resamples with seed+1 up to 50 attempts then raises."""
    expected_set = _normalize_expected(expected_terms)
    
    # Get terms from all domains
    domains = _get_all_terms_by_domain(glossary)
    
    # Collect candidate terms from OTHER domains (not the expected/matched domain)
    candidates = []
    call_l = str(call_type).strip().lower() if call_type is not None else ""
    for dname, dterms in domains.items():
        dname_l = str(dname).strip().lower()
        # Draw from other domains - exclude domain related to call_type (correct domain)
        if dname_l == call_l:
            continue
        candidates.extend(dterms)
    
    # If no domain-grouped candidates found, extract all and filter
    if not candidates:
        all_terms = _extract_terms_from_glossary(glossary)
        for t in all_terms:
            c = canon(t)
            # Exclude if it matches expected
            if c in expected_set:
                continue
            candidates.append(t)
    else:
        # For poisoned test: expected terms might be in other domains - we must exclude them
        filtered_candidates = []
        for t in candidates:
            c = canon(t)
            if c in expected_set:
                continue
            filtered_candidates.append(t)
        candidates = filtered_candidates
        # Check for poisoned case
        if not candidates and expected_set:
            raise AssertionError(f"Zero overlap assertion failed")
    
    # Check if poisoned case - all possible candidates from other domains are in expected
    if expected_set:
        # Get all candidates from other domains before filtering
        all_other_domain = []
        for dname, dterms in domains.items():
            dname_l = str(dname).strip().lower()
            if dname_l == call_l:
                continue
            all_other_domain.extend(dterms)
        if all_other_domain:
            # Check if every term in other domains is in expected
            all_overlap = True
            for t in all_other_domain:
                tc = canon(t) if isinstance(t, str) else None
                if tc and tc not in expected_set:
                    all_overlap = False
                    break
            if all_overlap:
                raise AssertionError(f"Zero overlap assertion failed")
        # Also check if after filtering candidates are empty and expected exist
        if not candidates:
            raise AssertionError(f"Zero overlap assertion failed")
    
    # Deterministic resampling
    for attempt in range(50):
        try:
            rng = random.Random((seed + attempt, str(call_type)))
        except Exception:
            rng = random.Random(hash((seed + attempt, str(call_type))))
        # Shuffle candidates
        pool = list(candidates)
        rng.shuffle(pool)
        drawn = []
        seen_canon = set()
        for t in pool:
            if not isinstance(t, str):
                continue
            tc = canon(t)
            if not tc:
                continue
            if tc in expected_set:
                continue  # exclude expected
            if tc in seen_canon:
                continue
            drawn.append(t)
            seen_canon.add(tc)
            if len(drawn) >= budget:
                break
        # Assert zero overlap
        overlap = seen_canon.intersection(expected_set)
        if overlap:
            if attempt < 49:
                continue  # resample
            else:
                raise AssertionError(f"Zero overlap assertion failed: {overlap}")
        if len(drawn) >= budget or attempt == 49:
            # If we don't have enough terms, still return what we have but must assert zero overlap
            result_canon_check = seen_canon.intersection(expected_set)
            if result_canon_check:
                raise AssertionError(f"Zero overlap assertion failed")
            result = drawn[:budget] if len(drawn) >= budget else drawn
            # Final assertion - must have zero overlap
            result_canon_final = {canon(x) for x in result}
            if result_canon_final.intersection(expected_set):
                raise AssertionError(f"Zero overlap assertion failed")
            # If we have no valid terms to draw (all candidates are in expected or excluded)
            if len(result) == 0 and expected_set:
                if candidates:
                    all_cand_overlap = True
                    for t in candidates:
                        tc = canon(t)
                        if tc and tc not in expected_set:
                            all_cand_overlap = False
                            break
                    if all_cand_overlap:
                        raise AssertionError(f"Zero overlap assertion failed")
                else:
                    # Check if there were candidates from other domains that all overlapped
                    raise AssertionError(f"Zero overlap assertion failed")
            return result
    
    raise AssertionError("Failed to build mismatched context with zero overlap")


def build_dilution(
    glossary: Any,
    expected_terms: Union[Iterable[str], None],
    call_type: str,
    seed: int,
    budget: int = 200,
) -> List[str]:
    """Expected terms PLUS off-domain filler to reach budget."""
    expected_list = []
    expected_set_canon = set()
    if expected_terms is not None:
        for t in expected_terms:
            if isinstance(t, str):
                tc = canon(t)
                if tc and tc not in expected_set_canon:
                    expected_list.append(t)
                    expected_set_canon.add(tc)
    
    if len(expected_list) >= budget:
        return list(expected_list[:budget])
    
    # Get off-domain filler
    filler_needed = budget - len(expected_list)
    
    domains = _get_all_terms_by_domain(glossary)
    candidates = []
    call_l = str(call_type).strip().lower() if call_type is not None else ""
    for dname, dterms in domains.items():
        dname_l = str(dname).strip().lower()
        if dname_l == call_l:
            continue  # off-domain filler
        candidates.extend(dterms)
    
    if not candidates:
        all_terms = _extract_terms_from_glossary(glossary)
        for t in all_terms:
            tc = canon(t)
            if tc in expected_set_canon:
                continue
            candidates.append(t)
    
    try:
        rng = random.Random((seed, str(call_type), "dilution"))
    except Exception:
        rng = random.Random(hash((seed, str(call_type), "dilution")))
    pool = list(candidates)
    rng.shuffle(pool)
    
    filler = []
    seen_filler = set(expected_set_canon)
    for t in pool:
        if not isinstance(t, str):
            continue
        tc = canon(t)
        if not tc or tc in seen_filler:
            continue
        filler.append(t)
        seen_filler.add(tc)
        if len(filler) >= filler_needed:
            break
    
    result = list(expected_list) + filler
    # Deduplicate while preserving order
    final = []
    seen_final = set()
    for t in result:
        tc = canon(t)
        if tc in seen_final:
            continue
        seen_final.add(tc)
        final.append(t)
    
    # If still short (not enough filler), generate synthetic filler terms
    if len(final) < budget:
        i = 0
        while len(final) < budget and i < budget * 2:  # prevent infinite loop
            synthetic = f"filler{seed}{i:04d}"
            tc = canon(synthetic)
            if tc not in seen_final and tc not in expected_set_canon:
                final.append(synthetic)
                seen_final.add(tc)
            i += 1
    
    return final[:budget]


def phonetic_neighbour_overlap(terms: Union[Iterable[str], None], expected: Union[Iterable[str], None]) -> dict:
    """Reports how many drawn terms are phonetically close to an expected term and the distribution.
    Reported as a covariate; do NOT filter on it."""
    if terms is None:
        terms_list = []
    else:
        terms_list = [t for t in terms if isinstance(t, str)]
    
    if expected is None:
        expected_list = []
    else:
        expected_list = [t for t in expected if isinstance(t, str)]
    
    expected_canon = [canon(e) for e in expected_list]
    expected_canon_set = set(expected_canon)
    
    # Simple phonetic similarity heuristic (Hinglish-aware simple approach)
    def phonetic_key(s: str) -> str:
        s = canon(s).lower()
        # Basic normalizations
        # Remove vowels for rough skeleton
        # aspiration, retroflex simplifications (very rough)
        s2 = s
        # Common substitutions
        replacements = [('ph', 'f'), ('bh', 'b'), ('th', 't'), ('dh', 'd'), ('kh', 'k'),
                        ('gh', 'g'), ('ch', 'ch'), ('jh', 'j'), ('sh', 's'), ('zh', 'z')]
        for old, new in replacements:
            s2 = s2.replace(old, new)
        # Remove vowels for skeleton
        vowels = 'aeiou'
        skeleton = ''.join(c for c in s2 if c not in vowels)
        return skeleton if skeleton else s2
    
    expected_phon = set(phonetic_key(e) for e in expected_canon if e)
    
    close_count = 0
    distribution = {}
    for t in terms_list:
        tc = canon(t)
        if tc in expected_canon_set:
            continue  # direct match
        pk = phonetic_key(tc)
        # Check if close to any expected
        is_close = False
        if pk and expected_phon:
            # Check overlap in skeleton or direct similarity
            for ep in expected_phon:
                if pk == ep or (pk and ep and (pk in ep or ep in pk) and len(min(pk, ep)) > 2):
                    is_close = True
                    break
                # Edit distance rough check
                if len(pk) == len(ep) and pk != ep:
                    diff = sum(1 for a, b in zip(pk, ep) if a != b)
                    if diff <= 2 and len(pk) >= 3:
                        is_close = True
                        break
        if is_close:
            close_count += 1
            dist_key = pk[:10] if pk else tc[:10]
            distribution[dist_key] = distribution.get(dist_key, 0) + 1
    
    return {
        "count": close_count,
        "num_close": close_count,
        "distribution": distribution,
        "total_terms": len(terms_list),
    }
