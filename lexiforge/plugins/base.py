"""Base classes for ASR backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class BackendConfig:
    """Configuration for an ASR backend."""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: float = 60.0
    max_retries: int = 3
    extra: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


class ASRBackend(ABC):
    """Abstract base class for ASR backends."""
    
    def __init__(self, config: BackendConfig):
        self.config = config
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name."""
        pass
    
    @property
    @abstractmethod
    def supported_formats(self) -> List[str]:
        """Supported audio formats."""
        pass
    
    @abstractmethod
    def create_job(
        self,
        files: Union[List[Union[str, Path]], List[Path]],
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a transcription job."""
        pass
    
    @abstractmethod
    def start_job(self, job_id: str) -> None:
        """Start a transcription job."""
        pass
    
    @abstractmethod
    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get job status."""
        pass
    
    @abstractmethod
    def get_results(self, job_id: str) -> List[Dict[str, Any]]:
        """Get job results."""
        pass
    
    @abstractmethod
    def download_transcript(self, job_id: str, file_info: Dict[str, Any]) -> Any:
        """Download transcript for a file."""
        pass
    
    def close(self):
        """Close any resources."""
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
