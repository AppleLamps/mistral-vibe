from __future__ import annotations

"""Tests for the web session manager."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from vibe.web.schemas import ChatMessage
from vibe.web.session_manager import WebSession, WebSessionManager


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock config."""
    config = MagicMock()
    config.session_logging.enabled = False
    config.session_logging.save_dir = "/tmp/vibe-sessions"
    config.session_logging.session_prefix = "vibe"
    return config


@pytest.fixture
def session_manager(mock_config: MagicMock) -> WebSessionManager:
    """Create a session manager with mock config."""
    return WebSessionManager(mock_config)


class TestWebSession:
    """Tests for WebSession class."""

    def test_creates_session_with_id(self, mock_config: MagicMock) -> None:
        """Session should have unique ID."""
        session = WebSession(
            session_id="test-123", name="Test Session", config=mock_config
        )
        assert session.session_id == "test-123"
        assert session.name == "Test Session"

    def test_tracks_timestamps(self, mock_config: MagicMock) -> None:
        """Session should track created and updated timestamps."""
        session = WebSession(
            session_id="test-123", name="Test Session", config=mock_config
        )
        assert session.created_at is not None
        assert session.updated_at is not None

    def test_adds_chat_messages(self, mock_config: MagicMock) -> None:
        """Session should track chat messages."""
        session = WebSession(
            session_id="test-123", name="Test Session", config=mock_config
        )
        msg = ChatMessage(role="user", content="Hello")
        session.add_chat_message(msg)
        assert len(session.chat_messages) == 1
        assert session.chat_messages[0].content == "Hello"

    def test_updates_timestamp_on_message(self, mock_config: MagicMock) -> None:
        """Adding message should update timestamp."""
        session = WebSession(
            session_id="test-123", name="Test Session", config=mock_config
        )
        original_updated = session.updated_at
        msg = ChatMessage(role="user", content="Hello")
        session.add_chat_message(msg)
        assert session.updated_at >= original_updated

    def test_to_summary(self, mock_config: MagicMock) -> None:
        """Should convert to summary format."""
        session = WebSession(
            session_id="test-123", name="Test Session", config=mock_config
        )
        msg = ChatMessage(role="user", content="Hello world")
        session.add_chat_message(msg)

        summary = session.to_summary()
        assert summary.id == "test-123"
        assert summary.name == "Test Session"
        assert summary.message_count == 1
        assert "Hello" in summary.preview

    def test_to_detail(self, mock_config: MagicMock) -> None:
        """Should convert to detail format."""
        session = WebSession(
            session_id="test-123", name="Test Session", config=mock_config
        )
        msg = ChatMessage(role="user", content="Hello")
        session.add_chat_message(msg)

        detail = session.to_detail()
        assert detail.id == "test-123"
        assert detail.name == "Test Session"
        assert len(detail.messages) == 1


class TestToolApproval:
    """Tests for tool approval mechanism."""

    @pytest.mark.asyncio
    async def test_request_and_respond_approval(self, mock_config: MagicMock) -> None:
        """Should handle tool approval request and response."""
        session = WebSession(
            session_id="test-123", name="Test Session", config=mock_config
        )

        # Start approval request in background
        async def request_approval() -> tuple[bool, bool]:
            return await session.request_tool_approval("tool-call-1")

        task = asyncio.create_task(request_approval())

        # Give the request time to set up
        await asyncio.sleep(0.01)

        # Respond to approval
        session.respond_to_approval("tool-call-1", approved=True, always_allow=False)

        # Get result
        approved, always_allow = await task
        assert approved is True
        assert always_allow is False

    @pytest.mark.asyncio
    async def test_respond_to_nonexistent_approval(
        self, mock_config: MagicMock
    ) -> None:
        """Responding to nonexistent approval should be safe."""
        session = WebSession(
            session_id="test-123", name="Test Session", config=mock_config
        )
        # Should not raise
        session.respond_to_approval("nonexistent", approved=True)


class TestWebSessionManager:
    """Tests for WebSessionManager class."""

    @pytest.mark.asyncio
    async def test_creates_session(self, session_manager: WebSessionManager) -> None:
        """Should create a new session."""
        session = await session_manager.create_session(name="Test")
        assert session.name == "Test"
        assert session.session_id is not None

    @pytest.mark.asyncio
    async def test_creates_session_with_default_name(
        self, session_manager: WebSessionManager
    ) -> None:
        """Should create session with default name if not provided."""
        session = await session_manager.create_session()
        assert "Chat" in session.name

    @pytest.mark.asyncio
    async def test_gets_session(self, session_manager: WebSessionManager) -> None:
        """Should get existing session by ID."""
        session = await session_manager.create_session(name="Test")
        retrieved = await session_manager.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_session(
        self, session_manager: WebSessionManager
    ) -> None:
        """Should return None for unknown session ID."""
        retrieved = await session_manager.get_session("nonexistent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_lists_sessions(self, session_manager: WebSessionManager) -> None:
        """Should list all active sessions."""
        await session_manager.create_session(name="Session 1")
        await session_manager.create_session(name="Session 2")

        sessions = await session_manager.list_sessions()
        assert len(sessions) >= 2
        names = [s.name for s in sessions]
        assert "Session 1" in names
        assert "Session 2" in names

    @pytest.mark.asyncio
    async def test_deletes_session(self, session_manager: WebSessionManager) -> None:
        """Should delete session."""
        session = await session_manager.create_session(name="To Delete")
        session_id = session.session_id

        success = await session_manager.delete_session(session_id)
        assert success is True

        retrieved = await session_manager.get_session(session_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(
        self, session_manager: WebSessionManager
    ) -> None:
        """Should clean up expired sessions."""
        # Create a session
        session = await session_manager.create_session(name="Old Session")

        # Manually set it to be expired (1 hour ago)
        session.updated_at = datetime.now() - timedelta(hours=2)

        # Run cleanup with 1 hour TTL
        cleaned = await session_manager.cleanup_expired_sessions(ttl_seconds=3600)
        assert cleaned >= 1

        # Session should be removed
        retrieved = await session_manager.get_session(session.session_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_cleanup_preserves_active_sessions(
        self, session_manager: WebSessionManager
    ) -> None:
        """Should preserve recently active sessions."""
        # Create a session
        session = await session_manager.create_session(name="Active Session")

        # Run cleanup with 1 hour TTL
        await session_manager.cleanup_expired_sessions(ttl_seconds=3600)

        # Session should still exist
        retrieved = await session_manager.get_session(session.session_id)
        assert retrieved is not None
