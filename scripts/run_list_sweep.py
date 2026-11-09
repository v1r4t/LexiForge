"""List-size sweep runner for the keyterm budget (design §2, P20).

Builds one keyterm list per ``(call, budget, arm)`` for a range of context
sizes (5, 50, 200 by default) so a dose-response curve can be read off the
same calls. Each cell is built independently: a glossary too small for a
budget records ``status="underfilled"`` with the requested budget intact
instead of silently shrinking the arm. The sweep is descriptive only -- the
small budgets carry no p-values.

Dry run is the default and performs zero network I/O. ``execute=True`` creates
exactly one job per filled cell (and therefore requires ``GNANI_API_KEY``)
using the same batch lifecycle as :mod:`scripts.run_keyterm_pilot`.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from lexiforge.canon import CANON_VERSION
from lexiforge.contexts.arms import build_arms
from lexiforge.contexts.build import MAX_KEYTERMS, assert_exact_budget

DEFAULT_BUDGETS = (5, 50, 200)
DEFAULT_ARMS = ("selected", "mismatched", "hard-negative")

# Short sweep arm name -> ``build_arms`` key. The builder always labels its
# lists ``-200`` even when the sweep asks for 5 or 50 slots.
_ARM_KEYS = {
    "selected": "selected-200",
    "mismatched": "mismatched-200",
    "hard-negative": "hard-negative-200",
    "static": "static-200",
}

_ROW_FIELDS = (
    "call_id",
    "call_type",
    "budget",
    "arm",
    "status",
    "n_terms",
    "terms",
    "error",
    "job_id",
    "job_status",
    "real_recall",
    "insertions_per_utterance",
    "wer",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_glossary(path: Path) -> list[dict]:
    data = _load_json(path)
    if isinstance(data, Mapping):
        data = data.get("terms") or data.get("glossary_terms") or []
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list of glossary entries.")
    return data


def _load_script(call_id: str) -> dict:
    path = Path("data/scripts") / f"{call_id}.json"
    if not path.is_file():
        return {}
    data = _load_json(path)
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return dict(data)


def _script_expected(script: Mapping[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ("expected_real", "expected_fictional"):
        values = script.get(key) or []
        if isinstance(values, str):
            values = [values]
        terms.extend(str(value) for value in values if str(value).strip())
    return terms


def _script_reference(script: Mapping[str, Any]) -> str:
    turns = script.get("turns")
    if not isinstance(turns, list):
        return ""
    parts = [
        str(turn.get("text")).strip()
        for turn in turns
        if isinstance(turn, Mapping) and str(turn.get("text") or "").strip()
    ]
    return " ".join(parts)


def _normalise_call(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        script = raw.get("script")
        script = dict(script) if isinstance(script, Mapping) else {}
        call_id = raw.get("call_id") or raw.get("id")
        if not call_id:
            raise ValueError("call mapping needs a call_id")
        call_type = raw.get("call_type") or script.get("call_type") or "general"
        expected = raw.get("expected_terms") or raw.get("expected")
        if not expected:
            expected = _script_expected(script)
        reference = raw.get("reference_text") or _script_reference(script)
        audio = raw.get("audio")
        hypothesis = raw.get("hypothesis") or f"call {call_id}"
        n_utterances = raw.get("n_utterances")
    elif isinstance(raw, (str, Path)):
        call_id = str(raw)
        script = _load_script(call_id)
        call_type = script.get("call_type") or "general"
        expected = _script_expected(script)
        reference = _script_reference(script)
        audio = None
        # The reference script must never feed the selector (circularity).
        hypothesis = f"call {call_id}"
        n_utterances = None
    else:
        raise TypeError(
            f"calls entries must be str or mappings, got {type(raw).__name__}"
        )

    if not isinstance(call_type, str) or not call_type.strip():
        call_type = "general"
    terms = [term for term in expected or [] if isinstance(term, str) and term.strip()]
    if n_utterances is None:
        turns = script.get("turns")
        n_utterances = len(turns) if isinstance(turns, list) and turns else 1

    return {
        "call_id": str(call_id),
        "call_type": call_type,
        "expected_terms": terms,
        "reference_text": str(reference or ""),
        "audio": str(audio) if audio else None,
        "hypothesis": str(hypothesis),
        "n_utterances": max(int(n_utterances), 1),
    }


def _normalise_calls(calls: Iterable[Any] | Mapping[str, Any] | str | Path) -> list[dict]:
    if isinstance(calls, (str, Path, Mapping)):
        calls = [calls]
    if isinstance(calls, (set, frozenset)):
        calls = sorted(calls, key=str)

    normalised: list[dict] = []
    seen: set[str] = set()
    for raw in calls:
        call = _normalise_call(raw)
        if call["call_id"] in seen:
            raise ValueError(f"duplicate call_id: {call['call_id']}")
        seen.add(call["call_id"])
        normalised.append(call)
    if not normalised:
        raise ValueError("at least one call is required")
    return normalised


def _normalise_budgets(budgets: Iterable[int] | int) -> list[int]:
    if isinstance(budgets, bool):
        raise ValueError("budgets must be ints, not bool")
    if isinstance(budgets, int):
        budgets = (budgets,)
    try:
        candidates = list(budgets)
    except TypeError as exc:
        raise ValueError(
            f"budgets must be iterable of ints, got {type(budgets).__name__}"
        ) from exc

    out: list[int] = []
    for budget in candidates:
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise ValueError(f"budget must be an int, got {type(budget).__name__}")
        if not 1 <= budget <= MAX_KEYTERMS:
            raise ValueError(
                f"budget must be between 1 and {MAX_KEYTERMS}, got {budget}"
            )
        if budget not in out:
            out.append(budget)
    if not out:
        raise ValueError("at least one budget is required")
    return out


def _normalise_arms(arms: Iterable[str] | str) -> list[tuple[str, str]]:
    if isinstance(arms, str):
        arms = (arms,)
    out: list[tuple[str, str]] = []
    for raw in arms:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"arm must be a non-empty str, got {raw!r}")
        key = raw.strip().lower().replace("_", "-")
        if key.endswith("-200"):
            key = key[:-4]
        full = _ARM_KEYS.get(key)
        if full is None:
            raise ValueError(
                f"unknown arm {raw!r}; expected one of "
                f"{', '.join(sorted(_ARM_KEYS))}"
            )
        if (key, full) not in out:
            out.append((key, full))
    if not out:
        raise ValueError("at least one arm is required")
    return out


def _build_cell(
    call: Mapping[str, Any],
    glossary: list[dict],
    budget: int,
    *,
    seed: int,
) -> tuple[dict[str, list[str]], str, set[str]]:
    """Build every arm for one (call, budget) cell, catching underfill.

    ``build_arms`` is all-or-nothing. When it raises, retry with an empty
    hard-negative builder: if that succeeds, the only unfillable arm was the
    hard-negative control, so the valid selected/mismatched lists are kept and
    only that arm is recorded underfilled.
    """
    try:
        built = build_arms(
            call["hypothesis"],
            glossary,
            call["call_type"],
            budget=budget,
            seed=seed,
            expected_terms=call["expected_terms"] or None,
        )
    except ValueError as exc:
        error = str(exc)
        try:
            built = build_arms(
                call["hypothesis"],
                glossary,
                call["call_type"],
                budget=budget,
                seed=seed,
                expected_terms=call["expected_terms"] or None,
                hard_negative_builder=lambda *args, **kwargs: [],
            )
        except (TypeError, ValueError):
            # A small glossary cannot fill the requested budget. Record the
            # cell as underfilled rather than lowering the budget or inventing
            # terms.
            return {}, error, set()
        return (
            {key: list(terms) for key, terms in built.items()},
            error,
            {"hard-negative-200"},
        )
    return {key: list(terms) for key, terms in built.items()}, "", set()


def _score(
    *,
    reference: str,
    hypothesis: str,
    glossary: list[dict],
    n_utterances: int,
) -> dict[str, Any]:
    from lexiforge.score.match import score_file_detail
    from lexiforge.score.metrics import term_recall, wer

    detail = score_file_detail(reference, hypothesis, glossary)
    recall = term_recall(detail["rows"], stratum="real")
    insertions = detail["insertions"]
    return {
        "real_recall": {
            "rate": recall["rate"],
            "numerator": recall["numerator"],
            "denominator": recall["denominator"],
        },
        "insertions_per_utterance": {
            "rate": insertions / n_utterances,
            "numerator": insertions,
            "denominator": n_utterances,
        },
        "wer": float(wer(reference, hypothesis)),
    }


def _resolve_client(client: Any) -> Any:
    if client is not None:
        return client
    if not os.environ.get("GNANI_API_KEY"):
        raise ValueError("API key is missing (GNANI_API_KEY).")
    from lexiforge.api.client import BatchClient

    return BatchClient()


def _audio_path(call: Mapping[str, Any], audio_dir: str | Path | None) -> Path:
    if call["audio"]:
        return Path(call["audio"])
    root = Path(audio_dir) if audio_dir else Path("data/audio")
    return root / f"{call['call_id']}.wav"


def _transcript_text(transcripts: Any) -> str:
    if not isinstance(transcripts, Mapping):
        return ""
    parts = [
        str(row.get("text") or "").strip()
        for _, row in sorted(transcripts.items(), key=lambda item: str(item[0]))
        if isinstance(row, Mapping)
    ]
    return " ".join(part for part in parts if part).strip()


def _execute_row(
    row: dict[str, Any],
    call: Mapping[str, Any],
    *,
    client: Any,
    glossary: list[dict],
    audio_dir: str | Path | None,
) -> None:
    audio = _audio_path(call, audio_dir)
    if not audio.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio}.")

    config: dict[str, Any] = {
        "model": "prisma-v3.0",
        "format": "transcribe",
        "language_code": "hi-IN,en-IN",
    }
    if row["terms"]:
        config["keyterms"] = list(row["terms"])

    job_id = client.create_job(config, [audio])
    client.start_job(job_id)
    status = client.wait(job_id)
    hypothesis = _transcript_text(client.fetch_all_transcripts(job_id))

    row["job_id"] = job_id
    row["job_status"] = status
    if call["reference_text"]:
        row["metrics"] = _score(
            reference=call["reference_text"],
            hypothesis=hypothesis,
            glossary=glossary,
            n_utterances=call["n_utterances"],
        )


def _dose_response(
    rows: list[dict[str, Any]],
    budgets: list[int],
    arms: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    response: list[dict[str, Any]] = []
    for budget in budgets:
        group = [row for row in rows if row["budget"] == budget]
        summary: dict[str, Any] = {
            "budget": budget,
            "n_lists": len(group),
            "n_filled": sum(row["status"] == "ok" for row in group),
            "n_underfilled": sum(row["status"] == "underfilled" for row in group),
            "mean_terms": (
                round(sum(row["n_terms"] for row in group) / len(group), 3)
                if group
                else 0.0
            ),
            "min_terms": min((row["n_terms"] for row in group), default=0),
            "max_terms": max((row["n_terms"] for row in group), default=0),
            "arms": {},
        }
        for arm, _ in arms:
            arm_rows = [row for row in group if row["arm"] == arm]
            arm_summary: dict[str, Any] = {
                "n_lists": len(arm_rows),
                "n_filled": sum(row["status"] == "ok" for row in arm_rows),
                "n_underfilled": sum(
                    row["status"] == "underfilled" for row in arm_rows
                ),
                "mean_terms": (
                    round(
                        sum(row["n_terms"] for row in arm_rows) / len(arm_rows), 3
                    )
                    if arm_rows
                    else 0.0
                ),
            }
            recalls = [
                row["metrics"]["real_recall"]["rate"]
                for row in arm_rows
                if row.get("metrics")
                and row["metrics"]["real_recall"]["rate"] is not None
            ]
            if recalls:
                arm_summary["mean_real_recall"] = round(
                    sum(recalls) / len(recalls), 6
                )
            summary["arms"][arm] = arm_summary
        response.append(summary)
    return response


def sweep(
    budgets: Iterable[int] | int = DEFAULT_BUDGETS,
    calls: Any = None,
    glossary: Any = None,
    *,
    seed: int = 0,
    arms: Iterable[str] | str = DEFAULT_ARMS,
    execute: bool = False,
    client: Any = None,
    audio_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build one keyterm list per ``(call, budget, arm)``.

    ``calls`` accepts call IDs (``data/scripts/<id>.json`` supplies the call
    type and expected terms), call mappings, or a mix. Each row records
    ``call_id``, ``budget``, ``arm``, ``status`` (``ok``/``underfilled``),
    ``n_terms`` and the ``terms`` list; ``dose_response`` aggregates term
    counts per budget and arm. ``execute=True`` decodes every filled cell once
    and adds descriptive metrics; a missing ``GNANI_API_KEY`` raises
    ``ValueError`` before any work is done.
    """
    if calls is None or glossary is None:
        raise TypeError("sweep() requires calls and glossary")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError(f"seed must be an int, got {type(seed).__name__}")

    normalised_budgets = _normalise_budgets(budgets)
    normalised_arms = _normalise_arms(arms)
    normalised_calls = _normalise_calls(calls)
    if isinstance(glossary, (str, bytes)):
        raise TypeError("glossary must be an iterable of dicts")
    entries = list(glossary)

    active_client = _resolve_client(client) if execute else None

    rows: list[dict[str, Any]] = []
    for call in normalised_calls:
        for budget in normalised_budgets:
            built, build_error, failed_arms = _build_cell(
                call, entries, budget, seed=seed
            )
            for arm, full_arm in normalised_arms:
                terms = list(built.get(full_arm, []))
                if full_arm in failed_arms:
                    # The probe list is not a valid hard-negative control.
                    terms = []
                if not built or full_arm in failed_arms:
                    status = "underfilled"
                    error = build_error
                else:
                    status = "ok"
                    error = ""
                    try:
                        assert_exact_budget(terms, budget, arm=arm)
                    except ValueError as exc:
                        status = "underfilled"
                        error = str(exc)

                row: dict[str, Any] = {
                    "call_id": call["call_id"],
                    "call_type": call["call_type"],
                    "budget": budget,
                    "arm": arm,
                    "status": status,
                    "n_terms": len(terms),
                    "terms": terms,
                    "error": error,
                }
                if execute and status == "ok":
                    _execute_row(
                        row,
                        call,
                        client=active_client,
                        glossary=entries,
                        audio_dir=audio_dir,
                    )
                rows.append(row)

    return {
        "rows": rows,
        "dose_response": _dose_response(rows, normalised_budgets, normalised_arms),
    }


def _csv_row(row: Mapping[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics") or {}
    recall = (metrics.get("real_recall") or {}).get("rate")
    insertions = (metrics.get("insertions_per_utterance") or {}).get("rate")
    return {
        "call_id": row["call_id"],
        "call_type": row["call_type"],
        "budget": row["budget"],
        "arm": row["arm"],
        "status": row["status"],
        "n_terms": row["n_terms"],
        "terms": json.dumps(row["terms"], ensure_ascii=False),
        "error": row.get("error") or "",
        "job_id": row.get("job_id") or "",
        "job_status": row.get("job_status") or "",
        "real_recall": "" if recall is None else recall,
        "insertions_per_utterance": "" if insertions is None else insertions,
        "wer": metrics.get("wer", ""),
    }


def _dose_fields(arms: list[tuple[str, str]]) -> list[str]:
    fields = [
        "budget",
        "n_lists",
        "n_filled",
        "n_underfilled",
        "mean_terms",
        "min_terms",
        "max_terms",
    ]
    for arm, _ in arms:
        fields.extend(
            [
                f"{arm}_n_filled",
                f"{arm}_n_underfilled",
                f"{arm}_mean_terms",
                f"{arm}_mean_real_recall",
            ]
        )
    return fields


def _dose_csv_row(summary: Mapping[str, Any], arms: list[tuple[str, str]]) -> dict[str, Any]:
    row: dict[str, Any] = {
        key: summary[key]
        for key in (
            "budget",
            "n_lists",
            "n_filled",
            "n_underfilled",
            "mean_terms",
            "min_terms",
            "max_terms",
        )
    }
    for arm, _ in arms:
        arm_summary = summary["arms"][arm]
        row[f"{arm}_n_filled"] = arm_summary["n_filled"]
        row[f"{arm}_n_underfilled"] = arm_summary["n_underfilled"]
        row[f"{arm}_mean_terms"] = arm_summary["mean_terms"]
        row[f"{arm}_mean_real_recall"] = arm_summary.get("mean_real_recall", "")
    return row


def _write_output(
    out_dir: Path,
    result: Mapping[str, Any],
    *,
    budgets: list[int],
    arms: list[tuple[str, str]],
    seed: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "canon_version": CANON_VERSION,
            "budgets": budgets,
            "arms": [arm for arm, _ in arms],
            "seed": seed,
        },
        "rows": result["rows"],
        "dose_response": result["dose_response"],
    }
    (out_dir / "sweep.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    with (out_dir / "sweep.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_ROW_FIELDS)
        writer.writeheader()
        for row in result["rows"]:
            writer.writerow(_csv_row(row))

    with (out_dir / "dose_response.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=_dose_fields(arms))
        writer.writeheader()
        for summary in result["dose_response"]:
            writer.writerow(_dose_csv_row(summary, arms))


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Sweep keyterm list sizes (dry-run by default)"
    )
    parser.add_argument(
        "--budgets", default="5,50,200", help="Comma-separated list sizes"
    )
    parser.add_argument(
        "--calls", default="c00", help="Comma-separated call IDs (data/scripts/*.json)"
    )
    parser.add_argument("--glossary", default="data/glossary.json")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--arms", default=",".join(DEFAULT_ARMS), help="Comma-separated arm names"
    )
    parser.add_argument("--out", default="runs/sweep", help="Output directory")
    parser.add_argument("--execute", action="store_true", help="Decode each cell")
    parser.add_argument(
        "--audio-dir", default=None, help="Directory holding <call_id>.wav"
    )
    args = parser.parse_args(argv)

    try:
        budgets = [int(item) for item in _csv_list(args.budgets)]
        calls = _csv_list(args.calls)
        arms = tuple(_csv_list(args.arms))
        normalised_arms = _normalise_arms(arms)
        glossary_path = Path(args.glossary)
        glossary = _load_glossary(glossary_path) if glossary_path.is_file() else []
        result = sweep(
            budgets,
            calls,
            glossary,
            seed=args.seed,
            arms=arms,
            execute=args.execute,
            audio_dir=args.audio_dir,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}")
        return 2

    out_dir = Path(args.out)
    _write_output(
        out_dir,
        result,
        budgets=budgets,
        arms=normalised_arms,
        seed=args.seed,
    )
    print(
        f"Wrote {len(result['rows'])} rows to "
        f"{out_dir / 'sweep.json'} and {out_dir / 'sweep.csv'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
