"""Backend registry for ASR plugins."""

from __future__ import annotations

from typing import Dict, Type

from lexiforge.plugins.base import ASRBackend, BackendConfig


class BackendRegistry:
    """Registry for ASR backends."""
    
    def __init__(self):
        self._backends: Dict[str, Type[ASRBackend]] = {}
    
    def register(self, name: str, backend_class: Type[ASRBackend]):
        """Register a backend class."""
        self._backends[name] = backend_class
    
    def get(self, name: str) -> Type[ASRBackend]:
        """Get a backend class by name."""
        if name not in self._backends:
            raise ValueError(f"Backend '{name}' not registered")
        return self._backends[name]
    
    def create(self, name: str, config: BackendConfig) -> ASRBackend:
        """Create a backend instance."""
        backend_class = self.get(name)
        return backend_class(config)
    
    def list_backends(self) -> list[str]:
        """List registered backend names."""
        return list(self._backends.keys())


_registry = BackendRegistry()


def get_registry() -> BackendRegistry:
    """Get the global backend registry."""
    return _registry
