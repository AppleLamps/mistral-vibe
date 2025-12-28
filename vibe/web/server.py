from __future__ import annotations

import asyncio
import base64
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vibe.core.config import VibeConfig, load_api_keys_from_env
from vibe.core.modes import AgentMode
from vibe.core.types import (
    ApprovalResponse,
    AssistantEvent,
    CompactEndEvent,
    CompactStartEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from vibe.web.schemas import (
    AttachmentData,
    ChatMessage,
    ConfigResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    ErrorData,
    RenameSessionRequest,
    SessionDetail,
    SessionSummary,
    SetModelRequest,
    ToolApprovalResponseData,
    ToolInfo,
    UserMessageData,
    WebMessageType,
    WebSocketMessage,
)
from vibe.web.session_manager import WebSession, WebSessionManager

# Global state
_session_manager: WebSessionManager | None = None
_api_key: str | None = None


# Simple in-memory rate limiter
class RateLimiter:
    """Simple in-memory rate limiter using token bucket algorithm."""

    def __init__(self, requests_per_minute: int = 60) -> None:
        self.requests_per_minute = requests_per_minute
        self.requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        """Check if request is allowed for the given client."""
        now = time.time()
        minute_ago = now - 60

        # Clean old requests
        self.requests[client_ip] = [
            t for t in self.requests[client_ip] if t > minute_ago
        ]

        # Check limit
        if len(self.requests[client_ip]) >= self.requests_per_minute:
            return False

        self.requests[client_ip].append(now)
        return True


_rate_limiter = RateLimiter(requests_per_minute=120)


def get_session_manager() -> WebSessionManager:
    """Get the global session manager."""
    global _session_manager
    if _session_manager is None:
        load_api_keys_from_env()
        config = VibeConfig.load()
        _session_manager = WebSessionManager(config)
    return _session_manager


def create_app(api_key: str | None = None) -> FastAPI:
    """Create the FastAPI application."""
    global _api_key
    _api_key = api_key

    app = FastAPI(
        title="Mistral Vibe Web",
        description="Web interface for Mistral Vibe coding assistant",
        version="1.0.0",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting middleware
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next: Any) -> Any:
        # Skip rate limiting for static files
        if request.url.path.startswith("/static"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        if not _rate_limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests. Please slow down."},
            )
        return await call_next(request)

    # Static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Register routes
    register_routes(app)

    return app


def register_routes(app: FastAPI) -> None:
    """Register all routes."""

    @app.get("/", response_class=HTMLResponse)
    async def index() -> FileResponse:
        """Serve the main HTML page."""
        static_dir = Path(__file__).parent / "static"
        return FileResponse(static_dir / "index.html")

    @app.get("/api/sessions", response_model=list[SessionSummary])
    async def list_sessions() -> list[SessionSummary]:
        """List all sessions."""
        manager = get_session_manager()
        return await manager.list_sessions()

    @app.post("/api/sessions", response_model=CreateSessionResponse)
    async def create_session(request: CreateSessionRequest) -> CreateSessionResponse:
        """Create a new session."""
        manager = get_session_manager()
        session = await manager.create_session(name=request.name)
        return CreateSessionResponse(
            session_id=session.session_id,
            name=session.name,
        )

    @app.get("/api/sessions/{session_id}", response_model=SessionDetail)
    async def get_session(session_id: str) -> SessionDetail:
        """Get session details."""
        manager = get_session_manager()
        session = await manager.get_session(session_id)
        if not session:
            session = await manager.load_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.to_detail()

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, bool]:
        """Delete a session."""
        manager = get_session_manager()
        success = await manager.delete_session(session_id)
        return {"success": success}

    @app.get("/api/config", response_model=ConfigResponse)
    async def get_config() -> ConfigResponse:
        """Get current configuration."""
        manager = get_session_manager()
        config = manager.config

        models = []
        for model in config.models:
            models.append({
                "name": model.name,
                "alias": model.alias,
                "provider": model.provider,
            })

        providers = [p.name for p in config.providers]

        tools = []
        for name, tool_config in config.tools.items():
            tools.append({
                "name": name,
                "permission": tool_config.permission,
            })

        return ConfigResponse(
            active_model=config.active_model,
            models=models,
            providers=providers,
            tools=tools,
        )

    @app.get("/api/tools", response_model=list[ToolInfo])
    async def list_tools() -> list[ToolInfo]:
        """List available tools."""
        manager = get_session_manager()

        # Create a temporary agent to get tool info
        session = await manager.create_session(name="temp")
        agent = await session.get_or_create_agent()

        tools = []
        for tool_class in agent.tool_manager.get_all_tools():
            permission = "ask"
            tool_name = tool_class.get_name()
            if tool_name in manager.config.tools:
                permission = manager.config.tools[tool_name].permission

            tools.append(ToolInfo(
                name=tool_name,
                description=tool_class.description,
                permission=permission,
            ))

        # Clean up temp session
        await manager.delete_session(session.session_id)

        return tools

    @app.post("/api/config/model")
    async def set_model(request: SetModelRequest) -> dict[str, str]:
        """Set the active model."""
        manager = get_session_manager()
        config = manager.config

        # Validate model exists
        valid_models = [m.name for m in config.models] + [m.alias for m in config.models if m.alias]
        if request.model not in valid_models:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid model. Available: {', '.join(valid_models)}",
            )

        config.active_model = request.model
        return {"model": config.active_model}

    @app.patch("/api/sessions/{session_id}")
    async def rename_session(
        session_id: str, request: RenameSessionRequest
    ) -> dict[str, str]:
        """Rename a session."""
        manager = get_session_manager()
        session = await manager.get_session(session_id)

        if not session:
            session = await manager.load_session(session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session.name = request.name
        session.updated_at = datetime.now()

        return {"name": session.name}

    @app.websocket("/ws/chat/{session_id}")
    async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
        """WebSocket endpoint for real-time chat."""
        await websocket.accept()

        manager = get_session_manager()
        session = await manager.get_session(session_id)

        if not session:
            session = await manager.load_session(session_id)

        if not session:
            await websocket.send_json({
                "type": WebMessageType.ERROR,
                "data": {"message": "Session not found", "code": "SESSION_NOT_FOUND"},
            })
            await websocket.close()
            return

        try:
            await handle_websocket_session(websocket, session, manager)
        except WebSocketDisconnect:
            # Save session on disconnect
            await manager.save_session(session)
        except Exception as e:
            await websocket.send_json({
                "type": WebMessageType.ERROR,
                "data": {"message": str(e), "code": "INTERNAL_ERROR"},
            })


async def handle_websocket_session(
    websocket: WebSocket,
    session: WebSession,
    manager: WebSessionManager,
) -> None:
    """Handle a WebSocket session."""
    # Send session info
    await websocket.send_json({
        "type": WebMessageType.SESSION_INFO,
        "data": session.to_detail().model_dump(mode="json"),
    })

    pending_approval: dict[str, asyncio.Event] = {}

    while True:
        try:
            raw_message = await websocket.receive_text()
            message = json.loads(raw_message)
            msg_type = message.get("type", "")
            data = message.get("data", {})

            if msg_type == WebMessageType.USER_MESSAGE:
                await handle_user_message(
                    websocket, session, data, pending_approval
                )

            elif msg_type == WebMessageType.TOOL_APPROVAL_RESPONSE:
                approval_data = ToolApprovalResponseData(**data)
                session.respond_to_approval(
                    approval_data.tool_call_id,
                    approval_data.approved,
                    approval_data.always_allow,
                )

        except json.JSONDecodeError:
            await websocket.send_json({
                "type": WebMessageType.ERROR,
                "data": {"message": "Invalid JSON", "code": "INVALID_JSON"},
            })
        except WebSocketDisconnect:
            raise
        except Exception as e:
            await websocket.send_json({
                "type": WebMessageType.ERROR,
                "data": {"message": str(e), "code": "MESSAGE_ERROR"},
            })


def _process_attachments(attachments: list[AttachmentData]) -> str:
    """Process attachments and return content to append to message."""
    parts: list[str] = []

    for attachment in attachments:
        mime_type = attachment.type
        name = attachment.name

        # Handle text-based files
        if mime_type.startswith("text/") or mime_type in (
            "application/json",
            "application/xml",
            "application/javascript",
        ) or name.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sh", ".bash", ".zsh", ".fish", ".rs", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".r", ".sql")):
            try:
                decoded = base64.b64decode(attachment.data).decode("utf-8")
                parts.append(f"\n\n--- File: {name} ---\n```\n{decoded}\n```")
            except Exception:
                parts.append(f"\n\n[Attached file: {name} (could not decode)]")

        # Handle images - note that full vision support would require model changes
        elif mime_type.startswith("image/"):
            parts.append(f"\n\n[Attached image: {name}]")

        # Handle PDFs and other files
        else:
            parts.append(f"\n\n[Attached file: {name} ({mime_type})]")

    return "".join(parts)


async def handle_user_message(
    websocket: WebSocket,
    session: WebSession,
    data: dict[str, Any],
    pending_approval: dict[str, asyncio.Event],
) -> None:
    """Handle a user message and stream the response."""
    # Parse and validate message data
    try:
        msg_data = UserMessageData(**data)
    except Exception:
        # Fallback to raw parsing
        msg_data = UserMessageData(
            content=data.get("content", ""),
            attachments=[],
            search_enabled=data.get("search_enabled", False),
        )

    content = msg_data.content
    attachments = msg_data.attachments
    search_enabled = msg_data.search_enabled

    # Process attachments and append to content
    if attachments:
        attachment_content = _process_attachments(attachments)
        content = content + attachment_content

    # Require either content or attachments
    if not content.strip():
        return

    # Add user message to session
    user_msg = ChatMessage(
        role="user",
        content=content,
        timestamp=datetime.now(),
    )
    session.add_chat_message(user_msg)

    # Get or create agent
    agent = await session.get_or_create_agent()

    # Set up approval callback
    async def approval_callback(
        tool_name: str,
        args: BaseModel,
        tool_call_id: str,
    ) -> tuple[ApprovalResponse, str | None]:
        # Send approval request
        await websocket.send_json({
            "type": WebMessageType.TOOL_APPROVAL_REQUEST,
            "data": {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments": args.model_dump(mode="json"),
            },
        })

        # Wait for response
        approved, always_allow = await session.request_tool_approval(tool_call_id)

        if always_allow and approved:
            # Persist always_allow to config (like CLI does)
            VibeConfig.save_updates({"tools": {tool_name: {"permission": "always"}}})
            # Also update in-memory config for this session
            manager = get_session_manager()
            if tool_name not in manager.config.tools:
                from vibe.core.tools.base import BaseToolConfig
                manager.config.tools[tool_name] = BaseToolConfig()
            from vibe.core.tools.base import ToolPermission
            manager.config.tools[tool_name].permission = ToolPermission.ALWAYS

        if approved:
            return ApprovalResponse.YES, None
        return ApprovalResponse.NO, None

    agent.approval_callback = approval_callback

    # Track assistant response
    full_response = ""
    full_reasoning = ""

    try:
        async for event in agent.act(content):
            if isinstance(event, AssistantEvent):
                full_response += event.content
                await websocket.send_json({
                    "type": WebMessageType.ASSISTANT_CHUNK,
                    "data": {
                        "content": event.content,
                        "done": event.stopped_by_middleware,
                    },
                })

            elif isinstance(event, ReasoningEvent):
                full_reasoning += event.content
                await websocket.send_json({
                    "type": WebMessageType.REASONING,
                    "data": {"content": event.content},
                })

            elif isinstance(event, ToolCallEvent):
                await websocket.send_json({
                    "type": WebMessageType.TOOL_CALL,
                    "data": {
                        "id": event.tool_call_id,
                        "name": event.tool_name,
                        "arguments": event.args.model_dump(mode="json"),
                        "requires_approval": True,
                    },
                })

            elif isinstance(event, ToolResultEvent):
                result_data: dict[str, Any] = {
                    "tool_call_id": event.tool_call_id,
                    "name": event.tool_name,
                    "skipped": event.skipped,
                }
                if event.result:
                    result_data["result"] = str(event.result)
                if event.error:
                    result_data["error"] = event.error
                if event.duration:
                    result_data["duration"] = event.duration

                await websocket.send_json({
                    "type": WebMessageType.TOOL_RESULT,
                    "data": result_data,
                })

            elif isinstance(event, CompactStartEvent):
                await websocket.send_json({
                    "type": WebMessageType.COMPACT_START,
                    "data": {
                        "current_tokens": event.current_context_tokens,
                        "threshold": event.threshold,
                    },
                })

            elif isinstance(event, CompactEndEvent):
                await websocket.send_json({
                    "type": WebMessageType.COMPACT_END,
                    "data": {
                        "old_tokens": event.old_context_tokens,
                        "new_tokens": event.new_context_tokens,
                    },
                })

        # Send done message
        await websocket.send_json({
            "type": WebMessageType.ASSISTANT_DONE,
            "data": {
                "content": full_response,
                "stats": agent.stats.model_dump(),
            },
        })

        # Add assistant message to session
        if full_response:
            assistant_msg = ChatMessage(
                role="assistant",
                content=full_response,
                timestamp=datetime.now(),
                reasoning=full_reasoning if full_reasoning else None,
            )
            session.add_chat_message(assistant_msg)

    except Exception as e:
        await websocket.send_json({
            "type": WebMessageType.ERROR,
            "data": {"message": str(e), "code": "AGENT_ERROR"},
        })
