"""Single-scenario, bounded Sub-agent support."""

from .contracts import SubAgentLimits, SubAgentResult
from .registry import DATA_CHECK_TOOLS, DELEGATE_TOOL_NAME, build_restricted_registry
from .runner import DataCheckSubAgentRunner
from .tool import data_check_delegate_definition

__all__ = [
    "DATA_CHECK_TOOLS",
    "DELEGATE_TOOL_NAME",
    "DataCheckSubAgentRunner",
    "SubAgentLimits",
    "SubAgentResult",
    "build_restricted_registry",
    "data_check_delegate_definition",
]

