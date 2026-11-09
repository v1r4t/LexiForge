#!/usr/bin/env python3
"""Read-only data-consistency checks for committed study artifacts.

Implements task P23 (Phase 6 engineering hardening; ``docs/design.md`` §11):
every script term id must resolve against ``data/glossary.json``, ``core200``
must match its ``.sha256`` sidecar, assignment keys must cover c00-c19, script
call ids must be unique, README-linked docs and runbook-named Makefile targets
must exist, and the matcher gold set must be internally consistent.

The checker never writes and never touches the network. It is deliberately
tolerant of artifacts still being regenerated: P08 owns ``c04-c19`` scripts and
P14 owns the manifest schema, so unresolved ids outside the four pilot calls
are warnings until that work lands.

CLI: ``python scripts/check_data_consistency.py [--json] [root]``; exits 1 on
any error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

CALL_IDS = tuple(f"c{i:02d}" for i in range(20))
# P08 regenerates these; until it lands they are reported as pending, not as
# failures. The four pilot calls (c00-c03) are frozen and always enforced.
STRICT_CALLS = frozenset({"c00", "c01", "c02", "c03"})
GOLD_TARGET_CASES = 45

_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_MAKE_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):", re.MULTILINE)
_PHONY = re.compile(r"^\.PHONY\s*:\s*(.+)$", re.MULTILINE)
_RUNBOOK_TARGETS = (
    re.compile(r"`make ([A-Za-z0-9_.-]+)`"),
    re.compile(r"^\s*\$?\s*make ([A-Za-z0-9_.-]+)\s*$", re.MULTILINE),
)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _check_glossary(root: Path, errors: list[str], warnings: list[str]) -> set[str]:
    path = root / "data" / "glossary.json"
    if not path.exists():
        errors.append("glossary: missing data/glossary.json")
        return set()
    try:
        entries = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"glossary: unreadable data/glossary.json: {exc}")
        return set()
    if not isinstance(entries, list) or not entries:
        errors.append("glossary: data/glossary.json must be a non-empty list")
        return set()

    term_ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"glossary: entry {index} is not an object")
            continue
        term_id = entry.get("term_id")
        if not isinstance(term_id, str) or not term_id.strip():
            errors.append(f"glossary: entry {index} has no term_id")
        elif term_id in term_ids:
            errors.append(f"glossary: duplicate term_id {term_id}")
        else:
            term_ids.add(term_id)
    return term_ids


def _script_term_ids(script: dict[str, Any]) -> set[str]:
    term_ids: set[str] = set()
    turns = script.get("turns")
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            terms = turn.get("glossary_terms") or []
            if isinstance(terms, list):
                term_ids.update(str(term) for term in terms if term)
    for key in ("expected_real", "expected_fictional"):
        values = script.get(key) or []
        if isinstance(values, list):
            term_ids.update(str(term) for term in values if term)
    return term_ids


def _check_scripts(
    root: Path, glossary_ids: set[str], errors: list[str], warnings: list[str]
) -> None:
    directory = root / "data" / "scripts"
    if not directory.is_dir():
        warnings.append("scripts: data/scripts is missing (P08 regeneration pending)")
        return
    files = sorted(directory.glob("*.json"))
    if not files:
        warnings.append("scripts: data/scripts has no call scripts")
        return

    owners: dict[str, str] = {}
    for path in files:
        try:
            script = _load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"scripts: {path.name}: unreadable JSON: {exc}")
            continue
        if not isinstance(script, dict):
            errors.append(f"scripts: {path.name}: expected a JSON object")
            continue

        call_id = str(script.get("call_id") or path.stem)
        if call_id in owners:
            errors.append(
                f"scripts: duplicate call_id {call_id} in "
                f"{owners[call_id]} and {path.name}"
            )
        else:
            owners[call_id] = path.name
        if call_id != path.stem:
            warnings.append(
                f"scripts: {path.name}: call_id {call_id} does not match filename"
            )

        unresolved = sorted(_script_term_ids(script) - glossary_ids)
        if not unresolved:
            continue
        if call_id in STRICT_CALLS:
            for term_id in unresolved:
                errors.append(
                    f"scripts: {path.name}: term id {term_id} is not in the glossary"
                )
        else:
            warnings.append(
                f"scripts: {path.name}: {len(unresolved)} term id(s) unresolved; "
                "P08 regeneration pending"
            )

    missing = [call_id for call_id in CALL_IDS if call_id not in owners]
    if missing:
        warnings.append(
            "scripts: missing call scripts "
            f"{', '.join(missing)} (P08 regeneration pending)"
        )


def _check_assignment(
    root: Path, glossary_ids: set[str], errors: list[str], warnings: list[str]
) -> None:
    path = root / "data" / "assignment.json"
    if not path.exists():
        errors.append("assignment: missing data/assignment.json")
        return
    try:
        assignment = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"assignment: unreadable data/assignment.json: {exc}")
        return
    if not isinstance(assignment, dict):
        errors.append("assignment: data/assignment.json must be an object")
        return

    expected_keys = {str(i) for i in range(20)}
    missing = sorted(expected_keys - set(assignment))
    if missing:
        errors.append(f"assignment: missing call keys {', '.join(missing)}")
    extra = sorted(set(assignment) - expected_keys)
    if extra:
        warnings.append(f"assignment: unexpected call keys {', '.join(extra)}")

    for key in sorted(assignment):
        entry = assignment[key]
        if not isinstance(entry, dict):
            errors.append(f"assignment: key {key} is not an object")
            continue
        for field in ("real", "fictional"):
            values = entry.get(field)
            if not isinstance(values, list):
                errors.append(f"assignment: key {key} has no {field} list")
                continue
            for term_id in values:
                if str(term_id) not in glossary_ids:
                    errors.append(
                        f"assignment: key {key} references unknown term id {term_id}"
                    )


def _normalised_sha256(path: Path) -> str:
    # Windows checkouts rewrite LF to CRLF; the committed sidecar hashes LF.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _check_core200(root: Path, errors: list[str], warnings: list[str]) -> None:
    path = root / "data" / "core200.json"
    sha_path = root / "data" / "core200.json.sha256"
    if not path.exists():
        errors.append("core200: missing data/core200.json")
        return
    if not sha_path.exists():
        errors.append("core200: missing data/core200.json.sha256")
    else:
        expected = sha_path.read_text(encoding="utf-8").split()
        actual = _normalised_sha256(path)
        if not expected or expected[0].lower() != actual:
            recorded = expected[0] if expected else "<empty>"
            errors.append(
                f"core200: sha256 mismatch (recorded {recorded}, actual {actual})"
            )

    try:
        core = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"core200: unreadable data/core200.json: {exc}")
        return
    term_ids = core.get("term_ids") if isinstance(core, dict) else None
    if not isinstance(term_ids, list):
        errors.append("core200: term_ids must be a list")
        return
    if len(term_ids) != len(set(term_ids)):
        errors.append("core200: term_ids contains duplicates")
    if len(term_ids) != 200:
        warnings.append(f"core200: expected 200 term ids, found {len(term_ids)}")


def _check_readme(root: Path, errors: list[str], warnings: list[str]) -> None:
    path = root / "README.md"
    if not path.exists():
        errors.append("readme: missing README.md")
        return
    text = path.read_text(encoding="utf-8")
    for raw_target in _MD_LINK.findall(text):
        target = raw_target.split()[0].split("#")[0].split("?")[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        if not (root / target).exists():
            errors.append(f"readme: linked path does not exist: {target}")


def _check_makefile(root: Path, errors: list[str], warnings: list[str]) -> None:
    path = root / "Makefile"
    if not path.exists():
        errors.append("makefile: missing Makefile")
        return
    text = path.read_text(encoding="utf-8")
    targets = set(_MAKE_TARGET.findall(text))
    for phony in _PHONY.findall(text):
        for name in phony.split():
            if name not in targets:
                errors.append(f"makefile: .PHONY target {name} has no rule")

    runbook = root / "docs" / "runbook.md"
    if not runbook.exists():
        warnings.append("runbook: docs/runbook.md is missing")
        return
    runbook_text = runbook.read_text(encoding="utf-8")
    referenced: set[str] = set()
    for pattern in _RUNBOOK_TARGETS:
        referenced.update(pattern.findall(runbook_text))
    for name in sorted(referenced):
        if name not in targets:
            errors.append(f"makefile: runbook references missing target {name}")


def _check_gold(root: Path, errors: list[str], warnings: list[str]) -> None:
    path = root / "tests" / "gold" / "matcher_gold.jsonl"
    if not path.exists():
        errors.append("gold: missing tests/gold/matcher_gold.jsonl")
        return

    cases: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"gold: line {lineno}: invalid JSON: {exc}")
            continue
        if not isinstance(case, dict):
            errors.append(f"gold: line {lineno}: expected a JSON object")
            continue
        cases.append(case)

    seen: set[str] = set()
    for case in cases:
        case_id = str(case.get("id") or "")
        if not case_id:
            errors.append("gold: case without an id")
        elif case_id in seen:
            errors.append(f"gold: duplicate case id {case_id}")
        else:
            seen.add(case_id)

        text = case.get("text")
        spans = case.get("expected_spans")
        if not isinstance(text, str) or not isinstance(spans, list):
            errors.append(f"gold: case {case_id or '<unknown>'}: missing text/spans")
            continue
        for span in spans:
            if not isinstance(span, dict):
                errors.append(f"gold: case {case_id}: span is not an object")
                continue
            start, end, surface = span.get("start"), span.get("end"), span.get("surface")
            if not isinstance(start, int) or not isinstance(end, int):
                errors.append(f"gold: case {case_id}: span offsets must be integers")
            elif not 0 <= start < end <= len(text):
                errors.append(f"gold: case {case_id}: span offsets out of range")
            elif text[start:end] != surface:
                errors.append(f"gold: case {case_id}: span surface does not match text")

    if len(cases) < GOLD_TARGET_CASES:
        warnings.append(
            f"gold: {len(cases)} cases, below the {GOLD_TARGET_CASES}-case P05 target"
        )


def check_all(root: str | Path = ".") -> dict[str, Any]:
    """Run every check and return ``{"ok", "errors", "warnings"}``."""
    base = Path(root)
    errors: list[str] = []
    warnings: list[str] = []

    glossary_ids = _check_glossary(base, errors, warnings)
    _check_scripts(base, glossary_ids, errors, warnings)
    _check_assignment(base, glossary_ids, errors, warnings)
    _check_core200(base, errors, warnings)
    _check_readme(base, errors, warnings)
    _check_makefile(base, errors, warnings)
    _check_gold(base, errors, warnings)

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="repository root")
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    args = parser.parse_args(argv)

    report = check_all(args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        for error in report["errors"]:
            print(_ascii(f"ERROR {error}"))
        for warning in report["warnings"]:
            print(_ascii(f"WARN {warning}"))
        status = "ok" if report["ok"] else "failed"
        print(
            _ascii(
                f"data consistency: {status} "
                f"({len(report['errors'])} errors, {len(report['warnings'])} warnings)"
            )
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
