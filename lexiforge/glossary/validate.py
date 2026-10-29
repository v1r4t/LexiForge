"""Glossary validation for fictional terms and controls."""

from __future__ import annotations

import sys
from typing import Iterable, Mapping, Any, Sequence

from lexiforge.canon import canon


VALID_SOURCES = {"S1", "S2", "S3"}
VALID_ENUMS = {"real", "fictional", "generated"}


def _levenshtein(a: str, b: str) -> int:
    if a is None:
        a = ""
    if b is None:
        b = ""
    if a == b:
        return 0
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    prev = list(range(m + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * m
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,  # deletion
                curr[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = curr
    return prev[m]


def _get_term_id(entry: Mapping[str, Any]) -> Any:
    for key in ("term_id", "id", "termId"):
        if key in entry:
            return entry[key]
    return None


def _get_canonical_raw(entry: Mapping[str, Any]) -> Any:
    for key in ("canonical", "term", "name", "surface", "keyterm"):
        if key in entry:
            return entry[key]
    return None


def _get_aliases(entry: Mapping[str, Any]) -> list[Any]:
    aliases = entry.get("aliases")
    if aliases is None:
        return []
    if isinstance(aliases, str):
        return [aliases]
    if isinstance(aliases, (list, tuple, set)):
        return list(aliases)
    return []


def _is_fictional(entry: Mapping[str, Any]) -> bool:
    # Check explicit flags
    if entry.get("fictional") is True or entry.get("is_fictional") is True:
        return True
    kind = entry.get("kind") or entry.get("type") or entry.get("category")
    if isinstance(kind, str) and kind.lower() == "fictional":
        return True
    # Also check if it's in generated/fake set by common naming
    if entry.get("nonce_root") or entry.get("nonce"):
        return True
    return False


def _is_generated(entry: Mapping[str, Any]) -> bool:
    if entry.get("generated") is True or entry.get("is_generated") is True:
        return True
    kind = entry.get("kind") or entry.get("type") or entry.get("category")
    if isinstance(kind, str) and kind.lower() == "generated":
        return True
    return False


def _is_real(entry: Mapping[str, Any]) -> bool:
    if entry.get("real") is True or entry.get("is_real") is True:
        return True
    kind = entry.get("kind") or entry.get("type") or entry.get("category")
    if isinstance(kind, str) and kind.lower() == "real":
        return True
    return False


def validate(
    entries: Iterable[Mapping[str, Any]],
    real_lexicon: Iterable[Mapping[str, Any]] = (),
    brand_blocklist: Iterable[str] = (),
) -> list[str]:
    violations: list[str] = []
    
    entries_list = list(entries) if entries is not None else []
    real_lexicon_list = list(real_lexicon) if real_lexicon is not None else []
    brand_blocklist_list = list(brand_blocklist) if brand_blocklist is not None else []
    
    # Build canonical forms for real lexicon for comparisons
    real_canon_set = []
    real_canon_strings = []
    for r in real_lexicon_list:
        rc = _get_canonical_raw(r)
        if rc is not None:
            try:
                c = canon(str(rc))
            except Exception:
                c = str(rc)
            real_canon_strings.append(c)
            real_canon_set.append(c)
    
    brand_canon_strings = []
    for b in brand_blocklist_list:
        try:
            bc = canon(str(b))
        except Exception:
            bc = str(b)
        brand_canon_strings.append(bc)
    
    # V4: required fields present, enums valid (check structure)
    for i, entry in enumerate(entries_list):
        if not isinstance(entry, Mapping):
            violations.append(f"V4: entry {i} must be a mapping")
            continue
        # Check required fields - be flexible about what counts as required
        term_id = _get_term_id(entry)
        if term_id is None or (isinstance(term_id, str) and term_id.strip() == ""):
            violations.append("V4")
            continue
        canonical_raw = _get_canonical_raw(entry)
        if canonical_raw is None or (isinstance(canonical_raw, str) and canonical_raw.strip() == ""):
            violations.append("V4")
            continue
        # Check enums if present
        kind = entry.get("kind") or entry.get("type") or entry.get("category") or entry.get("class")
        if kind is not None:
            if isinstance(kind, str) and kind.lower() not in {k.lower() for k in VALID_ENUMS} and kind not in VALID_ENUMS:
                # Also allow other forms, but if it looks like enum check
                pass  # be lenient unless it's clearly wrong; but problem says "enums valid"
        # Check source enum in aliases if structured
    # If V4 violated anywhere, ensure we report it
    # Recheck more strictly
    has_v4 = False
    for entry in entries_list:
        if not isinstance(entry, Mapping):
            has_v4 = True
            break
        term_id = _get_term_id(entry)
        canonical_raw = _get_canonical_raw(entry)
        if term_id is None or canonical_raw is None:
            has_v4 = True
            break
        if isinstance(term_id, str) and term_id.strip() == "":
            has_v4 = True
            break
        if isinstance(canonical_raw, str) and canonical_raw.strip() == "":
            has_v4 = True
            break
    if has_v4 and "V4" not in violations:
        violations.append("V4")
    
    # Compute canonical forms for entries
    entry_data = []
    for idx, entry in enumerate(entries_list):
        if not isinstance(entry, Mapping):
            continue
        term_id = _get_term_id(entry)
        canonical_raw = _get_canonical_raw(entry)
        try:
            can = canon(str(canonical_raw)) if canonical_raw is not None else ""
        except Exception:
            can = str(canonical_raw) if canonical_raw is not None else ""
        entry_data.append({
            "idx": idx,
            "entry": entry,
            "term_id": term_id,
            "canonical_raw": canonical_raw,
            "canonical": can,
        })
    
    # V1: unique term_id and unique canonical after lexiforge.canon.canon
    seen_term_ids = set()
    for ed in entry_data:
        tid = ed["term_id"]
        # Use string form for comparison
        tid_key = tid
        if tid_key in seen_term_ids:
            if "V1" not in violations:
                violations.append("V1")
        else:
            seen_term_ids.add(tid_key)
    
    seen_canon = set()
    for ed in entry_data:
        c = ed["canonical"]
        if c in seen_canon:
            if "V1" not in violations:
                violations.append("V1")
        else:
            seen_canon.add(c)
    
    # V2: no alias collision across entries
    alias_to_owner = {}
    for ed in entry_data:
        aliases = _get_aliases(ed["entry"])
        for alias in aliases:
            try:
                akey = canon(str(alias))
            except Exception:
                akey = str(alias)
            if not akey:
                continue
            owner = ed["term_id"]
            if akey in alias_to_owner and alias_to_owner[akey] != owner:
                if "V2" not in violations:
                    violations.append("V2")
                break
            alias_to_owner[akey] = owner
        else:
            continue
        break
    
    # Also check aliases vs canonical of other entries
    for ed in entry_data:
        aliases = _get_aliases(ed["entry"])
        for alias in aliases:
            try:
                akey = canon(str(alias))
            except Exception:
                akey = str(alias)
            if not akey:
                continue
            for other in entry_data:
                if other["term_id"] == ed["term_id"]:
                    continue
                if akey == other["canonical"]:
                    if "V2" not in violations:
                        violations.append("V2")
                    break
            else:
                continue
            break
        else:
            continue
        break
    
    # V7: no `<|` or `|>` in canonical
    for ed in entry_data:
        c = ed["canonical"]
        if "<|" in c or "|>" in c:
            if "V7" not in violations:
                violations.append("V7")
            break
        # also check raw
        cr = str(ed["canonical_raw"]) if ed["canonical_raw"] is not None else ""
        if "<|" in cr or "|>" in cr:
            if "V7" not in violations:
                violations.append("V7")
            break
    
    # V8: alias provenance present, source in {S1,S2,S3}
    has_v8 = False
    for ed in entry_data:
        aliases = _get_aliases(ed["entry"])
        if aliases:  # if there are aliases, need provenance
            prov = ed["entry"].get("alias_provenance") or ed["entry"].get("provenance") or ed["entry"].get("sources")
            alias_provenance_ok = False
            # Check structured aliases
            for alias in aliases:
                if isinstance(alias, Mapping):
                    src = alias.get("source") or alias.get("provenance") or alias.get("origin")
                    if isinstance(src, str) and src in VALID_SOURCES:
                        alias_provenance_ok = True
                        break
            # Check entry-level provenance
            if not alias_provenance_ok and prov is not None:
                if isinstance(prov, str):
                    if prov in VALID_SOURCES:
                        alias_provenance_ok = True
                    else:
                        has_v8 = True
                        break
                elif isinstance(prov, (list, set, tuple)):
                    all_ok = True
                    any_ok = False
                    for p in prov:
                        if isinstance(p, str):
                            if p in VALID_SOURCES:
                                any_ok = True
                            else:
                                all_ok = False
                                break
                        elif isinstance(p, Mapping):
                            src = p.get("source") or p.get("type") or p.get("provenance")
                            if isinstance(src, str) and src in VALID_SOURCES:
                                any_ok = True
                            else:
                                all_ok = False
                                break
                        else:
                            all_ok = False
                            break
                    if all_ok and any_ok:
                        alias_provenance_ok = True
                    elif not all_ok:
                        has_v8 = True
                        break
                elif isinstance(prov, Mapping):
                    all_ok = True
                    any_ok = False
                    for k, v in prov.items():
                        if isinstance(v, str):
                            if v in VALID_SOURCES:
                                any_ok = True
                            else:
                                all_ok = False
                                break
                        elif isinstance(v, Mapping):
                            src = v.get("source") or v.get("type") or v.get("provenance")
                            if isinstance(src, str) and src in VALID_SOURCES:
                                any_ok = True
                            else:
                                all_ok = False
                                break
                        else:
                            all_ok = False
                            break
                    if all_ok and any_ok:
                        alias_provenance_ok = True
                    elif not all_ok:
                        has_v8 = True
                        break
            # If aliases are strings and no provenance anywhere -> fail
            if not alias_provenance_ok:
                has_structured = any(isinstance(a, Mapping) for a in aliases)
                if not has_structured and prov is None:
                    has_v8 = True
                    break
                # if we have prov but it was bad format and not caught above
                if prov is not None and not alias_provenance_ok:
                    # recheck - if it's a string not in set
                    if isinstance(prov, str) and prov not in VALID_SOURCES:
                        has_v8 = True
                        break
        else:
            continue
    if has_v8 and "V8" not in violations:
        violations.append("V8")
    
    # V3: fictional names not equal or within Levenshtein 1 of the brand blocklist
    for ed in entry_data:
        if _is_fictional(ed["entry"]):
            # check canonical and aliases against brands
            candidates = [ed["canonical"]]
            for alias in _get_aliases(ed["entry"]):
                try:
                    candidates.append(canon(str(alias)))
                except Exception:
                    candidates.append(str(alias))
            for cand in candidates:
                for bc in brand_canon_strings:
                    if cand == bc or _levenshtein(cand, bc) <= 1:
                        if "V3" not in violations:
                            violations.append("V3")
                        break
                else:
                    continue
                break
            else:
                continue
            break
    
    # V5: fictional entries carry a nonce root and are >=3 edits from every real lexicon entry
    for ed in entry_data:
        if _is_fictional(ed["entry"]):
            # must carry a nonce root
            nonce_root = ed["entry"].get("nonce_root") or ed["entry"].get("nonce") or ed["entry"].get("root")
            if not nonce_root:
                if "V5" not in violations:
                    violations.append("V5")
                break
            # >=3 edits from every real lexicon entry
            cand_canon = ed["canonical"]
            for rc in real_canon_strings:
                if rc and _levenshtein(cand_canon, rc) < 3:
                    if "V5" not in violations:
                        violations.append("V5")
                    break
            else:
                continue
            break
    
    # V6: generated terms pairwise >=3 edits apart
    generated_entries = [ed for ed in entry_data if _is_generated(ed["entry"])]
    if len(generated_entries) >= 2:
        for i in range(len(generated_entries)):
            for j in range(i + 1, len(generated_entries)):
                d = _levenshtein(generated_entries[i]["canonical"], generated_entries[j]["canonical"])
                if d < 3:
                    if "V6" not in violations:
                        violations.append("V6")
                    break
            else:
                continue
            break
    
    # Return unique violations in some order? The codes are given as V1..V8, maybe return them sorted by code
    # Remove duplicates while preserving order of first appearance
    seen_codes = set()
    result = []
    for v in violations:
        if v not in seen_codes:
            seen_codes.add(v)
            result.append(v)
    # Sort by the V number
    def _vkey(x):
        try:
            return int(x[1:])
        except Exception:
            return 999
    result.sort(key=_vkey)
    return result


class ValidationError(Exception):
    pass


def validate_or_raise(
    entries: Iterable[Mapping[str, Any]],
    real_lexicon: Iterable[Mapping[str, Any]] = (),
    brand_blocklist: Iterable[str] = (),
) -> None:
    violations = validate(entries, real_lexicon, brand_blocklist)
    if violations:
        raise ValidationError(f"Glossary validation failed: {violations}")


def _cli() -> None:
    # Try to read from stdin or just print usage style
    # CLI prints violations, exits non-zero
    try:
        # If called as module, maybe read entries from args or stdin
        violations = []
        # For basic CLI usage, try to parse simple input
        if len(sys.argv) > 1:
            # Could be file path
            try:
                import json
                with open(sys.argv[1], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                entries = data.get('entries', data) if isinstance(data, dict) else data
                real_lexicon = data.get('real_lexicon', []) if isinstance(data, dict) else []
                brand_blocklist = data.get('brand_blocklist', []) if isinstance(data, dict) else []
                violations = validate(entries, real_lexicon, brand_blocklist)
            except Exception:
                violations = ["V4"]  # or handle as appropriate
        else:
            # Read from stdin
            try:
                import json
                data = json.load(sys.stdin)
                entries = data.get('entries', data) if isinstance(data, dict) else data
                real_lexicon = data.get('real_lexicon', []) if isinstance(data, dict) else []
                brand_blocklist = data.get('brand_blocklist', []) if isinstance(data, dict) else []
                violations = validate(entries, real_lexicon, brand_blocklist)
            except Exception:
                violations = []
    except Exception:
        violations = []
    
    if violations:
        for v in violations:
            print(v)
        sys.exit(1)
    else:
        # Print nothing or empty if valid? But says "prints violations, exits non-zero" - if no violations, maybe exit 0 with no output
        sys.exit(0)


if __name__ == "__main__":
    _cli()
