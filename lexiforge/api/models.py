"""Pydantic models for Gnani Prisma v3.0 API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    """Job status values."""
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PROCESSING = "PROCESSING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"
    START_FAILED = "START_FAILED"
    CANCELLED = "CANCELLED"


class FileStatus(str, Enum):
    """File status values."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AudioConfig(BaseModel):
    """Audio configuration."""
    model_config = ConfigDict(extra='allow')
    
    language: Optional[str] = None
    model: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None


class BatchJobConfig(BaseModel):
    """Batch job configuration."""
    model_config = ConfigDict(extra='allow')
    
    language: str = "hi"
    model: Optional[str] = None
    enable_word_time_offsets: bool = False
    enable_punctuation: bool = True
    enable_speaker_diarization: bool = False
    context: Optional[List[str]] = None
    vocabulary: Optional[List[str]] = None
    custom_vocabulary: Optional[List[str]] = None


class CreateJobRequest(BaseModel):
    """Request to create a batch job."""
    config: BatchJobConfig
    files: List[str]


class BatchJob(BaseModel):
    """Batch job response.

    ``job_id`` accepts either ``id`` or ``job_id`` on the wire and is required:
    a payload with neither is an API error, not an empty-string job.
    """
    model_config = ConfigDict(extra='allow', populate_by_name=True)

    job_id: str = Field(validation_alias=AliasChoices("id", "job_id"))
    status: JobStatus = JobStatus.CREATED
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    total_files: Optional[int] = None
    completed_files: Optional[int] = None
    failed_files: Optional[int] = None


class FileEntry(BaseModel):
    """File entry in a batch job."""
    model_config = ConfigDict(extra='allow')
    
    file_id: str
    name: Optional[str] = None
    filename: Optional[str] = None
    file_name: Optional[str] = None
    status: FileStatus = FileStatus.PENDING
    transcript_url: Optional[str] = None
    duration: Optional[float] = None
    error: Optional[Dict[str, Any]] = None
    
    def __init__(self, **data):
        if 'file_name' in data and 'name' not in data and 'filename' not in data:
            data['name'] = data['file_name']
        super().__init__(**data)


class Word(BaseModel):
    """Word with timing information."""
    model_config = ConfigDict(extra='allow')
    
    word: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    confidence: Optional[float] = None


class Transcript(BaseModel):
    """Transcript response."""
    model_config = ConfigDict(extra='allow')
    
    text: str
    words: Optional[List[Word]] = None
    confidence: Optional[float] = None
    language: Optional[str] = None
    duration: Optional[float] = None


# Aliases for compatibility
TranscriptResponse = Transcript


class AudioConstraints(BaseModel):
    """Audio constraints from API."""
    model_config = ConfigDict(extra='allow')
    
    max_duration_seconds: Optional[int] = None
    max_file_size_mb: Optional[int] = None
    supported_formats: Optional[List[str]] = None


class ApiInfo(BaseModel):
    """API information and constraints."""
    model_config = ConfigDict(extra='allow')
    
    models: Optional[List[str]] = None
    supported_models: Optional[List[str]] = None
    audio_constraints: Optional[AudioConstraints] = None
    languages: Optional[List[str]] = None


# Additional aliases
BatchJobResponse = BatchJob
FileEntryResponse = FileEntry
TranscriptResult = Transcript
