"""SQLite ledger for the transcription harness (design.md section 4).

Write-ahead ``client_job_id`` is persisted BEFORE the remote POST, keyed
uniquely on ``(condition, conversation, replicate)`` so a restart cannot
double-submit. Standard library only (``sqlite3``).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

TERMINAL_STATES = ("VERIFIED", "FAILED_TERMINAL")

# Bump when _SCHEMA changes; init() records this in PRAGMA user_version so an
# old database is detected instead of silently missing a column.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conditions (
    name TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contexts (
    context_hash TEXT PRIMARY KEY,
    condition TEXT,
    conversation TEXT,
    config_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    local_path TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    client_job_id TEXT PRIMARY KEY,
    condition TEXT NOT NULL,
    conversation TEXT NOT NULL,
    replicate INTEGER NOT NULL,
    context_hash TEXT,
    config_json TEXT,
    remote_job_id TEXT,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (condition, conversation, replicate)
);
CREATE TABLE IF NOT EXISTS job_files (
    client_job_id TEXT NOT NULL REFERENCES jobs(client_job_id) ON DELETE CASCADE,
    file_id TEXT NOT NULL,
    remote_name TEXT,
    status TEXT,
    transcript_url TEXT,
    updated_at TEXT,
    PRIMARY KEY (client_job_id, file_id)
);
CREATE TABLE IF NOT EXISTS transcripts (
    client_job_id TEXT NOT NULL REFERENCES jobs(client_job_id) ON DELETE CASCADE,
    file_id TEXT NOT NULL,
    text TEXT,
    raw_path TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (client_job_id, file_id)
);
CREATE TABLE IF NOT EXISTS missing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition TEXT NOT NULL,
    conversation TEXT NOT NULL,
    replicate INTEGER NOT NULL,
    file_id TEXT,
    file_path TEXT,
    created_at TEXT NOT NULL
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_str(status: Any) -> str:
    return getattr(status, "value", status) if status is not None else "DRAFT"


class Ledger:
    """SQLite-backed job ledger. One persistent connection per instance."""

    def __init__(self, path: Union[str, Path] = "lexiforge.db", **kwargs: Any) -> None:
        if "db_path" in kwargs:
            path = kwargs["db_path"]
        elif "db" in kwargs:
            path = kwargs["db"]
        self.db_path = str(path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.init()

    # -- setup -----------------------------------------------------------
    def init(self) -> "Ledger":
        self._conn.execute("PRAGMA foreign_keys = ON")
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:
            pass  # e.g. :memory: databases cannot use WAL
        self._conn.executescript(_SCHEMA)
        try:
            self._record_schema_version()
        except RuntimeError:
            # Do not leak the handle when refusing a database.
            self._conn.close()
            raise
        self._conn.commit()
        return self

    def schema_version(self) -> int:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    def _record_schema_version(self) -> None:
        """Stamp the schema version, refusing to open a newer database.

        Every statement in ``_SCHEMA`` is ``CREATE TABLE IF NOT EXISTS``, so an
        older file silently keeps its old columns. Stamping and checking the
        version turns that into a clear error instead of a confusing one.
        """
        existing = self.schema_version()
        if existing > SCHEMA_VERSION:
            raise RuntimeError(
                f"ledger schema {existing} is newer than this build ({SCHEMA_VERSION}); "
                "upgrade lexiforge or use a different database"
            )
        if existing != SCHEMA_VERSION:
            self._conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")

    def close(self) -> None:
        try:
            self._conn.commit()
        finally:
            self._conn.close()

    # -- core API --------------------------------------------------------
    def reserve_job(
        self,
        condition: str,
        conversation: str,
        replicate: int = 0,
        context_hash: Optional[str] = None,
        config_json: Optional[Union[str, Dict[str, Any]]] = None,
        client_job_id: Optional[str] = None,
    ) -> str:
        """Persist a write-ahead client_job_id BEFORE the remote POST.

        Idempotent: reserving the same (condition, conversation, replicate)
        twice returns the existing row's id without creating a duplicate. A
        caller-supplied ``client_job_id`` is honoured, so the id the runner
        persisted is the id the remote POST is reconciled against.
        """
        if isinstance(config_json, dict):
            config_json = json.dumps(config_json, sort_keys=True)
        now = _utcnow()
        self._conn.execute(
            "INSERT OR IGNORE INTO conditions (name, created_at) VALUES (?, ?)",
            (condition, now),
        )
        if context_hash:
            self._conn.execute(
                "INSERT OR IGNORE INTO contexts"
                " (context_hash, condition, conversation, config_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (context_hash, condition, conversation, config_json, now),
            )
        write_ahead_id = client_job_id or f"{condition}__{conversation}__r{int(replicate)}"
        self._conn.execute(
            "INSERT OR IGNORE INTO jobs"
            " (client_job_id, condition, conversation, replicate,"
            "  context_hash, config_json, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?)",
            (
                write_ahead_id,
                condition,
                conversation,
                int(replicate),
                context_hash,
                config_json,
                now,
                now,
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT client_job_id FROM jobs"
            " WHERE condition = ? AND conversation = ? AND replicate = ?",
            (condition, conversation, int(replicate)),
        ).fetchone()
        return row["client_job_id"]

    def attach_remote_job(self, client_job_id: str, remote_job_id: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET remote_job_id = ?, updated_at = ?"
            " WHERE client_job_id = ?",
            (remote_job_id, _utcnow(), client_job_id),
        )
        self._conn.commit()

    def record_status(self, client_job_id: str, status: Any) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE client_job_id = ?",
            (_status_str(status), _utcnow(), client_job_id),
        )
        self._conn.commit()

    def record_file(
        self,
        client_job_id: str,
        file_id: str,
        remote_name: Optional[str] = None,
        status: Optional[Any] = None,
        transcript_url: Optional[str] = None,
    ) -> None:
        now = _utcnow()
        self._conn.execute(
            "INSERT OR IGNORE INTO files (file_id, local_path, created_at)"
            " VALUES (?, ?, ?)",
            (file_id, remote_name, now),
        )
        self._conn.execute(
            "INSERT INTO job_files"
            " (client_job_id, file_id, remote_name, status, transcript_url, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (client_job_id, file_id) DO UPDATE SET"
            " remote_name = excluded.remote_name,"
            " status = excluded.status,"
            " transcript_url = excluded.transcript_url,"
            " updated_at = excluded.updated_at",
            (
                client_job_id,
                file_id,
                remote_name,
                _status_str(status) if status is not None else None,
                transcript_url,
                now,
            ),
        )
        self._conn.commit()

    def save_transcript(
        self, client_job_id: str, file_id: str, text: Optional[str], raw_path: str
    ) -> None:
        now = _utcnow()
        self._conn.execute(
            "INSERT OR IGNORE INTO files (file_id, local_path, created_at)"
            " VALUES (?, ?, ?)",
            (file_id, raw_path, now),
        )
        self._conn.execute(
            "INSERT INTO transcripts"
            " (client_job_id, file_id, text, raw_path, created_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (client_job_id, file_id) DO UPDATE SET"
            " text = excluded.text,"
            " raw_path = excluded.raw_path",
            (client_job_id, file_id, text, raw_path, now),
        )
        self._conn.execute(
            "UPDATE job_files SET status = 'downloaded', updated_at = ?"
            " WHERE client_job_id = ? AND file_id = ?"
            " AND (status IS NULL OR status != 'downloaded')",
            (now, client_job_id, file_id),
        )
        self._conn.commit()

    def log_missing_entry(
        self,
        condition: str,
        conversation: str,
        replicate: int,
        file_id: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO missing_log"
            " (condition, conversation, replicate, file_id, file_path, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (condition, conversation, int(replicate), file_id, file_path, _utcnow()),
        )
        self._conn.commit()

    def coverage(self, condition: str) -> Dict[str, Dict[str, int]]:
        """Per-conversation gate: attempted / contributed / missing."""
        conversations = set()
        for table in ("jobs", "missing_log"):
            for row in self._conn.execute(
                f"SELECT DISTINCT conversation FROM {table} WHERE condition = ?",
                (condition,),
            ):
                conversations.add(row["conversation"])
        out: Dict[str, Dict[str, int]] = {}
        for conv in sorted(conversations):
            attempted = self._conn.execute(
                "SELECT COUNT(*) AS n FROM job_files jf"
                " JOIN jobs j ON j.client_job_id = jf.client_job_id"
                " WHERE j.condition = ? AND j.conversation = ?",
                (condition, conv),
            ).fetchone()["n"]
            contributed = self._conn.execute(
                "SELECT COUNT(*) AS n FROM transcripts t"
                " JOIN jobs j ON j.client_job_id = t.client_job_id"
                " WHERE j.condition = ? AND j.conversation = ?",
                (condition, conv),
            ).fetchone()["n"]
            missing = self._conn.execute(
                "SELECT COUNT(*) AS n FROM missing_log"
                " WHERE condition = ? AND conversation = ?",
                (condition, conv),
            ).fetchone()["n"]
            out[conv] = {
                "attempted": attempted,
                "contributed": contributed,
                "downloaded": contributed,
                "missing": missing,
            }
        return out

    def pending(self, condition: Optional[str] = None) -> List[Dict[str, Any]]:
        """Jobs not in a terminal state (never re-POSTed on resume)."""
        if condition is None:
            rows = self._conn.execute("SELECT * FROM jobs WHERE status NOT IN (?, ?)",
                                      TERMINAL_STATES).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE condition = ? AND status NOT IN (?, ?)",
                (condition, *TERMINAL_STATES),
            ).fetchall()
        return [self._job_to_dict(r) for r in rows]

    # -- helpers ---------------------------------------------------------
    def _job_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["state"] = d.get("status")
        d["job_id"] = d.get("client_job_id")
        d["conversation_key"] = d.get("conversation")
        d["conversations"] = [d.get("conversation")]
        d["config"] = d.get("config_json")
        return d

    def get_job_by_client(self, client_job_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE client_job_id = ?", (client_job_id,)
        ).fetchone()
        return self._job_to_dict(row) if row else None

    def count_jobs(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]

    # -- runner compatibility --------------------------------------------
    def create_job(self, condition=None, conversation=None, replicate=0,
                   client_job_id=None, state=None, **kwargs) -> Dict[str, Any]:
        conversation = kwargs.pop("conv_key", conversation)
        self.reserve_job(condition, conversation, replicate,
                         kwargs.get("context_hash"), kwargs.get("config_json"),
                         client_job_id=client_job_id)
        if state is not None:
            row = self._conn.execute(
                "SELECT client_job_id FROM jobs WHERE condition=? AND conversation=?"
                " AND replicate=?", (condition, conversation, int(replicate))).fetchone()
            if row:
                self.record_status(row["client_job_id"], state)
        # keep write-ahead id stable: reserve_job owns id generation
        return self.get_job(condition, conversation, replicate)

    def get_job(self, condition, conversation, replicate) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE condition = ? AND conversation = ?"
            " AND replicate = ?",
            (condition, conversation, int(replicate)),
        ).fetchone()
        return self._job_to_dict(row) if row else None

    fetch_job = get_job

    def update_job(self, condition, conversation, replicate, job_id=None,
                   state=None, **kwargs) -> Optional[Dict[str, Any]]:
        job = self.get_job(condition, conversation, replicate)
        if job is None:
            job = self.create_job(condition, conversation, replicate,
                                  client_job_id=job_id, state=state)
            return job
        cid = job["client_job_id"]
        if job_id is not None:
            self.attach_remote_job(cid, job_id)
        if state is not None:
            self.record_status(cid, state)
        return self.get_job_by_client(cid)

    def set_state(self, condition, conversation, replicate, state) -> None:
        job = self.get_job(condition, conversation, replicate)
        if job is None:
            self.create_job(condition, conversation, replicate, state=state)
        else:
            self.record_status(job["client_job_id"], state)

    def log_missing(self, condition, conversation, replicate, filepath) -> None:
        self.log_missing_entry(condition, conversation, replicate,
                               file_id=str(filepath), file_path=str(filepath))

    def record_missing(self, condition, conversation, replicate, filepath) -> None:
        self.log_missing(condition, conversation, replicate, filepath)

    def get_incomplete_jobs(self, condition=None) -> List[Dict[str, Any]]:
        return self.pending(condition)

    def list_jobs(self, condition=None) -> List[Dict[str, Any]]:
        if condition is None:
            rows = self._conn.execute("SELECT * FROM jobs").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE condition = ?", (condition,)).fetchall()
        return [self._job_to_dict(r) for r in rows]
