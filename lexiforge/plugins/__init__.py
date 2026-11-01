"""Plugin architecture for ASR backends."""

from lexiforge.plugins.base import ASRBackend, BackendConfig
from lexiforge.plugins.prisma import PrismaBackend
from lexiforge.plugins.registry import BackendRegistry, get_registry

__all__ = [
    "ASRBackend",
    "BackendConfig",
    "BackendRegistry",
    "get_registry",
    "PrismaBackend",
]
