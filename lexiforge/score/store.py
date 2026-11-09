"""Persist one raw transcript per decoding arm.

Design §5 ("Stamped provenance") requires every scored output to carry the
canonicaliser version it was scored with, so each transcript records
``CANON_VERSION``. The reference script is deliberately absent: re-scoring
reads it from the study manifest, which keeps an arm's transcript from
carrying the answer back into its own evaluation.

Artifacts are UTF-8 JSON with ``ensure_ascii=False`` so Devanagari survives a
byte round-trip. Writes are atomic — the payload is serialised to a sibling
temp file first and then moved into place with ``os.replace`` — so a
serialisation failure or crash never leaves a partial
``<arm>.transcript.json`` behind.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator, Mapping

TRANSCRIPT_SUFFIX = ".transcript.json"


def _canon_version() -> str:
    # Lazy: importing the store must stay cheap and independent of the frozen
    # matcher's import graph (the pilot imports us only on the execute path).
    from lexiforge.canon import CANON_VERSION

    return CANON_VERSION


def write_arm_transcript(
    run_dir: str | os.PathLike[str],
    call_id: str,
    arm: str,
    *,
    text: str,
    rows: Mapping[str, Any],
    config: Mapping[str, Any],
    status: str,
    job_id: str | None = None,
    detected_language_code: str | None = None,
) -> Path:
    """Write ``<run_dir>/<arm>.transcript.json`` atomically and return its path.

    No path is serialised, so the same transcript bytes are byte-identical
    regardless of where the run directory lives.
    """
    directory = Path(run_dir)
    directory.mkdir(parents=True, exist_ok=True)

    payload = {
        "call_id": str(call_id),
        "arm": str(arm),
        "text": text,
        "rows": dict(rows),
        "config": dict(config),
        "status": str(status),
        "job_id": job_id,
        "detected_language_code": detected_language_code,
        "canon_version": _canon_version(),
    }
    # Serialise before touching the filesystem: a value that cannot be dumped
    # (including a stray Path) fails here and leaves nothing behind.
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    target = directory / f"{arm}{TRANSCRIPT_SUFFIX}"
    fd, tmp_name = tempfile.mkstemp(
        dir=directory, prefix=f".{arm}{TRANSCRIPT_SUFFIX}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
        os.replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return target


def read_arm_transcript(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read one transcript artifact; the JSON root must be an object."""
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{source} must contain a JSON object.")
    return data


def iter_arm_transcripts(
    run_dir: str | os.PathLike[str],
) -> Iterator[dict[str, Any]]:
    """Yield every arm transcript in ``run_dir``, ordered by arm filename."""
    directory = Path(run_dir)
    if not directory.is_dir():
        return
    for path in sorted(directory.glob(f"*{TRANSCRIPT_SUFFIX}")):
        yield read_arm_transcript(path)
