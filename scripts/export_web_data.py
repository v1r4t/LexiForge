"""Export dashboard JSON from measured transcripts and references.

This is the only supported way to put numbers in front of the dashboard. It
reads the scored artefacts the harness already produces and writes
``web/data/{calls,transcripts,terms,results}.json``; ``web/data/sample/`` is a
hand-written placeholder that this script replaces.

Input layout (all optional except transcripts):

- ``<transcripts_dir>/<call_id>/<condition>/<file>.json`` written by the
  runner, each ``{"text": "<hypothesis>"}``. A flat
  ``<transcripts_dir>/<condition>__<call_id>__<file>.json`` is also accepted.
- ``<refs_dir>/<file>.txt`` or ``.json`` reference text, keyed by file stem.
- ``<out_dir>/../..`` call metadata from ``data/assignment.json``.

Token statuses are computed with the frozen matcher
(:func:`lexiforge.score.match.find_spans`) plus a token alignment against the
reference, so the dashboard colours mean the same thing as the scored metrics:

- ``same``       aligned and recognised
- ``missed``     reference term absent from the hypothesis
- ``recovered``  reference term present in the hypothesis
- ``inserted``   hypothesis glossary span with no matching reference term

Usage::

    python scripts/export_web_data.py --transcripts transcripts --refs refs --out web/data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexiforge.privacy import redact_object  # noqa: E402
from lexiforge.score.match import find_spans, load_glossary, score_file  # noqa: E402

CONDITION_ORDER = (
    "baseline",
    "mismatched-200",
    "static-head-200",
    "oracle-minimal",
    "oracle-200",
    "random-200",
    "adaptive-200",
    "dilution",
    "near-miss",
)

STATUS_FROM_PAIR = {
    "hit": ("same", "recovered"),   # baseline, with-context
    "miss": ("missed", "missed"),
    "insertion": ("inserted", "inserted"),
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _hypothesis_text(path: Path) -> str:
    if path.suffix == ".json":
        payload = _read_json(path)
        if isinstance(payload, dict):
            for key in ("text", "transcript", "hypothesis"):
                if isinstance(payload.get(key), str):
                    return payload[key]
        if isinstance(payload, str):
            return payload
        return ""
    return path.read_text(encoding="utf-8-sig")


def _reference_text(path: Path) -> str:
    if path.suffix == ".json":
        payload = _read_json(path)
        if isinstance(payload, dict):
            for key in ("text", "reference", "transcript"):
                if isinstance(payload.get(key), str):
                    return payload[key]
        return ""
    return path.read_text(encoding="utf-8-sig")


def _collect_transcripts(transcripts_dir: Path) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Return ``{call_id: {condition: {file_stem: hypothesis}}}``."""
    out: Dict[str, Dict[str, Dict[str, str]]] = {}
    for path in sorted(transcripts_dir.rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".txt"):
            continue
        rel = path.relative_to(transcripts_dir)
        parts = rel.parts
        if len(parts) >= 3:
            call_id, condition = parts[0], parts[1]
        elif len(parts) == 1 and "__" in path.stem:
            condition, call_id, file_stem = path.stem.split("__", 2)
            out.setdefault(call_id, {}).setdefault(condition, {})[file_stem] = _hypothesis_text(path)
            continue
        else:
            continue
        out.setdefault(call_id, {}).setdefault(condition, {})[path.stem] = _hypothesis_text(path)
    return out


def _collect_refs(refs_dir: Path) -> Dict[str, str]:
    refs: Dict[str, str] = {}
    if not refs_dir.exists():
        return refs
    for path in sorted(refs_dir.rglob("*")):
        if path.is_file() and path.suffix in (".json", ".txt"):
            refs[path.stem] = _reference_text(path)
    return refs


def _term_recall(reference: str, hypothesis: str, glossary) -> Tuple[int, int]:
    """(hits, reference occurrences) from the frozen per-file scorer."""
    scored = score_file(reference, hypothesis, glossary)
    return int(scored["hits"]), int(scored["n_reference_occurrences"])


def _tokens(reference: str, hypothesis: str, glossary) -> List[Dict[str, str]]:
    """Colour hypothesis tokens from the frozen matcher.

    A glossary span in the hypothesis is ``recovered`` when the reference also
    carries that term, otherwise ``inserted``. Everything else is ``same``.
    Missed reference terms have no hypothesis text, so they are reported
    separately by :func:`_missed_terms` rather than invented here.
    """
    if not hypothesis:
        return []

    reference_ids = {span["term_id"] for span in find_spans(reference, glossary)}
    hyp_spans = find_spans(hypothesis, glossary)

    tokens: List[Dict[str, str]] = []
    cursor = 0
    for span in sorted(hyp_spans, key=lambda s: s["start"]):
        for word in hypothesis[cursor : span["start"]].split():
            tokens.append({"text": word, "status": "same"})
        status = "recovered" if span["term_id"] in reference_ids else "inserted"
        for word in span["surface"].split():
            tokens.append({"text": word, "status": status})
        cursor = span["end"]
    for word in hypothesis[cursor:].split():
        tokens.append({"text": word, "status": "same"})
    return tokens


def _missed_terms(reference: str, hypothesis: str, glossary) -> List[str]:
    """Reference term surfaces absent from the hypothesis."""
    hyp_ids = {span["term_id"] for span in find_spans(hypothesis, glossary)}
    seen: set = set()
    missed: List[str] = []
    for span in find_spans(reference, glossary):
        if span["term_id"] in hyp_ids:
            continue
        surface = span["surface"]
        if surface in seen:
            continue
        seen.add(surface)
        missed.append(surface)
    return missed


def _calls_metadata(assignment_path: Path) -> Dict[str, Dict[str, Any]]:
    if not assignment_path.exists():
        return {}
    payload = _read_json(assignment_path)
    return payload if isinstance(payload, dict) else {}


def _results_payload(call_scores: Dict[str, Dict[str, Dict[str, float]]]) -> Dict[str, Any]:
    """Aggregate per-call recall into contrasts the dashboard can render.

    This computes descriptive paired differences only. Inference stays in
    ``lexiforge.analysis.inference``; the dashboard must not invent p-values.
    """
    conditions = sorted(
        {condition for per_call in call_scores.values() for condition in per_call}
    )
    contrasts: List[Dict[str, Any]] = []
    baseline_recall = [
        call_scores[call].get("baseline", {}).get("term_recall")
        for call in sorted(call_scores)
        if call_scores[call].get("baseline")
    ]
    baseline_mean = (
        sum(v for v in baseline_recall if v is not None) / len(baseline_recall)
        if baseline_recall
        else 0.0
    )
    for condition in conditions:
        if condition == "baseline":
            continue
        deltas = []
        for call in sorted(call_scores):
            base = call_scores[call].get("baseline", {}).get("term_recall")
            other = call_scores[call].get(condition, {}).get("term_recall")
            if base is not None and other is not None:
                deltas.append(other - base)
        if not deltas:
            continue
        delta = sum(deltas) / len(deltas)
        contrasts.append(
            {
                "name": f"{condition} vs baseline (real-term recall)",
                "kind": "exploratory" if condition not in ("mismatched-200",) else "h1",
                "unit": "pp",
                "delta_pp": round(delta * 100.0, 3),
                "n_calls": len(deltas),
                "verdict": "descriptive",
            }
        )
    return {
        "source": "measured",
        "is_sample": False,
        "contrasts": contrasts,
        "control": {"baseline_recall": round(baseline_mean, 6)},
        "note": "Descriptive paired differences. Run lexiforge.analysis.inference for p-values.",
    }


def export(
    transcripts_dir: Path,
    refs_dir: Path,
    out_dir: Path,
    *,
    glossary_path: Path = Path("data/glossary.json"),
    assignment_path: Path = Path("data/assignment.json"),
    redact: bool = True,
) -> List[Path]:
    """Write dashboard JSON; returns the written paths.

    ``redact`` (default on) masks phone numbers, card/Aadhaar/account numbers
    and e-mail addresses in every string that reaches ``out_dir``. Scoring runs
    on the unredacted text, so masking never changes a recall figure.
    """
    transcripts_dir = Path(transcripts_dir)
    refs_dir = Path(refs_dir)
    out_dir = Path(out_dir)

    if not transcripts_dir.exists():
        raise FileNotFoundError(f"transcripts directory not found: {transcripts_dir}")

    glossary = load_glossary(glossary_path) if Path(glossary_path).exists() else []
    refs = _collect_refs(refs_dir)
    by_call = _collect_transcripts(transcripts_dir)
    assignment = _calls_metadata(Path(assignment_path))

    if not by_call:
        raise ValueError(f"no transcripts found under {transcripts_dir}")
    if not refs:
        raise ValueError(
            f"no references found under {refs_dir}; cannot colour tokens without references"
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    calls: List[Dict[str, Any]] = []
    transcripts: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
    terms: Dict[str, Any] = {}
    call_scores: Dict[str, Dict[str, Dict[str, float]]] = {}
    statuses_seen: Dict[str, set] = {}

    for call_id in sorted(by_call):
        meta = assignment.get(call_id, {}) if isinstance(assignment, dict) else {}
        calls.append(
            {
                "call_id": call_id,
                "call_type": meta.get("call_type") or meta.get("type") or "unknown",
                "duration_s": float(meta.get("duration_s") or 0.0),
                "has_audio": bool(meta.get("has_audio", True)),
                "n_conditions": len(by_call[call_id]),
            }
        )

        missed_by_condition: Dict[str, List[str]] = {}
        for condition, files in by_call[call_id].items():
            tokens: List[Dict[str, str]] = []
            missed: List[str] = []
            hits = refs_n = 0
            for stem, hypothesis in sorted(files.items()):
                reference = refs.get(stem, "")
                if not reference:
                    continue
                tokens.extend(_tokens(reference, hypothesis, glossary))
                missed.extend(_missed_terms(reference, hypothesis, glossary))
                h, n = _term_recall(reference, hypothesis, glossary)
                hits += h
                refs_n += n
            transcripts.setdefault(call_id, {})[condition] = tokens
            missed_by_condition[condition] = missed
            statuses_seen[condition] = {
                token["status"] for token in tokens
            } | statuses_seen.get(condition, set())
            if refs_n:
                call_scores.setdefault(call_id, {})[condition] = {
                    "term_recall": hits / refs_n                }

        meta_terms = meta.get("terms") if isinstance(meta, dict) else None
        terms[call_id] = {
            "selected": (meta_terms or {}).get("selected", []) if isinstance(meta_terms, dict) else [],
            "left_out": (meta_terms or {}).get("left_out", []) if isinstance(meta_terms, dict) else [],
            "missed_by_condition": missed_by_condition,
        }

    written: List[Path] = []

    def write(name: str, payload: Any) -> None:
        path = out_dir / name
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written.append(path)

    results_payload = _results_payload(call_scores)
    config_payload = {
        "mode": "precomputed",
        "data_source": "measured",
        "note": "Generated by scripts/export_web_data.py from scored transcripts.",
        "redacted": redact,
    }

    if redact:
        tokens_before = sum(len(v) for conds in transcripts.values() for v in conds.values())
        calls, _ = redact_object(calls)
        transcripts, masked = redact_object(transcripts)
        terms, terms_masked = redact_object(terms)
        for key, count in terms_masked.items():
            masked[key] = masked.get(key, 0) + count
        config_payload["redaction_counts"] = masked
        config_payload["tokens_scanned"] = tokens_before

    write("calls.json", calls)
    write("transcripts.json", transcripts)
    write("terms.json", terms)
    write("results.json", results_payload)
    write("demo_config.json", config_payload)
    return written


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcripts", default="transcripts", type=Path)
    parser.add_argument("--refs", default="refs", type=Path)
    parser.add_argument("--out", default="web/data", type=Path)
    parser.add_argument("--glossary", default="data/glossary.json", type=Path)
    parser.add_argument("--assignment", default="data/assignment.json", type=Path)
    parser.add_argument(
        "--no-redact",
        dest="redact",
        action="store_false",
        help="Emit raw transcript text (phone/card/Aadhaar/account/email unmasked)",
    )
    parser.set_defaults(redact=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        written = export(
            args.transcripts,
            args.refs,
            args.out,
            glossary_path=args.glossary,
            assignment_path=args.assignment,
            redact=args.redact,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    for path in written:
        print(f"OK   {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
