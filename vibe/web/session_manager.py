from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
import uuid

from vibe.core.config import VibeConfig
from vibe.core.interaction_logger import InteractionLogger
from vibe.core.modes import AgentMode
from vibe.core.types import AgentStats, LLMMessage, Role
from vibe.web.schemas import ChatMessage, SessionDetail, SessionSummary

if TYPE_CHECKING:
    from vibe.core.agent import Agent


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
        self._approval_event: asyncio.Event | None = None
        self._approval_response: tuple[bool, bool] | None = None  # (approved, always)

    async def get_or_create_agent(self) -> Agent:
        """Get existing agent or create a new one."""
        if self.agent is None:
            from vibe.core.agent import Agent

            self.agent = Agent(
                self.config,
                mode=self.mode,
                enable_streaming=True,
            )
            # Restore messages if any
            if self.messages:
                non_system = [m for m in self.messages if m.role != Role.system]
                self.agent.messages.extend(non_system)

        return self.agent

    def add_chat_message(self, message: ChatMessage) -> None:
        """Add a chat message to the session history."""
        self.chat_messages.append(message)
        self.updated_at = datetime.now()

    async def request_tool_approval(self, tool_call_id: str) -> tuple[bool, bool]:
        """Request approval for a tool call. Returns (approved, always_allow)."""
        self._approval_event = asyncio.Event()
        self._approval_response = None

        # Wait for approval response
        await self._approval_event.wait()

        if self._approval_response is None:
            return False, False

        return self._approval_response

    def respond_to_approval(self, approved: bool, always_allow: bool = False) -> None:
        """Respond to a pending approval request."""
        self._approval_response = (approved, always_allow)
        if self._approval_event:
            self._approval_event.set()

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
        )


class WebSessionManager:
    """Manages web sessions and integrates with CLI sessions."""

    def __init__(self, config: VibeConfig) -> None:
        self.config = config
        self._active_sessions: dict[str, WebSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        name: str | None = None,
        mode: AgentMode = AgentMode.DEFAULT,
    ) -> WebSession:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        if name is None:
            name = f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        session = WebSession(
            session_id=session_id,
            name=name,
            config=self.config,
            mode=mode,
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

            created = datetime.fromisoformat(start_time) if start_time else datetime.now()
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

        if session.agent is None:
            return

        logger = InteractionLogger(
            session_config=self.config.session_logging,
            session_id=session.session_id,
            auto_approve=session.mode == AgentMode.AUTO_APPROVE,
        )

        await logger.save_interaction(
            messages=session.agent.messages,
            stats=session.agent.stats,
            config=self.config,
            tool_manager=session.agent.tool_manager,
        )
