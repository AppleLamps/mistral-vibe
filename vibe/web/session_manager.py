from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
import uuid

from vibe.core.config import VibeConfig
from vibe.core.interaction_logger import InteractionLogger
from vibe.core.modes import AgentMode
from vibe.core.types import LLMMessage, Role
from vibe.web.schemas import ChatMessage, SessionDetail, SessionSummary

if TYPE_CHECKING:
    from vibe.core.agent import Agent

logger = logging.getLogger(__name__)

# Default session TTL: 24 hours
DEFAULT_SESSION_TTL_SECONDS = 24 * 60 * 60


class WebSession:
    """Represents an active web session with an agent."""

    def __init__(
        self,
        session_id: str,
        name: str,
        config: VibeConfig,
        mode: AgentMode = AgentMode.DEFAULT,
    ) -> None:
        self.session_id = session_id
        self.name = name
        self.config = config
        self.mode = mode
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.agent: Agent | None = None
        self.messages: list[LLMMessage] = []
        self.chat_messages: list[ChatMessage] = []
        # Pending approvals keyed by tool_call_id: (event, response)
        self._pending_approvals: dict[
            str, tuple[asyncio.Event, tuple[bool, bool] | None]
        ] = {}

    async def get_or_create_agent(self) -> Agent:
        """Get existing agent or create a new one."""
        if self.agent is None:
            from vibe.core.agent import Agent

            self.agent = Agent(self.config, mode=self.mode, enable_streaming=True)
            # Restore messages if any
            if self.messages:
                non_system = [m for m in self.messages if m.role != Role.system]
                self.agent.messages.extend(non_system)

        return self.agent

    def add_chat_message(self, message: ChatMessage) -> None:
        """Add a chat message to the session history."""
        self.chat_messages.append(message)
        self.updated_at = datetime.now()

    async def request_tool_approval(
        self, tool_call_id: str, timeout_seconds: float = 300.0
    ) -> tuple[bool, bool]:
        """Request approval for a tool call. Returns (approved, always_allow).

        Args:
            tool_call_id: The unique identifier for the tool call.
            timeout_seconds: Maximum time to wait for approval (default 5 minutes).

        Returns:
            Tuple of (approved, always_allow). Returns (False, False) on timeout.
        """
        event = asyncio.Event()
        self._pending_approvals[tool_call_id] = (event, None)

        try:
            # Wait for approval response with timeout
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            # Clean up on timeout and deny the request
            logger.warning(
                "Tool approval request timed out after %.1f seconds: %s",
                timeout_seconds,
                tool_call_id,
            )
            self._pending_approvals.pop(tool_call_id, None)
            return False, False

        # Get the response and clean up
        entry = self._pending_approvals.pop(tool_call_id, None)
        if entry is None or entry[1] is None:
            return False, False

        return entry[1]

    def respond_to_approval(
        self, tool_call_id: str, approved: bool, always_allow: bool = False
    ) -> None:
        """Respond to a pending approval request."""
        if tool_call_id not in self._pending_approvals:
            return

        event, _ = self._pending_approvals[tool_call_id]
        self._pending_approvals[tool_call_id] = (event, (approved, always_allow))
        event.set()

    def to_summary(self) -> SessionSummary:
        """Convert to session summary."""
        preview = ""
        if self.chat_messages:
            for msg in reversed(self.chat_messages):
                if msg.role == "user":
                    preview = msg.content[:100]
                    break

        return SessionSummary(
            id=self.session_id,
            name=self.name,
            created_at=self.created_at,
            updated_at=self.updated_at,
            message_count=len(self.chat_messages),
            preview=preview,
        )

    def to_detail(self) -> SessionDetail:
        """Convert to session detail."""
        stats = {}
        if self.agent:
            stats = self.agent.stats.model_dump()

        return SessionDetail(
            id=self.session_id,
            name=self.name,
            created_at=self.created_at,
            updated_at=self.updated_at,
            messages=self.chat_messages,
            stats=stats,
            mode=self.mode.value,
        )


class WebSessionManager:
    """Manages web sessions and integrates with CLI sessions."""

    _session_storage_warning_logged: bool = False

    def __init__(self, config: VibeConfig) -> None:
        self.config = config
        self._active_sessions: dict[str, WebSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self, name: str | None = None, mode: AgentMode = AgentMode.DEFAULT
    ) -> WebSession:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        if name is None:
            name = f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        session = WebSession(
            session_id=session_id, name=name, config=self.config, mode=mode
        )

        async with self._lock:
            self._active_sessions[session_id] = session

        return session

    async def get_session(self, session_id: str) -> WebSession | None:
        """Get an active session by ID."""
        return self._active_sessions.get(session_id)

    async def list_sessions(self) -> list[SessionSummary]:
        """List all sessions (active + saved)."""
        sessions: list[SessionSummary] = []

        # Add active sessions
        for session in self._active_sessions.values():
            sessions.append(session.to_summary())

        # Add saved sessions from disk
        saved_sessions = await self._load_saved_sessions()
        for saved in saved_sessions:
            # Skip if already in active sessions
            if saved.id not in self._active_sessions:
                sessions.append(saved)

        # Sort by updated_at descending
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    async def _load_saved_sessions(self) -> list[SessionSummary]:
        """Load session summaries from disk."""
        sessions: list[SessionSummary] = []
        save_dir = Path(self.config.session_logging.save_dir)

        if not save_dir.exists():
            return sessions

        pattern = f"{self.config.session_logging.session_prefix}_*.json"
        for filepath in save_dir.glob(pattern):
            try:
                summary = await self._parse_session_file(filepath)
                if summary:
                    sessions.append(summary)
            except Exception:
                continue

        return sessions

    async def _parse_session_file(self, filepath: Path) -> SessionSummary | None:
        """Parse a session file and return summary."""
        try:
            content = filepath.read_text(encoding="utf-8")
            data = json.loads(content)
            metadata = data.get("metadata", {})
            messages = data.get("messages", [])

            session_id = metadata.get("session_id", filepath.stem)
            start_time = metadata.get("start_time", "")
            end_time = metadata.get("end_time", start_time)

            # Get preview from last user message
            preview = ""
            for msg in reversed(messages):
                if msg.get("role") == "user" and msg.get("content"):
                    preview = str(msg["content"])[:100]
                    break

            created = (
                datetime.fromisoformat(start_time) if start_time else datetime.now()
            )
            updated = datetime.fromisoformat(end_time) if end_time else created

            return SessionSummary(
                id=session_id,
                name=f"Session {session_id[:8]}",
                created_at=created,
                updated_at=updated,
                message_count=len(messages),
                preview=preview,
            )
        except Exception:
            return None

    async def load_session(self, session_id: str) -> WebSession | None:
        """Load a session from disk into active sessions."""
        # Check if already active
        if session_id in self._active_sessions:
            return self._active_sessions[session_id]

        # Try to find session file
        session_file = InteractionLogger.find_session_by_id(
            session_id, self.config.session_logging
        )

        if not session_file:
            return None

        try:
            messages, metadata = InteractionLogger.load_session(session_file)

            session = WebSession(
                session_id=session_id,
                name=f"Session {session_id[:8]}",
                config=self.config,
            )
            session.messages = messages

            # Convert to chat messages
            for msg in messages:
                if msg.role == Role.system:
                    continue

                chat_msg = ChatMessage(
                    role=str(msg.role),
                    content=msg.content or "",
                    reasoning=msg.reasoning_content,
                )
                session.chat_messages.append(chat_msg)

            # Parse timestamps from metadata
            start_time = metadata.get("start_time")
            if start_time:
                session.created_at = datetime.fromisoformat(start_time)

            end_time = metadata.get("end_time")
            if end_time:
                session.updated_at = datetime.fromisoformat(end_time)

            async with self._lock:
                self._active_sessions[session_id] = session

            return session
        except Exception:
            return None

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        # Remove from active sessions
        async with self._lock:
            if session_id in self._active_sessions:
                del self._active_sessions[session_id]

        # Try to delete file
        session_file = InteractionLogger.find_session_by_id(
            session_id, self.config.session_logging
        )

        if session_file and session_file.exists():
            try:
                session_file.unlink()
            except Exception:
                pass

        return True

    async def save_session(self, session: WebSession) -> None:
        """Save a session to disk."""
        if not self.config.session_logging.enabled:
            return

        # One-time warning about unencrypted session storage
        if not WebSessionManager._session_storage_warning_logged:
            logger.warning(
                "Session data is stored as unencrypted JSON on disk. "
                "Avoid including sensitive information (API keys, credentials) in prompts."
            )
            WebSessionManager._session_storage_warning_logged = True

        if session.agent is None:
            return

        interaction_logger = InteractionLogger(
            session_config=self.config.session_logging,
            session_id=session.session_id,
            auto_approve=session.mode == AgentMode.AUTO_APPROVE,
        )

        await interaction_logger.save_interaction(
            messages=session.agent.messages,
            stats=session.agent.stats,
            config=self.config,
            tool_manager=session.agent.tool_manager,
        )

    async def cleanup_expired_sessions(
        self, ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS
    ) -> int:
        """Clean up sessions that haven't been accessed within the TTL.

        Args:
            ttl_seconds: Time-to-live in seconds. Sessions not accessed within
                this period will be removed.

        Returns:
            Number of sessions cleaned up.
        """
        now = datetime.now()
        cutoff = now - timedelta(seconds=ttl_seconds)
        cleaned = 0

        async with self._lock:
            expired_ids = [
                session_id
                for session_id, session in self._active_sessions.items()
                if session.updated_at < cutoff
            ]

            for session_id in expired_ids:
                session = self._active_sessions.pop(session_id)
                # Try to save before cleanup
                try:
                    await self.save_session(session)
                except Exception as e:
                    logger.warning(
                        "Failed to save session %s before cleanup: %s", session_id, e
                    )
                cleaned += 1
                logger.info("Cleaned up expired session: %s", session_id)

        return cleaned

    async def start_cleanup_task(
        self,
        interval_seconds: int = 3600,
        ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> asyncio.Task[None]:
        """Start a background task to periodically clean up expired sessions.

        Args:
            interval_seconds: How often to run cleanup (default: 1 hour).
            ttl_seconds: Session TTL (default: 24 hours).

        Returns:
            The cleanup task.
        """

        async def cleanup_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    cleaned = await self.cleanup_expired_sessions(ttl_seconds)
                    if cleaned > 0:
                        logger.info(
                            "Session cleanup: removed %d expired sessions", cleaned
                        )
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Session cleanup error: %s", e)

        return asyncio.create_task(cleanup_loop())
