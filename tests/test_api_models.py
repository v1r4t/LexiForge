"""Tests for API Pydantic models."""

from __future__ import annotations

from lexiforge.api.models import (
    BatchJob,
    BatchJobConfig,
    FileEntry,
    FileStatus,
    JobStatus,
    TranscriptResponse,
)


class TestBatchJobConfig:
    def test_minimal_config(self):
        config = BatchJobConfig(model="prisma-v3.0")
        assert config.model == "prisma-v3.0"

    def test_config_with_options(self):
        config = BatchJobConfig(
            model="prisma-v3.0",
            language="hi",
            keyterms=["NEFT", "UPI"],
            transcription_mode="clean",
        )
        assert config.model == "prisma-v3.0"
        assert config.language == "hi"
        assert config.keyterms == ["NEFT", "UPI"]
        assert config.transcription_mode == "clean"


class TestJobStatus:
    def test_valid_statuses(self):
        assert JobStatus.CREATED == "CREATED"
        assert JobStatus.COMPLETED == "COMPLETED"
        assert JobStatus.FAILED == "FAILED"


class TestFileStatus:
    def test_valid_statuses(self):
        assert FileStatus.PENDING == "PENDING"
        assert FileStatus.COMPLETED == "COMPLETED"


class TestBatchJob:
    def test_batch_job_creation(self):
        job = BatchJob(job_id="job123", status=JobStatus.CREATED)
        assert job.job_id == "job123"
        assert job.status == JobStatus.CREATED

    def test_batch_job_with_files(self):
        files = [FileEntry(file_id="f1", file_name="test.wav")]
        job = BatchJob(job_id="job123", status=JobStatus.RUNNING, files=files)
        assert len(job.files) == 1
        assert job.files[0].file_id == "f1"


class TestFileEntry:
    def test_file_entry_creation(self):
        entry = FileEntry(file_id="f1", file_name="test.wav", status=FileStatus.COMPLETED)
        assert entry.file_id == "f1"
        assert entry.file_name == "test.wav"
        assert entry.status == FileStatus.COMPLETED


class TestTranscriptResponse:
    def test_transcript_response(self):
        resp = TranscriptResponse(text="Hello world", file_id="f1")
        assert resp.text == "Hello world"
        assert resp.file_id == "f1"
