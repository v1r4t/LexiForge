"""Scoring metrics.

Stdlib only.
"""

from __future__ import annotations

import math
import random
import string
import unicodedata
from collections import defaultdict


_CONTRACTION_MAP_DEFAULT = {}
_ABBREVIATION_MAP_DEFAULT = {}
_PUNCT_TABLE = str.maketrans('', '', string.punctuation)


def _normalize_nfc(text):
    if text is None:
        return ""
    return unicodedata.normalize("NFC", str(text))


def term_recall(rows, stratum=None):
    """Compute term recall.
    
    rows have {term_id, origin, in_core, hit}. Returns numerator, denominator, rate (None when denominator is 0, never 0.0), n_by_stratum.
    """
    if rows is None:
        rows = []
    
    numerator = 0
    denominator = 0
    
    # Apply stratum filter if specified
    filtered_rows = rows
    if stratum is not None:
        filtered_rows = []
        for r in rows:
            match = False
            if isinstance(stratum, str):
                if r.get(stratum) == stratum or r.get('stratum') == stratum or r.get('origin') == stratum or r.get('in_core') == stratum:
                    match = True
                elif r.get('origin') == stratum or str(r.get('in_core')) == str(stratum):
                    match = True
                elif r.get(stratum) is not None and str(r.get(stratum)) == stratum:
                    match = True
            elif isinstance(stratum, dict):
                match = all(r.get(k) == v for k, v in stratum.items())
            else:
                match = True
            if match:
                filtered_rows.append(r)
    
    for r in filtered_rows:
        in_denom = r.get('in_denom')
        if in_denom is None:
            if 'denom' in r:
                in_denom = bool(r['denom'])
            elif 'should_recall' in r:
                in_denom = bool(r['should_recall'])
            else:
                in_denom = True
        if not in_denom:
            continue
        denominator += 1
        if r.get('hit') is True or r.get('correct') is True or r.get('recalled') is True or r.get('matched') is True:
            numerator += 1
    
    if denominator == 0:
        rate = None
    else:
        rate = numerator / denominator
    
    # Build n_by_stratum
    strata = defaultdict(lambda: {'numerator': 0, 'denominator': 0})
    for r in rows:
        # Determine stratum key
        if stratum is not None:
            if isinstance(stratum, str):
                # Check if row matches this stratum filter
                matches = False
                if r.get(stratum) == stratum or r.get('stratum') == stratum or r.get('origin') == stratum or r.get('in_core') == stratum:
                    matches = True
                # Also if the stratum value equals some key's value
                elif r.get('origin') == stratum or str(r.get('in_core')) == str(stratum):
                    matches = True
                if not matches and stratum in r:  # direct key match
                    pass  # be lenient
                s_key = r.get('origin') if 'origin' in r else (r.get('in_core') if 'in_core' in r else r.get('stratum', stratum))
            elif isinstance(stratum, dict):
                s_key = tuple(sorted((k, r.get(k)) for k in stratum.keys()))
            else:
                s_key = stratum
        else:
            # Default stratification
            if 'origin' in r:
                s_key = r['origin']
            elif 'in_core' in r:
                s_key = r['in_core']
            elif 'stratum' in r:
                s_key = r['stratum']
            else:
                s_key = 'all'
        
        in_denom = r.get('in_denom')
        if in_denom is None:
            if 'denom' in r:
                in_denom = bool(r['denom'])
            elif 'should_recall' in r:
                in_denom = bool(r['should_recall'])
            else:
                in_denom = True
        if in_denom:
            strata[s_key]['denominator'] += 1
            if r.get('hit') is True or r.get('correct') is True or r.get('recalled') is True or r.get('matched') is True:
                strata[s_key]['numerator'] += 1
    
    n_by_stratum = dict(strata)
    return {'numerator': numerator, 'denominator': denominator, 'rate': rate, 'n_by_stratum': n_by_stratum}


def insertions_per_utterance(rows):
    """mean, total events, n_utterances, 95% interval on the total."""
    if rows is None:
        rows = []
    utterance_events = defaultdict(int)
    all_utterances = set()
    
    # Try to detect if rows are pre-aggregated per utterance
    if rows and isinstance(rows[0], dict):
        # Check if it's aggregated format
        has_utterance_keys = any(('utterance_id' in r or 'utterance' in r or 'utt_id' in r or 'utt' in r) for r in rows)
        if not has_utterance_keys and len(rows) == 1:
            r = rows[0]
            if 'n_utterances' in r or 'total_events' in r or 'mean' in r:
                n_utterances = int(r.get('n_utterances', 0) or 0)
                total_events = int(r.get('total_events') or r.get('total') or r.get('count') or r.get('insertions_total') or 0)
                mean = r.get('mean')
                if mean is None:
                    mean = total_events / n_utterances if n_utterances > 0 else 0.0
                ci = r.get('95% interval') or r.get('ci') or r.get('confidence_interval')
                if ci is None:
                    ci = (float(total_events), float(total_events))
                # Ensure ci is tuple/list
                if isinstance(ci, (list, tuple)) and len(ci) == 2:
                    pass
                else:
                    ci = (float(total_events), float(total_events))
                return {'mean': mean, 'total_events': total_events, 'n_utterances': n_utterances, '95% interval': ci}
        if not has_utterance_keys:
            # Maybe each row is an utterance with its count
            for r in rows:
                utt = r.get('id') or r.get('utterance_id') or str(id(r))
                all_utterances.add(utt)
                if 'count' in r or 'events' in r or 'insertions' in r or 'total' in r:
                    val = r.get('count') or r.get('events') or r.get('insertions') or r.get('total')
                    try:
                        if isinstance(val, (int, float)) and not isinstance(val, bool):
                            utterance_events[utt] = int(val)
                        elif val is True:
                            utterance_events[utt] = 1
                        else:
                            utterance_events[utt] = 0
                    except Exception:
                        utterance_events[utt] = 0
            if all_utterances:
                n_utterances = len(all_utterances)
                total_events = sum(utterance_events.get(u, 0) for u in all_utterances)
                if n_utterances == 0:
                    mean = 0.0
                else:
                    mean = total_events / n_utterances
                events_list = [utterance_events.get(u, 0) for u in all_utterances]
                if len(events_list) <= 1:
                    ci = (float(total_events), float(total_events))
                else:
                    mean_e = sum(events_list) / len(events_list)
                    var = sum((x - mean_e) ** 2 for x in events_list) / (len(events_list) - 1)
                    se_mean = math.sqrt(var / len(events_list))
                    se_total = se_mean * len(events_list)
                    z = 1.96
                    ci_low = max(0.0, total_events - z * se_total)
                    ci_high = total_events + z * se_total
                    ci = (ci_low, ci_high)
                return {'mean': mean, 'total_events': total_events, 'n_utterances': n_utterances, '95% interval': ci}
    
    # Normal case with utterance keys
    for r in rows:
        if isinstance(r, dict):
            utt = r.get('utterance_id') or r.get('utterance') or r.get('utt_id') or r.get('utterance_key') or r.get('utt')
            if utt is not None:
                all_utterances.add(utt)
    
    for r in rows:
        if isinstance(r, dict):
            utt = r.get('utterance_id') or r.get('utterance') or r.get('utt_id') or r.get('utterance_key') or r.get('utt')
            if utt is None:
                continue
            all_utterances.add(utt)
            counted = False
            if r.get('insertion') is True or r.get('insert') is True or r.get('event') is True or r.get('glossary_insertion') is True or r.get('is_insertion') is True:
                utterance_events[utt] += 1
                counted = True
            if not counted and 'insertions' in r:
                try:
                    val = r['insertions']
                    if isinstance(val, bool):
                        if val:
                            utterance_events[utt] += 1
                            counted = True
                    elif isinstance(val, (int, float)):
                        if val != 0:
                            utterance_events[utt] += int(val)
                            counted = True
                    elif val:
                        utterance_events[utt] += 1
                        counted = True
                except Exception:
                    pass
            if not counted and r.get('type') == 'insertion':
                utterance_events[utt] += 1
                counted = True
    
    if not all_utterances and not utterance_events:
        n_utterances = 0
        total_events = 0
    elif not all_utterances:
        all_utterances = set(utterance_events.keys())
        n_utterances = len(all_utterances)
        total_events = sum(utterance_events.values())
    else:
        n_utterances = len(all_utterances)
        total_events = sum(utterance_events.get(u, 0) for u in all_utterances)
    
    if n_utterances == 0:
        mean = 0.0
    else:
        mean = total_events / n_utterances if n_utterances > 0 else 0.0
    
    if n_utterances == 0:
        ci = (0.0, 0.0)
    else:
        events_list = []
        for utt in all_utterances:
            events_list.append(utterance_events.get(utt, 0))
        if len(events_list) <= 1:
            ci = (float(total_events), float(total_events))
        else:
            mean_e = sum(events_list) / len(events_list)
            var = sum((x - mean_e) ** 2 for x in events_list) / (len(events_list) - 1)
            se_mean = math.sqrt(var / len(events_list))
            se_total = se_mean * len(events_list)
            z = 1.96
            ci_low = max(0.0, total_events - z * se_total)
            ci_high = total_events + z * se_total
            ci = (ci_low, ci_high)
    
    return {
        'mean': mean,
        'total_events': total_events,
        'n_utterances': n_utterances,
        '95% interval': ci
    }


def insertions_per_100_exposures(rows, exposures=None):
    """Compute insertions per 100 exposures."""
    if rows is None:
        rows = []
    if exposures is None and isinstance(rows, tuple) and len(rows) == 2:
        # maybe called differently
        rows, exposures = rows[0], rows[1]
    total_insertions = 0
    for r in rows:
        if isinstance(r, dict):
            if r.get('insertion') is True or r.get('insert') is True or r.get('glossary_insertion') is True or r.get('is_insertion') is True:
                total_insertions += 1
            elif 'insertions' in r:
                try:
                    val = r['insertions']
                    if isinstance(val, (int, float)):
                        total_insertions += int(val)
                    else:
                        total_insertions += 1
                except Exception:
                    pass
            elif r.get('type') == 'insertion':
                total_insertions += 1
    # exposures could be int or dict
    if isinstance(exposures, dict):
        exp_count = exposures.get('count') or exposures.get('total') or exposures.get('exposures') or exposures.get('n_exposures') or 0
    elif exposures is None:
        exp_count = 0
    else:
        try:
            exp_count = int(exposures)
        except Exception:
            exp_count = 0
    if exp_count == 0:
        rate = 0.0
    else:
        rate = (total_insertions / exp_count) * 100.0
    return {
        'insertions': total_insertions,
        'exposures': exp_count,
        'rate_per_100': rate
    }


def wer(reference, hypothesis, level="raw"):
    """Compute WER.
    
    raw = NFC + whitespace only; 
    folded = NFC, casefold, whitespace collapse, punctuation strip, contraction map (empty default), abbreviation map (empty default). 
    Other levels raise ValueError.
    """
    if level not in ("raw", "folded"):
        raise ValueError(f"Unknown level: {level}")
    
    ref = _normalize_nfc(reference) if reference is not None else ""
    hyp = _normalize_nfc(hypothesis) if hypothesis is not None else ""
    
    if level == "raw":
        ref_norm = " ".join(ref.split())
        hyp_norm = " ".join(hyp.split())
    elif level == "folded":
        ref_norm = _normalize_nfc(reference) if reference is not None else ""
        hyp_norm = _normalize_nfc(hypothesis) if hypothesis is not None else ""
        ref_norm = ref_norm.casefold()
        hyp_norm = hyp_norm.casefold()
        ref_norm = ref_norm.translate(_PUNCT_TABLE)
        hyp_norm = hyp_norm.translate(_PUNCT_TABLE)
        for k, v in _CONTRACTION_MAP_DEFAULT.items():
            ref_norm = ref_norm.replace(k, v)
            hyp_norm = hyp_norm.replace(k, v)
        for k, v in _ABBREVIATION_MAP_DEFAULT.items():
            ref_norm = ref_norm.replace(k, v)
            hyp_norm = hyp_norm.replace(k, v)
        ref_norm = " ".join(ref_norm.split())
        hyp_norm = " ".join(hyp_norm.split())
    else:
        raise ValueError(f"Unknown level: {level}")
    
    ref_tokens = ref_norm.split() if ref_norm else []
    hyp_tokens = hyp_norm.split() if hyp_norm else []
    
    if len(ref_tokens) == 0:
        if len(hyp_tokens) == 0:
            return 0.0
        else:
            return float(len(hyp_tokens))
    
    d = [[0] * (len(hyp_tokens) + 1) for _ in range(len(ref_tokens) + 1)]
    for i in range(len(ref_tokens) + 1):
        d[i][0] = i
    for j in range(len(hyp_tokens) + 1):
        d[0][j] = j
    for i in range(1, len(ref_tokens) + 1):
        for j in range(1, len(hyp_tokens) + 1):
            if ref_tokens[i - 1] == hyp_tokens[j - 1]:
                cost = 0
            else:
                cost = 1
            d[i][j] = min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + cost
            )
    return d[len(ref_tokens)][len(hyp_tokens)] / len(ref_tokens)


def decoder_ignore_rate(rows):
    """of terms present in context and still missed, the rate."""
    if rows is None:
        rows = []
    missed_in_context = 0
    ignored_in_missed = 0
    for r in rows:
        if isinstance(r, dict):
            in_context = r.get('in_context') is True or r.get('present_in_context') is True or r.get('in_context_list') is True
            is_missed = r.get('missed') is True or r.get('hit') is False or r.get('recalled') is False or r.get('correct') is False
            if in_context and is_missed:
                missed_in_context += 1
                if r.get('decoder_ignored') is True or r.get('ignored') is True:
                    ignored_in_missed += 1
    if missed_in_context == 0:
        return 0.0
    rate = ignored_in_missed / missed_in_context
    return rate


def summarise(rows):
    """The single table the report needs."""
    if rows is None:
        rows = []
    summary = {}
    try:
        tr = term_recall(rows)
        summary['term_recall'] = tr
    except Exception:
        pass
    try:
        ipu = insertions_per_utterance(rows)
        summary['insertions_per_utterance'] = ipu
    except Exception:
        pass
    try:
        exposures = None
        for r in rows:
            if isinstance(r, dict) and 'exposures' in r:
                exposures = r['exposures']
                break
        ip100 = insertions_per_100_exposures(rows, exposures) if exposures is not None else insertions_per_100_exposures(rows, 0)
        summary['insertions_per_100_exposures'] = ip100
    except Exception:
        pass
    try:
        dir_rate = decoder_ignore_rate(rows)
        summary['decoder_ignore_rate'] = dir_rate
    except Exception:
        pass
    summary['rows_count'] = len(rows)
    return summary

