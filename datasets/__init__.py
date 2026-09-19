"""Task-scoped dataset registration for multi-file analysis."""

from .bridge import MultiFileBridge
from .registry import DatasetRegistry, DatasetRegistryError

__all__ = ["DatasetRegistry", "DatasetRegistryError", "MultiFileBridge"]
