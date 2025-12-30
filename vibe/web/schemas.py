from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel, Field


class WebMessageType(StrEnum):
    """WebSocket message types."""

    USER_MESSAGE = auto()
    ASSISTANT_CHUNK = auto()
    ASSISTANT_DONE = auto()
    TOOL_CALL = auto()
    TOOL_RESULT = auto()
    TOOL_APPROVAL_REQUEST = auto()
    TOOL_APPROVAL_RESPONSE = auto()
    REASONING = auto()
    ERROR = auto()
    SESSION_INFO = auto()
    COMPACT_START = auto()
    COMPACT_END = auto()
    AGENT_STATUS = auto()  # Status updates like "Thinking...", "Running tool..."


class ToolCallRecord(BaseModel):
    """Record of a tool call execution."""

    name: str
    id: str
    summary: str | None = None
    success: bool | None = None


class ChatMessage(BaseModel):
    """A single chat message."""

    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    tool_call: dict[str, Any] | None = None  # Deprecated, kept for compatibility
    tool_result: dict[str, Any] | None = None  # Deprecated, kept for compatibility
    tool_calls: list[ToolCallRecord] | None = None  # New: list of executed tools
    reasoning: str | None = None


class SessionSummary(BaseModel):
    """Summary of a session for listing."""

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    preview: str = ""


class SessionDetail(BaseModel):
    """Full session details including messages."""

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessage] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    mode: str = "default"  # Current agent mode


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    name: str | None = None
    mode: str = "default"  # "default", "plan", or "auto_approve"


class CreateSessionResponse(BaseModel):
    """Response after creating a session."""

    session_id: str
    name: str


class WebSocketMessage(BaseModel):
    """Generic WebSocket message."""

    type: WebMessageType
    data: dict[str, Any] = Field(default_factory=dict)


class AttachmentData(BaseModel):
    """A file attachment."""

    name: str
    type: str  # MIME type
    size: int
    data: str  # base64 encoded content


class UserMessageData(BaseModel):
    """Data for user message."""

    content: str = ""
    attachments: list[AttachmentData] = Field(default_factory=list)
    search_enabled: bool = False


class AssistantChunkData(BaseModel):
    """Data for streaming assistant response."""

    content: str
    done: bool = False


class ToolCallData(BaseModel):
    """Data for tool call preview."""

    id: str
    name: str
    arguments: dict[str, Any]
    requires_approval: bool = True
    summary: str | None = None  # Human-readable summary like "Running: ls -la"


class ToolResultData(BaseModel):
    """Data for tool result."""

    tool_call_id: str
    name: str
    result: str | None = None
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None
    duration: float | None = None
    summary: str | None = None
    full_result: str | None = None
    warnings: list[str] = Field(default_factory=list)
    success: bool | None = None


class ToolApprovalResponseData(BaseModel):
    """Data for tool approval response from client."""

    tool_call_id: str
    approved: bool
    always_allow: bool = False


class ErrorData(BaseModel):
    """Data for error message."""

    message: str
    code: str | None = None


class ConfigResponse(BaseModel):
    """Configuration response."""

    active_model: str
    models: list[dict[str, Any]]
    providers: list[str]
    tools: list[dict[str, Any]]


class ToolInfo(BaseModel):
    """Information about an available tool."""

    name: str
    description: str
    permission: str = "ask"


class SetModelRequest(BaseModel):
    """Request to set active model."""

    model: str


class RenameSessionRequest(BaseModel):
    """Request to rename a session."""

    name: str
