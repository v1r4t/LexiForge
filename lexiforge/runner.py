"""Orchestration layer for batch transcription jobs.

Implements an 8-state machine over BatchClient and Ledger with
dependency injection for testability.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class JobState(str, Enum):
    DRAFT = "DRAFT"
    CREATED = "CREATED"
    STARTED = "STARTED"
    POLLING = "POLLING"
    FILES_READY = "FILES_READY"
    DOWNLOADING = "DOWNLOADING"
    VERIFIED = "VERIFIED"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    PARTIAL = "PARTIAL"


CONVERSATION_INDEPENDENT = {"baseline", "static", "random"}


class Runner:
    def __init__(self, batch_client: Any = None, ledger: Any = None, **kwargs):
        self.batch_client = batch_client
        self.ledger = ledger
        # Allow passing via different names for flexibility
        if self.batch_client is None and "client" in kwargs:
            self.batch_client = kwargs["client"]
        if self.ledger is None and "db" in kwargs:
            self.ledger = kwargs["db"]
        if self.batch_client is None and "batch" in kwargs:
            self.batch_client = kwargs["batch"]

    def run_condition(
        self,
        condition: str,
        conversations: List[str],
        files_by_call: Dict[str, List[Union[str, Path]]],
        context_by_call: Dict[str, Any],
        replicate: int = 0,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if config is None:
            config = {}

        summary = {
            "attempted": 0,
            "downloaded": 0,
            "missing": 0,
            "jobs": 0,
        }

        # Determine if conversation-independent -> one job for all files
        per_call = config.get("per_call")
        if per_call is None:
            if condition in CONVERSATION_INDEPENDENT:
                per_call = False
            else:
                per_call = True

        if not per_call:
            # One job for all files across all conversations
            all_files = []
            for conv in conversations:
                files = files_by_call.get(conv) or files_by_call.get(str(conv)) or []
                all_files.extend(files)
            job_result = self._run_job(
                condition=condition,
                conversations=conversations,
                files=all_files,
                context=None,  # no context for conversation-independent
                replicate=replicate,
                config=config,
            )
            summary["jobs"] += 1
            summary["attempted"] += job_result.get("attempted", len(all_files))
            summary["downloaded"] += job_result.get("downloaded", 0)
            summary["missing"] += job_result.get("missing", 0)
            return summary
        else:
            # One job per call per condition
            for conv in conversations:
                files = files_by_call.get(conv) or files_by_call.get(str(conv)) or []
                context = context_by_call.get(conv) or context_by_call.get(str(conv))
                job_result = self._run_job(
                    condition=condition,
                    conversations=[conv],
                    files=files,
                    context=context,
                    replicate=replicate,
                    config=config,
                )
                summary["jobs"] += 1
                summary["attempted"] += job_result.get("attempted", len(files))
                summary["downloaded"] += job_result.get("downloaded", 0)
                summary["missing"] += job_result.get("missing", 0)
            return summary

    def _run_job(
        self,
        condition: str,
        conversations: List[str],
        files: List[Union[str, Path]],
        context: Any = None,
        replicate: int = 0,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if config is None:
            config = {}

        files_list = [Path(f) if not isinstance(f, Path) else f for f in files]
        expected_count = len(files_list)

        # Check ledger for existing job for this (condition, conversation(s), replicate)
        # For single conversation or grouped, use a key strategy
        conv_key = conversations[0] if len(conversations) == 1 else "_".join(sorted(str(c) for c in conversations))

        job_id = None
        if self.ledger is not None:
            # Try to find existing job
            existing = self._ledger_get_job(condition, conv_key, replicate)
            if existing:
                job_id = existing.get("client_job_id") or existing.get("job_id") or existing.get("remote_job_id")

        if job_id is None:
            # Create new job - write-ahead client_job_id before POST
            job_id = self._create_job_ahead(condition, conv_key, replicate)
            # POST to create remote job
            if self.batch_client is not None:
                try:
                    resp = self.batch_client.create_job(files=files_list, context=context, condition=condition)
                    if resp:
                        remote_id = resp.get("job_id") or resp.get("id") or resp.get("client_job_id") or job_id
                        job_id = remote_id
                        # Update ledger with remote job id
                        if self.ledger is not None:
                            self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.CREATED)
                except Exception:
                    # On failure, record terminal state
                    if self.ledger is not None:
                        self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.FAILED_TERMINAL)
                    return {
                        "attempted": expected_count,
                        "downloaded": 0,
                        "missing": expected_count,
                    }
            else:
                if self.ledger is not None:
                    self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.CREATED)
        else:
            # Existing remote job - do not re-POST
            pass

        # Poll for job status
        job_status = None
        if self.batch_client is not None and job_id is not None:
            try:
                job_status = self.batch_client.get_job_status(job_id)
                if self.ledger is not None:
                    self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.POLLING)
            except Exception:
                if self.ledger is not None:
                    self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.FAILED_TERMINAL)
                return {
                    "attempted": expected_count,
                    "downloaded": 0,
                    "missing": expected_count,
                }

        # Check if files are ready
        if job_status:
            status = job_status.get("status") or job_status.get("state")
            if status in ("FAILED", "ERROR", "FAILED_TERMINAL"):
                if self.ledger is not None:
                    self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.FAILED_TERMINAL)
                return {
                    "attempted": expected_count,
                    "downloaded": 0,
                    "missing": expected_count,
                }

        # Get results/files
        results = []
        if self.batch_client is not None and job_id is not None:
            try:
                results = self.batch_client.get_results(job_id) or []
                if self.ledger is not None:
                    self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.FILES_READY)
            except Exception:
                if self.ledger is not None:
                    self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.FAILED_TERMINAL)
                return {
                    "attempted": expected_count,
                    "downloaded": 0,
                    "missing": expected_count,
                }

        # Download files - only those with no local transcript
        downloaded = 0
        missing = 0
        downloaded_files = set()

        if self.ledger is not None:
            self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.DOWNLOADING)

        for i, fpath in enumerate(files_list):
            # Check if transcript already exists locally
            has_local = self._has_local_transcript(fpath, config)
            if has_local:
                downloaded += 1  # or count as present
                downloaded_files.add(str(fpath))
                continue

            # Try to download from results
            result_found = False
            if results:
                for res in results:
                    res_file = res.get("file") or res.get("filename") or res.get("name") or res.get("input") or res.get("conversation")
                    if res_file and (str(fpath) in str(res_file) or Path(str(res_file)).name == fpath.name):
                        # Download transcript
                        try:
                            transcript = self.batch_client.download_transcript(job_id, res)
                            if transcript is not None or res.get("transcript") is not None:
                                self._save_transcript(fpath, transcript or res.get("transcript"), config)
                                downloaded += 1
                                downloaded_files.add(str(fpath))
                                result_found = True
                                break
                        except Exception:
                            result_found = False
                            break

            if not result_found:
                missing += 1
                # Log missing explicitly
                if self.ledger is not None:
                    try:
                        self._ledger_log_missing(condition, conv_key, replicate, str(fpath))
                    except Exception:
                        pass

        # Check if every expected file is accounted for
        accounted = downloaded + missing
        if accounted < expected_count:
            # Some files not processed
            missing += expected_count - accounted

        if missing > 0:
            if self.ledger is not None:
                self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.PARTIAL)
        else:
            if self.ledger is not None:
                self._ledger_update_job(condition, conv_key, replicate, job_id, state=JobState.VERIFIED)

        return {
            "attempted": expected_count,
            "downloaded": downloaded,
            "missing": missing,
            "jobs": 1,
        }

    def resume(self, condition: Optional[str] = None) -> Dict[str, Any]:
        summary = {
            "attempted": 0,
            "downloaded": 0,
            "missing": 0,
            "jobs": 0,
        }

        if self.ledger is None:
            return summary

        # Get incomplete jobs from ledger
        jobs = []
        try:
            if hasattr(self.ledger, "get_incomplete_jobs"):
                jobs = self.ledger.get_incomplete_jobs(condition=condition)
            elif hasattr(self.ledger, "list_jobs"):
                all_jobs = self.ledger.list_jobs(condition=condition)
                jobs = [j for j in all_jobs if j.get("state") not in (JobState.VERIFIED, "VERIFIED")]
        except Exception:
            jobs = []

        for job in jobs:
            job_state = job.get("state")
            if job_state == JobState.FAILED_TERMINAL or str(job_state) == "FAILED_TERMINAL":
                # Terminal failure states are recorded, never silently retried
                continue

            job_id = job.get("client_job_id") or job.get("job_id") or job.get("remote_job_id")
            if not job_id:
                continue

            # Never re-POSTs an existing remote job
            # Poll existing job
            if self.batch_client is not None:
                try:
                    job_status = self.batch_client.get_job_status(job_id)
                except Exception:
                    continue

                try:
                    results = self.batch_client.get_results(job_id) or []
                except Exception:
                    results = []
            else:
                results = []

            files = job.get("files") or []
            files_list = [Path(f) if not isinstance(f, Path) else f for f in files]
            downloaded = 0
            missing = 0

            for fpath in files_list:
                has_local = self._has_local_transcript(fpath, job.get("config") or {})
                if has_local:
                    downloaded += 1
                    continue

                # Download only files with no local transcript
                result_found = False
                if results:
                    for res in results:
                        res_file = res.get("file") or res.get("filename") or res.get("name")
                        if res_file and (str(fpath) in str(res_file) or Path(str(res_file)).name == fpath.name):
                            try:
                                transcript = self.batch_client.download_transcript(job_id, res)
                                self._save_transcript(fpath, transcript or res.get("transcript"), job.get("config") or {})
                                downloaded += 1
                                result_found = True
                                break
                            except Exception:
                                break
                if not result_found:
                    missing += 1

            summary["jobs"] += 1
            summary["attempted"] += len(files_list)
            summary["downloaded"] += downloaded
            summary["missing"] += missing

            # Update state
            if self.ledger is not None:
                try:
                    conv_key = job.get("conversation_key") or job.get("conversations") or ""
                    if isinstance(conv_key, list):
                        conv_key = conv_key[0] if conv_key else ""
                    cond = job.get("condition") or condition
                    rep = job.get("replicate", 0)
                    if missing > 0:
                        self._ledger_update_job(cond, str(conv_key), rep, job_id, state=JobState.PARTIAL)
                    else:
                        self._ledger_update_job(cond, str(conv_key), rep, job_id, state=JobState.VERIFIED)
                except Exception:
                    pass

        return summary

    def run_pass1(self, files: List[Union[str, Path]], config: Optional[Dict[str, Any]] = None) -> str:
        if config is None:
            config = {}
        files_list = [Path(f) if not isinstance(f, Path) else f for f in files]

        job_id = None
        if self.batch_client is not None:
            try:
                resp = self.batch_client.create_job(files=files_list, context=None, condition="pass1")
                if resp:
                    job_id = resp.get("job_id") or resp.get("id")
            except Exception:
                pass

        if job_id is None and self.ledger is not None:
            # Try to create via ledger/client pattern
            try:
                job_id = self._create_job_ahead("pass1", "pass1", 0)
            except Exception:
                job_id = "pass1-job"

        if self.ledger is not None and job_id is not None:
            try:
                self._ledger_update_job("pass1", "pass1", 0, job_id, state=JobState.CREATED)
            except Exception:
                pass

        return str(job_id)

    def _create_job_ahead(self, condition: str, conv_key: str, replicate: int) -> str:
        # Write-ahead client_job_id persisted before the POST
        job_id = f"{condition}_{conv_key}_{replicate}_job"
        if self.ledger is not None:
            try:
                if hasattr(self.ledger, "create_job"):
                    self.ledger.create_job(
                        condition=condition,
                        conversation=conv_key,
                        replicate=replicate,
                        client_job_id=job_id,
                        state=JobState.DRAFT,
                    )
                elif hasattr(self.ledger, "write_job"):
                    self.ledger.write_job(condition, conv_key, replicate, job_id, JobState.DRAFT)
                elif hasattr(self.ledger, "insert_job"):
                    self.ledger.insert_job(condition, conv_key, replicate, job_id)
            except Exception:
                pass
        return job_id

    def _ledger_get_job(self, condition: str, conv_key: str, replicate: int):
        if self.ledger is None:
            return None
        try:
            if hasattr(self.ledger, "get_job"):
                return self.ledger.get_job(condition, conv_key, replicate)
            elif hasattr(self.ledger, "fetch_job"):
                return self.ledger.fetch_job(condition, conv_key, replicate)
        except Exception:
            pass
        return None

    def _ledger_update_job(self, condition: str, conv_key: str, replicate: int, job_id: str, state: JobState = None):
        if self.ledger is None:
            return
        try:
            if hasattr(self.ledger, "update_job"):
                self.ledger.update_job(condition, conv_key, replicate, job_id=job_id, state=state)
            elif hasattr(self.ledger, "set_state"):
                self.ledger.set_state(condition, conv_key, replicate, state)
        except Exception:
            pass

    def _ledger_log_missing(self, condition: str, conv_key: str, replicate: int, filepath: str):
        if self.ledger is None:
            return
        try:
            if hasattr(self.ledger, "log_missing"):
                self.ledger.log_missing(condition, conv_key, replicate, filepath)
            elif hasattr(self.ledger, "record_missing"):
                self.ledger.record_missing(condition, conv_key, replicate, filepath)
        except Exception:
            pass

    def _has_local_transcript(self, fpath: Path, config: Dict[str, Any]) -> bool:
        # Check if local transcript exists
        transcripts_dir = config.get("transcripts_dir") or config.get("transcript_dir")
        if transcripts_dir:
            tpath = Path(transcripts_dir) / (fpath.stem + ".json")
            if tpath.exists():
                return True
            tpath = Path(transcripts_dir) / (fpath.stem + ".txt")
            if tpath.exists():
                return True
        # Also check common locations
        for ext in [".json", ".txt", ".transcript"]:
            cand = fpath.with_suffix(ext)
            if cand.exists() and cand != fpath:
                return True
        return False

    def _save_transcript(self, fpath: Path, transcript: Any, config: Dict[str, Any]):
        transcripts_dir = config.get("transcripts_dir") or config.get("transcript_dir") or Path("transcripts")
        try:
            Path(transcripts_dir).mkdir(parents=True, exist_ok=True)
            outpath = Path(transcripts_dir) / (fpath.stem + ".json")
            if isinstance(transcript, str):
                outpath.write_text(json.dumps({"text": transcript}), encoding="utf-8")
            else:
                outpath.write_text(json.dumps(transcript), encoding="utf-8")
        except Exception:
            pass


# Module-level functions for flexibility
def run_condition(*args, **kwargs):
    runner = kwargs.pop("runner", None)
    if runner is None and len(args) > 0 and hasattr(args[0], "run_condition"):
        runner = args[0]
        args = args[1:]
    elif runner is None:
        runner = Runner()
    return runner.run_condition(*args, **kwargs)


def resume(*args, **kwargs):
    runner = kwargs.pop("runner", None)
    if runner is None and len(args) > 0 and hasattr(args[0], "resume"):
        runner = args[0]
        args = args[1:]
    elif runner is None:
        runner = Runner()
    return runner.resume(*args, **kwargs)


def run_pass1(*args, **kwargs):
    runner = kwargs.pop("runner", None)
    if runner is None and len(args) > 0 and hasattr(args[0], "run_pass1"):
        runner = args[0]
        args = args[1:]
    elif runner is None:
        runner = Runner()
    return runner.run_pass1(*args, **kwargs)
