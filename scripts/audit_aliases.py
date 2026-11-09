"""CLI for the glossary alias / transliteration audit.

Example::

    python scripts/audit_aliases.py \
        --glossary data/glossary.json \
        --scripts data/scripts \
        --out runs/alias-audit.json

Exit status: 0 when no alias collision or cross-script dupe is found, 1 when
one is (the JSON is still written first), 2 on an input error. Stdout is ASCII
so it stays safe on a CP1252 console; the JSON artifact is UTF-8.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lexiforge.score.alias_audit import audit_glossary  # noqa: E402
from lexiforge.score.match import load_glossary  # noqa: E402


def _summary_line(result: dict) -> str:
    summary = result["summary"]
    return (
        f"alias audit: {summary['n_terms']} terms | "
        f"collisions {summary['n_collisions']} | "
        f"missing spoken forms {summary['n_missing_spoken_forms']} | "
        f"cross-script dupes {summary['n_cross_script_dupes']} | "
        f"proposals {summary['n_proposed_aliases']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit glossary aliases and transliterations (read-only)"
    )
    parser.add_argument("--glossary", default="data/glossary.json", help="Glossary JSON path")
    parser.add_argument(
        "--scripts",
        default=None,
        help="Committed scripts directory for usage-driven spoken-form gaps",
    )
    parser.add_argument("--out", default=None, help="Write the audit JSON to this path")
    args = parser.parse_args(argv)

    try:
        glossary = load_glossary(args.glossary)
        result = audit_glossary(
            glossary,
            scripts_dir=Path(args.scripts) if args.scripts else None,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(_summary_line(result))
    print("result: OK" if result["summary"]["ok"] else "result: FAIL (duplicate alias keys)")
    return 0 if result["summary"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
