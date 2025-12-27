"""Sub-agent type definitions and configurations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto


class SubAgentType(StrEnum):
    """Types of specialized sub-agents."""

    EXPLORE = auto()  # Read-only codebase exploration
    PLAN = auto()  # Design implementation approaches
    TASK = auto()  # General-purpose task execution

    @property
    def display_name(self) -> str:
        return SUBAGENT_CONFIGS[self].display_name

    @property
    def description(self) -> str:
        return SUBAGENT_CONFIGS[self].description

    @classmethod
    def from_string(cls, value: str) -> SubAgentType | None:
        try:
            return cls(value.lower())
        except ValueError:
            return None


@dataclass(frozen=True)
class SubAgentConfig:
    """Configuration for a sub-agent type."""

    type: SubAgentType
    display_name: str
    description: str
    enabled_tools: list[str] = field(default_factory=list)
    auto_approve: bool = True
    max_turns: int = 50
    include_project_context: bool = True


# Pre-defined sub-agent configurations
SUBAGENT_CONFIGS: dict[SubAgentType, SubAgentConfig] = {
    SubAgentType.EXPLORE: SubAgentConfig(
        type=SubAgentType.EXPLORE,
        display_name="Explore Agent",
        description="Read-only codebase exploration with search and read tools",
        enabled_tools=["grep", "read_file", "list_dir", "symbol_search"],
        auto_approve=True,
        max_turns=30,
        include_project_context=True,
    ),
    SubAgentType.PLAN: SubAgentConfig(
        type=SubAgentType.PLAN,
        display_name="Plan Agent",
        description="Design and plan implementation approaches",
        enabled_tools=["grep", "read_file", "list_dir", "todo", "symbol_search"],
        auto_approve=True,
        max_turns=50,
        include_project_context=True,
    ),
    SubAgentType.TASK: SubAgentConfig(
        type=SubAgentType.TASK,
        display_name="Task Agent",
        description="Execute complex multi-step tasks with full tool access",
        enabled_tools=[],  # Empty means all tools available
        auto_approve=False,  # Inherits from parent permission settings
        max_turns=100,
        include_project_context=True,
    ),
}
