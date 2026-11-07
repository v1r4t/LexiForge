"""Glossary coverage audit."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def audit_coverage(
    glossary_path: str | Path = "data/glossary.json",
    scripts_dir: str | Path = "data/scripts",
) -> dict[str, Any]:
    glossary_path = Path(glossary_path)
    scripts_dir = Path(scripts_dir)

    if not glossary_path.exists():
        raise FileNotFoundError(f"Glossary not found: {glossary_path}")

    try:
        with glossary_path.open("r", encoding="utf-8") as f:
            glossary = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed glossary {glossary_path}: {e}") from e

    if not isinstance(glossary, list):
        raise ValueError("Glossary must be a list of term entries")

    # Collect all glossary term IDs
    glossary_term_ids = set()
    for entry in glossary:
        if isinstance(entry, dict):
            term_id = entry.get("term_id") or entry.get("id")
            if term_id is not None:
                glossary_term_ids.add(str(term_id))
        elif isinstance(entry, str):
            glossary_term_ids.add(entry)

    total_terms = len(glossary_term_ids) if glossary_term_ids else len(glossary)

    # Scan scripts
    used_term_ids: set[str] = set()
    per_script: dict[str, Any] = {}

    if not scripts_dir.exists():
        raise FileNotFoundError(f"Scripts directory not found: {scripts_dir}")

    # Look for all json files in scripts_dir
    script_files = sorted([p for p in scripts_dir.iterdir() if p.is_file() and p.suffix == ".json"])
    if not script_files:
        # Maybe empty is an issue? Let us see - but be clear
        pass

    for script_path in script_files:
        try:
            with script_path.open("r", encoding="utf-8") as f:
                script_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed script {script_path}: {e}") from e
        except OSError as e:
            raise ValueError(f"Error reading script {script_path}: {e}") from e

        script_used: set[str] = set()

        # Check turns for glossary_terms
        turns = script_data.get("turns") or []
        if isinstance(turns, list):
            for turn in turns:
                if isinstance(turn, dict):
                    glossary_terms = turn.get("glossary_terms") or []
                    if isinstance(glossary_terms, (list, set, tuple)):
                        for tid in glossary_terms:
                            if tid is None:
                                continue
                            tid_str = str(tid)
                            # Do not treat oov as glossary terms - but oov is separate; glossary_terms are different
                            script_used.add(tid_str)
                            used_term_ids.add(tid_str)

        # Check expected_real and expected_fictional
        for key in ("expected_real", "expected_fictional"):
            arr = script_data.get(key) or []
            if isinstance(arr, (list, set, tuple)):
                for tid in arr:
                    if tid is None:
                        continue
                    tid_str = str(tid)
                    script_used.add(tid_str)
                    used_term_ids.add(tid_str)

        # oov is explicitly not counted as glossary terms
        per_script[script_path.name] = {
            "used": len(script_used),
            "used_terms": sorted(list(script_used)),
        }

    # If glossary_term_ids is empty for some reason, fall back to used_term_ids count vs total_terms
    if glossary_term_ids:
        used_terms = len(used_term_ids & glossary_term_ids)
    else:
        used_terms = len(used_term_ids)

    unused_terms = total_terms - used_terms
    if total_terms == 0:
        fraction = 0.0
    else:
        fraction = used_terms / total_terms

    result = {
        "total_terms": total_terms,
        "used_terms": used_terms,
        "unused_terms": unused_terms,
        "fraction": fraction,
        "per_script": per_script,
    }
    return result


def render_ascii_summary(result: dict[str, Any]) -> str:
    lines = []
    lines.append("=" * 40)
    lines.append("GLOSSARY COVERAGE AUDIT")
    lines.append("=" * 40)
    lines.append(f"Total terms:   {result['total_terms']}")
    lines.append(f"Used terms:    {result['used_terms']}")
    lines.append(f"Unused terms:  {result['unused_terms']}")
    lines.append(f"Coverage:      {result['fraction']:.2%}")
    lines.append("-" * 40)
    lines.append("Per-script breakdown:")
    per_script = result.get("per_script") or {}
    for name in sorted(per_script.keys()):
        info = per_script[name]
        if isinstance(info, dict):
            count = info.get("used", 0)
        else:
            count = info
        lines.append(f"  {name}: {count} terms")
    lines.append("=" * 40)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Audit glossary coverage against committed scripts")
    parser.add_argument("--glossary", default="data/glossary.json", help="Path to glossary.json")
    parser.add_argument("--scripts-dir", default="data/scripts", help="Path to scripts directory")
    args = parser.parse_args(argv)

    try:
        result = audit_coverage(args.glossary, args.scripts_dir)
        print(render_ascii_summary(result))
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
