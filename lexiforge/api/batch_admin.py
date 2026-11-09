"""Batch job administration: list, cancel, reconcile and resume.

The runner writes a local ledger row *before* the remote POST, so the server
and the ledger can drift apart after a crash. These helpers make that drift
visible and let an operator act on it without ever creating (or re-POSTing) a
job, which is the double-billing window described in design.md §4. Cancel is
idempotent for terminal jobs and is not retried on ambiguous 5xx failures
(design.md §10).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from lexiforge.api.client import TERMINAL_STATUSES, BatchApiError

__all__ = ["cancel", "reconcile", "resume"]

_SERVER_ID_KEYS = ("job_id", "jobId", "id")
_LEDGER_ID_KEYS = ("remote_job_id", "job_id", "client_job_id")


def _first_id(record: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = record.get(key)
        if value:
            return str(value)
    return None


def _ledger_ids(ledger_rows: Iterable[Mapping[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for row in ledger_rows:
        job_id = _first_id(row, _LEDGER_ID_KEYS)
        if job_id:
            ids.add(job_id)
    return ids


def reconcile(client: Any, ledger_rows: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Compare server jobs with ledger rows.

    Returns sorted ``known`` ids (both sides), ``orphans`` (server-side only:
    possibly billed but unrecorded) and ``missing`` (ledger-side only: a
    remote id the server no longer knows about).
    """
    server_ids = {
        job_id
        for job_id in (
            _first_id(job, _SERVER_ID_KEYS) for job in client.list_jobs()
        )
        if job_id
    }
    local_ids = _ledger_ids(ledger_rows)
    return {
        "known": sorted(server_ids & local_ids),
        "orphans": sorted(server_ids - local_ids),
        "missing": sorted(local_ids - server_ids),
    }


def cancel(client: Any, job_ids: Iterable[str]) -> dict[str, str]:
    """Cancel each id once, preserving input order; return id -> status.

    ``BatchClient.cancel_job`` already treats terminal jobs as a no-op, so
    calling this twice is safe.
    """
    statuses: dict[str, str] = {}
    for job_id in job_ids:
        if job_id in statuses:
            continue
        statuses[job_id] = client.cancel_job(job_id)
    return statuses


def resume(client: Any, ledger_rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Return remote job ids that are still running, sorted by id.

    Resume means re-attaching to work that already exists: the server is the
    source of truth for each ledger row's ``remote_job_id``. Jobs already in a
    terminal state are done, rows without a remote id are drafts, and a 404
    means the remote job vanished - none are returned. This helper never
    creates, starts or re-POSTs a job.
    """
    running: set[str] = set()
    for row in ledger_rows:
        job_id = _first_id(row, ("remote_job_id",))
        if not job_id:
            continue
        try:
            job = client.get_job(job_id)
        except BatchApiError as exc:
            if exc.status_code == 404:
                continue
            raise
        if client.job_status(job) not in TERMINAL_STATUSES:
            running.add(job_id)
    return sorted(running)
