"""Task tool for spawning isolated sub-agents."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, Field

from vibe.core.subagent.runner import SubAgentRunner
from vibe.core.subagent.types import SubAgentType
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData

if TYPE_CHECKING:
    from vibe.core.config import VibeConfig
    from vibe.core.llm.types import BackendLike
    from vibe.core.types import ToolCallEvent, ToolResultEvent


class TaskType(StrEnum):
    """Type of sub-agent to spawn."""

    EXPLORE = auto()
    PLAN = auto()
    TASK = auto()


class TaskArgs(BaseModel):
    """Arguments for the Task tool."""

    description: str = Field(
        description="Clear description of the task for the sub-agent to perform"
    )
    type: TaskType = Field(
        default=TaskType.TASK,
        description=(
            "Type of sub-agent: 'explore' for read-only codebase exploration, "
            "'plan' for designing implementation approaches, "
            "'task' for general execution with full tool access"
        ),
    )
    tools: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of specific tools to enable for this sub-agent. "
            "If not provided, uses the default tools for the task type."
        ),
    )


class TaskResult(BaseModel):
    """Result from a sub-agent execution."""

    success: bool
    result: str = Field(description="The sub-agent's final response")
    summary: str = Field(description="Brief summary of actions taken")
    files_read: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    tokens_used: int = 0


class TaskConfig(BaseToolConfig):
    """Configuration for the Task tool."""

    permission: ToolPermission = ToolPermission.ASK
    max_parallel_tasks: int = Field(
        default=3, description="Maximum number of sub-agents that can run in parallel"
    )


class TaskState(BaseToolState):
    """State for the Task tool."""

    active_tasks: int = 0
    total_tasks_run: int = 0


class Task(
    BaseTool[TaskArgs, TaskResult, TaskConfig, TaskState],
    ToolUIData[TaskArgs, TaskResult],
):
    """Spawn an isolated sub-agent to perform a specific task.

    Sub-agents have their own message history and only return the result
    to the parent conversation, dramatically reducing token usage for
    complex multi-step operations.

    Use this tool when:
    - Exploring the codebase (type='explore')
    - Designing implementation plans (type='plan')
    - Executing complex multi-step tasks (type='task')
    """

    description: ClassVar[str] = (
        "Spawn an isolated sub-agent for a specific task. "
        "Use 'explore' type for read-only codebase exploration (grep, read_file). "
        "Use 'plan' type for designing implementation approaches. "
        "Use 'task' type for general multi-step operations with full tool access. "
        "Sub-agents have isolated message history - only results return to parent, "
        "dramatically reducing token usage."
    )

    # Parent context - injected by Agent after tool instantiation
    _parent_config: VibeConfig | None = None
    _parent_backend: BackendLike | None = None

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, TaskArgs):
            return ToolCallDisplay(summary="task")

        desc = event.args.description
        summary = f"task [{event.args.type}]: {desc[:50]}"
        if len(desc) > 50:
            summary += "..."

        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, TaskResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        status = "Success" if event.result.success else "Failed"
        message = f"{status}: {event.result.summary}"

        return ToolResultDisplay(success=event.result.success, message=message)

    @classmethod
    def get_status_text(cls) -> str:
        return "Running sub-agent"

    async def run(self, args: TaskArgs) -> TaskResult:
        """Execute the task in an isolated sub-agent."""
        if self._parent_config is None:
            raise ToolError(
                "Task tool not properly initialized. "
                "Parent agent context must be injected."
            )

        subagent_type = SubAgentType(args.type.value)

        runner = SubAgentRunner(
            parent_config=self._parent_config,
            backend=self._parent_backend,
        )

        self.state.active_tasks += 1
        try:
            result = await runner.run(
                task=args.description,
                subagent_type=subagent_type,
                custom_tools=args.tools,
            )
        finally:
            self.state.active_tasks -= 1
            self.state.total_tasks_run += 1

        return TaskResult(
            success=result.success,
            result=result.result,
            summary=result.summary,
            files_read=result.files_read,
            files_modified=result.files_modified,
            tokens_used=result.tokens_used,
        )
