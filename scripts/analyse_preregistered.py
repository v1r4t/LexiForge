#!/usr/bin/env python3
"""Run the pre-registered H1/H2 analysis on per-call aggregates (design §6).

Input is a JSON object mapping arm name to per-call rows, in the shape written
by ``scripts/run_keyterm_pilot.py``::

    {
      "baseline": [{"call_id": "c01",
                    "real_recall": {"num": 9, "den": 10},
                    "insertions_per_utterance": {"num": 0, "den": 5}}],
      "mismatched-200": [...],
      "oracle-200": [...]
    }

The output is the complete analysis object: two directional permutation tests,
Holm over exactly those two tests, the positive-control CI (no p-value), the
observed-sample MDE, and the claim-ladder rung. No planned sample size is
substituted for an observed one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lexiforge.analysis.preregistered import analyse_h1_h2  # noqa: E402

__all__ = ["main"]


def _load_arms(path: str | Path) -> Mapping[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("per-call input must be a JSON object keyed by arm name")
    for wrapper in ("per_call_by_arm", "arms"):
        nested = data.get(wrapper)
        if isinstance(nested, Mapping):
            return nested
    return data


def _write_json(result: Mapping[str, Any], out_path: str | Path) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _summary(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "n_calls": result.get("n_calls"),
        "h1": result["h1"]["decision"],
        "h2": result["h2"]["decision"],
        "holm": result["holm"]["rejected"],
        "positive_control": result["positive_control"].get("passed"),
        "claim_ladder": result.get("claim_ladder"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("per_call", help="JSON mapping arm -> per-call rows")
    parser.add_argument("--out", default="runs/preregistered.json")
    parser.add_argument("--cluster-key", default="call_id")
    parser.add_argument("--n-permutations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    arms = _load_arms(args.per_call)
    result = analyse_h1_h2(
        arms,
        cluster_key=args.cluster_key,
        n_permutations=args.n_permutations,
        seed=args.seed,
    )
    path = _write_json(result, args.out)
    print(json.dumps({"out": str(path), **_summary(result)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
