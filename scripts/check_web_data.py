#!/usr/bin/env python3
"""Quick sanity check for exported web dashboard data.

Validates schema, flags sample vs measured, checks redaction metadata,
and reports basic stats. Exits 0 if everything looks consistent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List


def _load(p: Path) -> Any:
    with p.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def check(data_dir: Path) -> int:
    ok = True
    required = ["calls.json", "transcripts.json", "terms.json", "results.json", "demo_config.json"]
    for name in required:
        if not (data_dir / name).exists():
            print(f"FAIL missing {name} in {data_dir}")
            ok = False
    if not ok:
        return 1

    calls = _load(data_dir / "calls.json")
    transcripts = _load(data_dir / "transcripts.json")
    terms = _load(data_dir / "terms.json")
    results = _load(data_dir / "results.json")
    config = _load(data_dir / "demo_config.json")

    if not isinstance(calls, list):
        print("FAIL calls.json must be a list")
        ok = False
    if not isinstance(transcripts, dict):
        print("FAIL transcripts.json must be an object")
        ok = False
    if not isinstance(terms, dict):
        print("FAIL terms.json must be an object")
        ok = False
    if not isinstance(results, dict):
        print("FAIL results.json must be an object")
        ok = False
    if not isinstance(config, dict):
        print("FAIL demo_config.json must be an object")
        ok = False

    if not ok:
        return 1

    is_sample = bool(results.get("is_sample") or config.get("data_source") == "illustrative_sample")
    print(f"data_dir={data_dir}")
    print(f"source={config.get('data_source')} is_sample={is_sample} mode={config.get('mode')}")
    if config.get("redacted"):
        rc = config.get("redaction_counts") or {}
        print(f"redacted=true tokens_scanned={config.get('tokens_scanned')} counts={rc}")
    else:
        print("redacted=false")

    print(f"calls={len(calls)} transcripts_keys={len(transcripts)} terms_keys={len(terms)}")
    contrasts = results.get("contrasts") or []
    if isinstance(contrasts, list):
        print(f"contrasts={len(contrasts)}")
        for c in contrasts[:5]:
            if isinstance(c, dict):
                name = c.get("name", "?")
                d = c.get("delta_pp")
                k = c.get("kind", "?")
                v = c.get("verdict", "?")
                print(f"  - {k}: {name} delta_pp={d} verdict={v}")
    else:
        print("FAIL results.contrasts must be a list")
        ok = False

    # spot check: calls have required fields
    bad = 0
    for c in calls[:10]:
        if not isinstance(c, dict) or not c.get("call_id"):
            bad += 1
    if bad:
        print(f"WARN {bad} calls missing call_id in first 10")
    else:
        print("calls: ok")

    if is_sample and not all((isinstance(c, dict) and c.get("verdict") == "sample") for c in contrasts if isinstance(c, dict)):
        print("WARN sample results should mark contrasts as sample")
    if not is_sample and config.get("data_source") != "measured":
        print("WARN measured-like results but data_source not 'measured'")

    return 0 if ok else 1


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data_dir", type=Path, nargs="?", default=Path("web/data"))
    args = p.parse_args(argv)
    return check(args.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
