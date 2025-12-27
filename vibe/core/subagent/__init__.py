"""Sub-agent architecture for isolated task execution."""

from __future__ import annotations

from vibe.core.subagent.result import SubAgentResult
from vibe.core.subagent.runner import SubAgentRunner
from vibe.core.subagent.types import SubAgentConfig, SubAgentType

__all__ = [
    "SubAgentConfig",
    "SubAgentResult",
    "SubAgentRunner",
    "SubAgentType",
]
