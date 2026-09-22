"""Unified, bounded observability primitives for Day20."""

from .collector import TraceCollector
from .contracts import TraceEvent

__all__ = ["TraceCollector", "TraceEvent"]
