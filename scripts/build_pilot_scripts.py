"""Build pilot call scripts from data/assignment.json and the committed glossary.

The committed scripts were generated from a different glossary version, so many
of their term IDs do not exist. This generator makes four internally consistent
calls (c00-c03) from assignment keys 0-3.

Usage:
  python scripts/build_pilot_scripts.py --calls c00,c01,c02,c03 --write
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

__all__ = ["build_scripts", "main"]

DEFAULT_CALLS = ("c00", "c01", "c02", "c03")

_MISMATCH = {
    "mandate_fail": "upi_failed",
    "kyc_reverify": "fraud_dispute",
    "upi_failed": "card_block",
    "card_block": "loan_foreclosure",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _estimate(text: str) -> int:
    return max(3, round(len(text.split()) / 2.2 + 1.5))


def _turn(idx: int, speaker: str, text: str, term_ids: list[str]) -> dict:
    return {
        "idx": idx,
        "speaker": speaker,
        "text": text,
        "est_s": _estimate(text),
        "glossary_terms": term_ids,
    }


def _build_one(
    call_id: str,
    assignment: Mapping[str, Any],
    glossary: Mapping[str, Mapping[str, Any]],
) -> dict:
    call_type = str(assignment.get("call_type") or "general")
    real_ids = [tid for tid in assignment.get("real", []) if tid in glossary]
    fict_ids = [tid for tid in assignment.get("fictional", []) if tid in glossary]
    if len(real_ids) < 4 or len(fict_ids) < 3:
        raise ValueError(f"{call_id}: assignment needs >=4 real and >=3 fictional terms")

    def surface(tid: str) -> str:
        return str(glossary[tid]["canonical"])

    real = [surface(t) for t in real_ids]
    fict = [surface(t) for t in fict_ids]
    if len(real) >= 5:
        # Four fictional terms plus five real terms exceed the two-per-turn
        # budget; keep the first three fictional terms for the pilot script.
        fict_ids = fict_ids[:3]
        fict = [surface(t) for t in fict_ids]

    t1 = f"Namaste ji, main aapke {call_type.replace('_', ' ')} ke baare mein baat karne call kiya hu."
    t2 = f"Ji sir, mera {real[0]} aur {real[1]} se related sawaal hai."
    t3 = f"Theek hai, {real[2]} aur {real[3]} check karke batata hu."

    turns = [
        _turn(1, "AGT", t1, []),
        _turn(2, "CUS", t2, real_ids[0:2]),
        _turn(3, "AGT", t3, real_ids[2:4]),
    ]
    if len(real) >= 5:
        t4 = f"Ji, {real[4]} ke saath {fict[0]} bhi dekh lijiye."
        turns.append(_turn(4, "CUS", t4, [real_ids[4], fict_ids[0]]))
        t5 = f"Bilkul, {fict[1]} aur {fict[2]} verify karke update deta hu."
        turns.append(_turn(5, "AGT", t5, fict_ids[1:3]))
    else:
        t4 = f"Ji, {fict[0]} aur {fict[1]} bhi dekh lijiye."
        turns.append(_turn(4, "CUS", t4, fict_ids[0:2]))
        if len(fict) >= 4:
            t5 = f"Bilkul, {fict[2]} aur {fict[3]} verify karke account update deta hu."
            t5_ids = fict_ids[2:4]
        else:
            t5 = f"Bilkul, {fict[2]} verify karke account update deta hu."
            t5_ids = [fict_ids[2]]
        turns.append(_turn(5, "AGT", t5, t5_ids))

    return {
        "call_id": call_id,
        "call_type": call_type,
        "speakers": ["SP-A", "SP-B"],
        "mismatched_domain": _MISMATCH.get(call_type, "upi_failed"),
        "channel": "phone",
        "language": "hi-en",
        "turns": turns,
        "expected_real": real_ids,
        "expected_fictional": fict_ids,
        "oov": [],
        "zero_turns": [1],
    }


def build_scripts(
    calls: tuple[str, ...] = DEFAULT_CALLS,
    *,
    assignment_path: str | Path = "data/assignment.json",
    glossary_path: str | Path = "data/glossary.json",
) -> dict[str, dict]:
    assignment = _load(Path(assignment_path))
    glossary_entries = _load(Path(glossary_path))
    glossary = {entry["term_id"]: entry for entry in glossary_entries}
    result = {}
    for index, call_id in enumerate(calls):
        key = str(index)
        if key not in assignment:
            raise KeyError(f"assignment has no key {key} for {call_id}")
        result[call_id] = _build_one(call_id, assignment[key], glossary)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build consistent pilot scripts")
    parser.add_argument("--calls", default=",".join(DEFAULT_CALLS))
    parser.add_argument("--assignment", default="data/assignment.json")
    parser.add_argument("--glossary", default="data/glossary.json")
    parser.add_argument("--out-dir", default="data/scripts")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    calls = tuple(c.strip() for c in args.calls.split(",") if c.strip())
    scripts = build_scripts(
        calls, assignment_path=args.assignment, glossary_path=args.glossary
    )
    if args.write:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for call_id, script in scripts.items():
            (out / f"{call_id}.json").write_text(
                json.dumps(script, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"wrote {out / (call_id + '.json')}")
    else:
        for call_id, script in scripts.items():
            print(
                f"{call_id}: {len(script['turns'])} turns, "
                f"real={len(script['expected_real'])}, fictional={len(script['expected_fictional'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
