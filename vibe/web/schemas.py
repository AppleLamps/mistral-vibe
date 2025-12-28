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


class ChatMessage(BaseModel):
    """A single chat message."""

    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    tool_call: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
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


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    name: str | None = None


class CreateSessionResponse(BaseModel):
    """Response after creating a session."""

    session_id: str
    name: str


class WebSocketMessage(BaseModel):
    """Generic WebSocket message."""

    type: WebMessageType
    data: dict[str, Any] = Field(default_factory=dict)


class UserMessageData(BaseModel):
    """Data for user message."""

    content: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)


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
    preview: str | None = None


class ToolResultData(BaseModel):
    """Data for tool result."""

    tool_call_id: str
    name: str
    result: str | None = None
    error: str | None = None
    skipped: bool = False
    duration: float | None = None


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
