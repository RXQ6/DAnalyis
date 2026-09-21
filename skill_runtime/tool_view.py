"""Build a restricted view from existing ToolRegistry definitions."""

from __future__ import annotations

from tools.registry import ToolExecutionError, ToolRegistry


def build_skill_tool_view(
    source: ToolRegistry, allowed_tools: tuple[str, ...]
) -> ToolRegistry:
    if not allowed_tools or len(allowed_tools) != len(set(allowed_tools)):
        raise ValueError("skill allowed-tools must be non-empty and unique")
    try:
        definitions = [source.get(name) for name in allowed_tools]
    except ToolExecutionError as error:
        raise ValueError(f"skill references an unavailable tool: {error}") from error
    restricted = ToolRegistry()
    restricted.register_many(definitions)
    return restricted

