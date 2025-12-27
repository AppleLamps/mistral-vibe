"""Sub-agent runner for isolated task execution."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from vibe.core.modes import AgentMode
from vibe.core.subagent.result import SubAgentResult
from vibe.core.subagent.types import SUBAGENT_CONFIGS, SubAgentType

if TYPE_CHECKING:
    from vibe.core.config import VibeConfig
    from vibe.core.llm.types import BackendLike

logger = logging.getLogger(__name__)


class SubAgentRunner:
    """Runs isolated sub-agents for specific tasks.

    Sub-agents have their own message history and only return results to the parent,
    dramatically reducing token usage for multi-step operations.
    """

    def __init__(
        self,
        parent_config: VibeConfig,
        backend: BackendLike | None = None,
    ) -> None:
        self.parent_config = parent_config
        self.backend = backend

    def _create_subagent_config(
        self,
        subagent_type: SubAgentType,
        custom_tools: list[str] | None = None,
    ) -> VibeConfig:
        """Create a VibeConfig for the sub-agent with restricted tools."""
        from vibe.core.config import VibeConfig

        subagent_cfg = SUBAGENT_CONFIGS[subagent_type]

        # Determine tools to enable
        # Always exclude "task" tool to prevent recursive sub-agent spawning
        base_tools = custom_tools or subagent_cfg.enabled_tools
        if base_tools:
            tools_to_enable = [t for t in base_tools if t != "task"]
        else:
            # If no tool restrictions, use disabled_tools to block task
            tools_to_enable = []

        # Create config dict with overrides
        config_overrides: dict = {
            "workdir": self.parent_config.workdir,
            "include_project_context": subagent_cfg.include_project_context,
            "system_prompt_id": "subagent",  # Use sub-agent specific prompt
        }

        # Apply tool restrictions
        if tools_to_enable:
            config_overrides["enabled_tools"] = tools_to_enable
        else:
            # Block task tool to prevent infinite recursion
            config_overrides["disabled_tools"] = ["task"]

        # Load config with overrides
        return VibeConfig.load(
            workdir=self.parent_config.workdir,
            **config_overrides,
        )

    async def run(
        self,
        task: str,
        subagent_type: SubAgentType = SubAgentType.TASK,
        custom_tools: list[str] | None = None,
    ) -> SubAgentResult:
        """Execute a task in an isolated sub-agent.

        Args:
            task: The task description for the sub-agent to perform.
            subagent_type: Type of sub-agent (EXPLORE, PLAN, TASK).
            custom_tools: Optional list of specific tools to enable.

        Returns:
            SubAgentResult with the outcome of the sub-agent's work.
        """
        from vibe.core.agent import Agent
        from vibe.core.types import AssistantEvent, ToolResultEvent

        subagent_cfg = SUBAGENT_CONFIGS[subagent_type]
        config = self._create_subagent_config(subagent_type, custom_tools)

        # Determine mode based on sub-agent type
        mode = AgentMode.AUTO_APPROVE if subagent_cfg.auto_approve else AgentMode.DEFAULT

        # Create isolated agent with fresh message history
        agent = Agent(
            config=config,
            mode=mode,
            max_turns=subagent_cfg.max_turns,
            backend=self.backend,
            enable_streaming=False,  # No streaming for sub-agents
        )

        # Track results
        files_read: set[str] = set()
        files_modified: set[str] = set()
        errors: list[str] = []
        final_response = ""

        try:
            async for event in agent.act(task):
                if isinstance(event, AssistantEvent):
                    final_response = event.content
                elif isinstance(event, ToolResultEvent):
                    # Track file operations from tool results
                    if event.result:
                        result_dict = event.result.model_dump()
                        path = result_dict.get("path")
                        if path:
                            if event.tool_name in ("write_file", "search_replace"):
                                files_modified.add(str(path))
                            elif event.tool_name == "read_file":
                                files_read.add(str(path))
                    if event.error:
                        errors.append(f"{event.tool_name}: {event.error}")

        except asyncio.CancelledError:
            return SubAgentResult(
                success=False,
                result="Sub-agent was cancelled",
                summary="Execution cancelled",
                errors=["CancelledError"],
            )
        except Exception as e:
            logger.exception("Sub-agent execution failed")
            errors.append(str(e))
            return SubAgentResult(
                success=False,
                result=f"Sub-agent failed: {e}",
                summary=f"Error during {subagent_type.value} execution",
                files_read=list(files_read),
                files_modified=list(files_modified),
                errors=errors,
            )

        return SubAgentResult(
            success=True,
            result=final_response,
            summary=self._generate_summary(agent.stats, files_read, files_modified),
            files_read=list(files_read),
            files_modified=list(files_modified),
            tokens_used=agent.stats.session_total_llm_tokens,
            steps_taken=agent.stats.steps,
            errors=errors,
        )

    def _generate_summary(
        self,
        stats,
        files_read: set[str],
        files_modified: set[str],
    ) -> str:
        """Generate a brief summary of sub-agent activity."""
        parts = []

        if files_read:
            parts.append(f"Read {len(files_read)} file(s)")
        if files_modified:
            parts.append(f"Modified {len(files_modified)} file(s)")
        parts.append(f"Used {stats.session_total_llm_tokens} tokens in {stats.steps} steps")

        return ". ".join(parts)

    async def run_parallel(
        self,
        tasks: list[tuple[str, SubAgentType]],
        max_concurrent: int = 3,
    ) -> list[SubAgentResult]:
        """Execute multiple sub-agents in parallel.

        Args:
            tasks: List of (task_description, subagent_type) tuples.
            max_concurrent: Maximum number of concurrent sub-agents.

        Returns:
            List of SubAgentResults in the same order as input tasks.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def run_with_semaphore(
            task: str, subagent_type: SubAgentType
        ) -> SubAgentResult:
            async with semaphore:
                return await self.run(task, subagent_type)

        results = await asyncio.gather(
            *[run_with_semaphore(task, stype) for task, stype in tasks],
            return_exceptions=True,
        )

        # Convert exceptions to failed results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    SubAgentResult(
                        success=False,
                        result=f"Sub-agent failed: {result}",
                        summary=f"Exception in parallel task {i}",
                        errors=[str(result)],
                    )
                )
            else:
                final_results.append(result)

        return final_results
