from __future__ import annotations

import asyncio
from datetime import datetime
import getpass
import json
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Any

import aiofiles

from vibe.core.llm.format import get_active_tool_classes
from vibe.core.system_prompt import ProjectContextProvider
from vibe.core.types import AgentStats, LLMMessage, SessionInfo, SessionMetadata
from vibe.core.utils import is_windows, run_sync

if TYPE_CHECKING:
    from vibe.core.config import SessionLoggingConfig, VibeConfig
    from vibe.core.tools.manager import ToolManager


class InteractionLogger:
    def __init__(
        self,
        session_config: SessionLoggingConfig,
        session_id: str,
        auto_approve: bool = False,
        workdir: Path | None = None,
    ) -> None:
        if workdir is None:
            workdir = Path.cwd()
        self.session_config = session_config
        self.enabled = session_config.enabled
        self.auto_approve = auto_approve
        self.workdir = workdir
        self._context_snapshot: str | None = None

        if not self.enabled:
            self.save_dir: Path | None = None
            self.session_prefix: str | None = None
            self.session_id: str = "disabled"
            self.session_start_time: str = "N/A"
            self.filepath: Path | None = None
            self.session_metadata: SessionMetadata | None = None
            return

        self.save_dir = Path(session_config.save_dir)
        self.session_prefix = session_config.session_prefix
        self.session_id = session_id
        self.session_start_time = datetime.now().isoformat()

        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.filepath = self._get_save_filepath()
        self.session_metadata = self._initialize_session_metadata()

    def _get_save_filepath(self) -> Path:
        if self.save_dir is None or self.session_prefix is None:
            raise RuntimeError("Cannot get filepath when logging is disabled")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.session_prefix}_{timestamp}_{self.session_id[:8]}.json"
        return self.save_dir / filename

    async def _run_git_command_async(
        self, args: list[str], timeout: float = 5.0
    ) -> str | None:
        """Run a git command asynchronously and return output or None.

        Optimized helper for concurrent git operations.
        """
        try:
            if is_windows():
                process = await asyncio.create_subprocess_exec(
                    "git",
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.DEVNULL,
                    cwd=self.workdir,
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    "git",
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.workdir,
                )

            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            if process.returncode == 0 and stdout:
                return stdout.decode("utf-8", errors="ignore").strip()
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            pass
        return None

    async def _get_git_metadata_async(self) -> tuple[str | None, str | None]:
        """Get git commit and branch concurrently.

        Optimized to run 2 git commands in parallel instead of sequentially.
        Reduces initialization time from sum(both_commands) to max(slowest_command).
        """
        results = await asyncio.gather(
            self._run_git_command_async(["rev-parse", "HEAD"]),
            self._run_git_command_async(["rev-parse", "--abbrev-ref", "HEAD"]),
            return_exceptions=True,
        )

        git_commit = results[0] if not isinstance(results[0], Exception) else None
        git_branch = results[1] if not isinstance(results[1], Exception) else None

        return git_commit, git_branch

    def _get_username(self) -> str:
        try:
            return getpass.getuser()
        except Exception:
            return "unknown"

    def _initialize_session_metadata(self) -> SessionMetadata:
        """Initialize session metadata with git information.

        Runs git commands concurrently for faster initialization.
        """
        # Get git metadata concurrently
        try:
            git_commit, git_branch = run_sync(self._get_git_metadata_async())
        except Exception:
            git_commit, git_branch = None, None

        user_name = self._get_username()

        return SessionMetadata(
            session_id=self.session_id,
            start_time=self.session_start_time,
            end_time=None,
            git_commit=git_commit,
            git_branch=git_branch,
            auto_approve=self.auto_approve,
            username=user_name,
            environment={"working_directory": str(self.workdir)},
        )

    def _build_agent_config(self, config: VibeConfig) -> dict[str, Any]:
        cfg = config.model_dump(mode="json")

        if not self.session_config.include_providers:
            cfg.pop("providers", None)
        elif self.session_config.redact_env_vars:
            for provider in cfg.get("providers", []):
                if isinstance(provider, dict) and "api_key_env_var" in provider:
                    provider["api_key_env_var"] = "<redacted>"

        if not self.session_config.include_tools:
            cfg.pop("tools", None)

        return cfg

    def _ensure_context_snapshot(self, config: VibeConfig) -> None:
        if not self.session_config.include_context_snapshot:
            return
        if self._context_snapshot is not None:
            return

        try:
            provider = ProjectContextProvider(
                config=config.project_context, root_path=config.effective_workdir
            )
            self._context_snapshot = provider.get_full_context()
        except Exception:
            self._context_snapshot = None

    async def save_interaction(
        self,
        messages: list[LLMMessage],
        stats: AgentStats,
        config: VibeConfig,
        tool_manager: ToolManager,
    ) -> str | None:
        if not self.enabled or self.filepath is None:
            return None

        if self.session_metadata is None:
            return None

        tools_available: list[dict[str, Any]] = []
        if self.session_config.include_tools:
            active_tools = get_active_tool_classes(tool_manager, config)
            tools_available = [
                {
                    "type": "function",
                    "function": {
                        "name": tool_class.get_name(),
                        "description": tool_class.description,
                        "parameters": tool_class.get_parameters(),
                    },
                }
                for tool_class in active_tools
            ]

        metadata = {
            **self.session_metadata.model_dump(),
            "end_time": datetime.now().isoformat(),
            "stats": stats.model_dump(),
            "total_messages": len(messages),
            "agent_config": self._build_agent_config(config),
        }

        self._ensure_context_snapshot(config)
        if self._context_snapshot:
            metadata["context_snapshot"] = self._context_snapshot

        if tools_available:
            metadata["tools_available"] = tools_available

        interaction_data = {
            "metadata": metadata,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }

        try:
            json_content = json.dumps(interaction_data, indent=2, ensure_ascii=False)

            async with aiofiles.open(
                self.filepath,
                "w",
                encoding="utf-8",
                buffering=self.session_config.write_buffer_bytes,
            ) as f:
                await f.write(json_content)

            return str(self.filepath)
        except Exception:
            return None

    def reset_session(self, session_id: str) -> None:
        if not self.enabled:
            return

        self.session_id = session_id
        self.session_start_time = datetime.now().isoformat()
        self.filepath = self._get_save_filepath()
        self.session_metadata = self._initialize_session_metadata()

    def get_session_info(
        self, messages: list[dict[str, Any]], stats: AgentStats
    ) -> SessionInfo:
        if not self.enabled or self.save_dir is None:
            return SessionInfo(
                session_id="disabled",
                start_time="N/A",
                message_count=len(messages),
                stats=stats,
                save_dir="N/A",
            )

        return SessionInfo(
            session_id=self.session_id,
            start_time=self.session_start_time,
            message_count=len(messages),
            stats=stats,
            save_dir=str(self.save_dir),
        )

    @staticmethod
    def find_latest_session(config: SessionLoggingConfig) -> Path | None:
        save_dir = Path(config.save_dir)
        if not save_dir.exists():
            return None

        pattern = f"{config.session_prefix}_*.json"
        session_files = list(save_dir.glob(pattern))

        if not session_files:
            return None

        return max(session_files, key=lambda p: p.stat().st_mtime)

    @staticmethod
    def find_session_by_id(
        session_id: str, config: SessionLoggingConfig
    ) -> Path | None:
        save_dir = Path(config.save_dir)
        if not save_dir.exists():
            return None

        # If it's a full UUID, extract the short form (first 8 chars)
        short_id = session_id.split("-")[0] if "-" in session_id else session_id

        # Try exact match first, then partial
        patterns = [
            f"{config.session_prefix}_*_{short_id}.json",  # Exact short UUID
            f"{config.session_prefix}_*_{short_id}*.json",  # Partial UUID
        ]

        for pattern in patterns:
            matches = list(save_dir.glob(pattern))
            if matches:
                return (
                    max(matches, key=lambda p: p.stat().st_mtime)
                    if len(matches) > 1
                    else matches[0]
                )

        return None

    @staticmethod
    def load_session(filepath: Path) -> tuple[list[LLMMessage], dict[str, Any]]:
        with filepath.open("r", encoding="utf-8") as f:
            content = f.read()

        data = json.loads(content)
        messages = [LLMMessage.model_validate(msg) for msg in data.get("messages", [])]
        metadata = data.get("metadata", {})

        return messages, metadata
