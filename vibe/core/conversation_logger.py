"""Human-readable conversation logger for debugging agent behavior."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vibe.core.types import AgentStats


class ConversationLogger:
    """Logs conversations to human-readable .txt files for debugging and review.

    Creates a .vibe_logs/ folder in the working directory and writes one log
    file per conversation session with timestamps, messages, tool calls, and results.
    """

    LOG_DIR_NAME = ".vibe_logs"

    def __init__(
        self,
        workdir: Path,
        session_id: str,
        enabled: bool = True,
    ) -> None:
        self.workdir = workdir
        self.session_id = session_id
        self.enabled = enabled
        self.start_time = datetime.now()
        self.filepath: Path | None = None
        self._initialized = False
        self._lock = threading.Lock()

    def _get_log_dir(self) -> Path:
        """Get the log directory path."""
        return self.workdir / self.LOG_DIR_NAME

    def _get_log_filepath(self) -> Path:
        """Generate unique log filename with timestamp and session ID."""
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        short_id = self.session_id[:8]
        filename = f"conversation_{timestamp}_{short_id}.txt"
        return self._get_log_dir() / filename

    def _get_timestamp(self) -> str:
        """Get current time formatted for log entries."""
        return datetime.now().strftime("%H:%M:%S")

    def _ensure_initialized(self) -> None:
        """Initialize log file with header on first write."""
        if self._initialized or not self.enabled:
            return

        with self._lock:
            # Double-check after acquiring lock
            if self._initialized:
                return

            log_dir = self._get_log_dir()
            log_dir.mkdir(parents=True, exist_ok=True)

            self.filepath = self._get_log_filepath()

            separator = "=" * 80
            header = (
                f"{separator}\n"
                "VIBE CONVERSATION LOG\n"
                f"Session ID: {self.session_id[:8]}\n"
                f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Working Directory: {self.workdir}\n"
                f"{separator}\n\n"
            )

            with open(self.filepath, "w", encoding="utf-8") as f:
                f.write(header)

            self._initialized = True

    def _append(self, content: str) -> None:
        """Append content to the log file."""
        if not self.enabled or self.filepath is None:
            return

        with self._lock:
            try:
                with open(self.filepath, "a", encoding="utf-8") as f:
                    f.write(content)
            except OSError:
                # Silently fail - logging should not break the agent
                pass

    async def log_user_message(self, content: str) -> None:
        """Log a user message with timestamp."""
        if not self.enabled:
            return

        self._ensure_initialized()

        separator = "-" * 80
        entry = (
            f"[{self._get_timestamp()}] USER:\n"
            f"{content}\n\n"
            f"{separator}\n"
        )
        self._append(entry)

    async def log_assistant_message(self, content: str) -> None:
        """Log an assistant response with timestamp."""
        if not self.enabled or not content.strip():
            return

        self._ensure_initialized()

        separator = "-" * 80
        entry = (
            f"[{self._get_timestamp()}] ASSISTANT:\n"
            f"{content}\n\n"
            f"{separator}\n"
        )
        self._append(entry)

    async def log_reasoning(self, content: str) -> None:
        """Log reasoning/thinking content."""
        if not self.enabled or not content.strip():
            return

        self._ensure_initialized()

        separator = "-" * 80
        entry = (
            f"[{self._get_timestamp()}] REASONING:\n"
            f"{content}\n\n"
            f"{separator}\n"
        )
        self._append(entry)

    async def log_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        tool_call_id: str,
    ) -> None:
        """Log a tool call with its arguments."""
        if not self.enabled:
            return

        self._ensure_initialized()

        # Format arguments nicely
        args_lines = []
        for key, value in args.items():
            # Truncate very long values
            str_value = str(value)
            if len(str_value) > 500:
                str_value = str_value[:500] + "... [truncated]"
            args_lines.append(f"    {key}: {str_value}")

        args_str = "\n".join(args_lines) if args_lines else "    (no arguments)"

        entry = (
            f"[{self._get_timestamp()}] TOOL CALL: {tool_name} (id: {tool_call_id[:12]})\n"
            f"  Arguments:\n"
            f"{args_str}\n\n"
        )
        self._append(entry)

    async def log_tool_result(
        self,
        tool_name: str,
        result: str | None,
        error: str | None,
        skipped: bool,
        skip_reason: str | None = None,
        duration: float | None = None,
    ) -> None:
        """Log a tool result or error."""
        if not self.enabled:
            return

        self._ensure_initialized()

        separator = "-" * 80
        duration_str = f" ({duration:.2f}s)" if duration else ""

        if skipped:
            reason = skip_reason or "user rejected"
            entry = (
                f"[{self._get_timestamp()}] TOOL SKIPPED: {tool_name}{duration_str}\n"
                f"  Reason: {reason}\n\n"
                f"{separator}\n"
            )
        elif error:
            entry = (
                f"[{self._get_timestamp()}] TOOL ERROR: {tool_name}{duration_str}\n"
                f"  Error: {error}\n\n"
                f"{separator}\n"
            )
        else:
            # Truncate very long results
            result_str = str(result) if result else "(no output)"
            if len(result_str) > 2000:
                result_str = result_str[:2000] + "\n... [truncated]"

            entry = (
                f"[{self._get_timestamp()}] TOOL RESULT: {tool_name}{duration_str}\n"
                f"  Success: True\n"
                f"  Result:\n{_indent(result_str, 4)}\n\n"
                f"{separator}\n"
            )

        self._append(entry)

    async def log_session_end(self, stats: AgentStats) -> None:
        """Log session summary with stats."""
        if not self.enabled:
            return

        self._ensure_initialized()

        separator = "=" * 80
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        summary = (
            f"\n{separator}\n"
            f"SESSION ENDED: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Duration: {duration:.1f} seconds\n"
            f"Total Steps: {stats.steps}\n"
            f"Tool Calls: {stats.tool_calls_succeeded} succeeded, "
            f"{stats.tool_calls_failed} failed, "
            f"{stats.tool_calls_rejected} rejected\n"
            f"Tokens: {stats.session_prompt_tokens:,} prompt, "
            f"{stats.session_completion_tokens:,} completion\n"
            f"Estimated Cost: ${stats.session_cost:.4f}\n"
            f"{separator}\n"
        )
        self._append(summary)

    def reset_session(self, session_id: str) -> None:
        """Reset for a new session."""
        self.session_id = session_id
        self.start_time = datetime.now()
        self.filepath = None
        self._initialized = False
        self._lock = threading.Lock()


def _indent(text: str, spaces: int) -> str:
    """Indent all lines of text by the specified number of spaces."""
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.split("\n"))
