from __future__ import annotations

import asyncio
import base64
from collections import defaultdict
from datetime import datetime
import hmac
import json
import logging
from pathlib import Path
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

# Configure logging
logger = logging.getLogger(__name__)

# Security constants
MAX_MESSAGE_LENGTH = 100_000  # 100KB max message content
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB max attachment
MAX_ATTACHMENTS = 10  # Maximum attachments per message

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
    RenameSessionRequest,
    SessionDetail,
    SessionSummary,
    SetModelRequest,
    ToolApprovalResponseData,
    ToolInfo,
    UserMessageData,
    WebMessageType,
)
from vibe.web.session_manager import WebSession, WebSessionManager

# Global state
_session_manager: WebSessionManager | None = None
_api_key: str | None = None
_allowed_origins: list[str] = []


def _sanitize_error_message(error: Exception) -> str:
    """Sanitize error messages to prevent information disclosure."""
    error_type = type(error).__name__
    # Only return safe, generic messages for internal errors
    safe_messages = {
        "ValidationError": "Invalid input data",
        "JSONDecodeError": "Invalid JSON format",
        "KeyError": "Missing required field",
        "ValueError": "Invalid value provided",
        "TypeError": "Invalid data type",
    }
    return safe_messages.get(error_type, "An internal error occurred")


def _verify_api_key(provided_key: str | None) -> bool:
    """Verify API key using constant-time comparison."""
    if _api_key is None:
        return True  # No API key configured, allow all
    if provided_key is None:
        return False
    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(provided_key.encode(), _api_key.encode())


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # CSP for the web interface
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none';"
        )
        return response


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


def create_app(
    api_key: str | None = None, allowed_origins: list[str] | None = None
) -> FastAPI:
    """Create the FastAPI application.

    Args:
        api_key: Optional API key for authentication. If provided, all API
            requests must include this key in the X-API-Key header.
        allowed_origins: List of allowed CORS origins. If None, defaults to
            localhost only for security.
    """
    global _api_key, _allowed_origins
    _api_key = api_key

    # Default to localhost-only for security
    if allowed_origins is None:
        _allowed_origins = [
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    else:
        _allowed_origins = allowed_origins

    app = FastAPI(
        title="Mistral Vibe Web",
        description="Web interface for Mistral Vibe coding assistant",
        version="1.0.0",
    )

    # Add security headers middleware first
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS middleware - restricted to specific origins
    # Note: When allow_credentials=True, origins must be explicit (not "*")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    )

    # Authentication and rate limiting middleware
    @app.middleware("http")
    async def auth_and_rate_limit_middleware(request: Request, call_next: Any) -> Any:
        # Skip auth and rate limiting for static files and index
        if request.url.path.startswith("/static") or request.url.path == "/":
            return await call_next(request)

        # Check API key authentication for API endpoints
        if request.url.path.startswith("/api"):
            api_key_header = request.headers.get("X-API-Key")
            if not _verify_api_key(api_key_header):
                return JSONResponse(
                    status_code=401, content={"error": "Invalid or missing API key"}
                )

        # Rate limiting
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

    # Session cleanup on startup
    @app.on_event("startup")
    async def start_session_cleanup() -> None:
        """Start the session cleanup background task."""
        manager = get_session_manager()
        await manager.start_cleanup_task()
        logger.info("Session cleanup task started")

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

        # Parse mode from request
        mode = AgentMode.DEFAULT
        if request.mode == "plan":
            mode = AgentMode.PLAN
        elif request.mode == "auto_approve":
            mode = AgentMode.AUTO_APPROVE

        session = await manager.create_session(name=request.name, mode=mode)
        return CreateSessionResponse(session_id=session.session_id, name=session.name)

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
            tools.append({"name": name, "permission": tool_config.permission})

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
        for tool_name, tool_class in agent.tool_manager.available_tools().items():
            permission = "ask"
            if tool_name in manager.config.tools:
                permission = manager.config.tools[tool_name].permission

            tools.append(
                ToolInfo(
                    name=tool_name,
                    description=tool_class.description,
                    permission=permission,
                )
            )

        # Clean up temp session
        await manager.delete_session(session.session_id)

        return tools

    @app.post("/api/config/model")
    async def set_model(request: SetModelRequest) -> dict[str, str]:
        """Set the active model."""
        manager = get_session_manager()
        config = manager.config

        # Validate model exists
        valid_models = [m.name for m in config.models] + [
            m.alias for m in config.models if m.alias
        ]
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
        # Check API key from query params for WebSocket
        api_key_param = websocket.query_params.get("api_key")
        if not _verify_api_key(api_key_param):
            await websocket.close(code=4001, reason="Invalid or missing API key")
            return

        await websocket.accept()

        # WebSocket rate limiting - check client IP
        client_ip = websocket.client.host if websocket.client else "unknown"
        if not _rate_limiter.is_allowed(client_ip):
            await websocket.send_json({
                "type": WebMessageType.ERROR,
                "data": {"message": "Too many requests", "code": "RATE_LIMITED"},
            })
            await websocket.close(code=4029)
            return

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
            logger.exception("WebSocket error: %s", e)
            await websocket.send_json({
                "type": WebMessageType.ERROR,
                "data": {
                    "message": _sanitize_error_message(e),
                    "code": "INTERNAL_ERROR",
                },
            })


async def handle_websocket_session(
    websocket: WebSocket, session: WebSession, manager: WebSessionManager
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
                await handle_user_message(websocket, session, data, pending_approval)

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
                "data": {"message": "Invalid JSON format", "code": "INVALID_JSON"},
            })
        except WebSocketDisconnect:
            raise
        except Exception as e:
            logger.exception("Message handling error: %s", e)
            await websocket.send_json({
                "type": WebMessageType.ERROR,
                "data": {
                    "message": _sanitize_error_message(e),
                    "code": "MESSAGE_ERROR",
                },
            })


def _process_attachments(attachments: list[AttachmentData]) -> str:
    """Process attachments and return content to append to message."""
    parts: list[str] = []

    for attachment in attachments:
        mime_type = attachment.type
        name = attachment.name

        # Handle text-based files
        if (
            mime_type.startswith("text/")
            or mime_type
            in {"application/json", "application/xml", "application/javascript"}
            or name.endswith((
                ".py",
                ".js",
                ".ts",
                ".tsx",
                ".jsx",
                ".md",
                ".yaml",
                ".yml",
                ".toml",
                ".ini",
                ".cfg",
                ".sh",
                ".bash",
                ".zsh",
                ".fish",
                ".rs",
                ".go",
                ".java",
                ".c",
                ".cpp",
                ".h",
                ".hpp",
                ".cs",
                ".rb",
                ".php",
                ".swift",
                ".kt",
                ".scala",
                ".r",
                ".sql",
            ))
        ):
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

    # Input validation - message length
    if len(content) > MAX_MESSAGE_LENGTH:
        await websocket.send_json({
            "type": WebMessageType.ERROR,
            "data": {
                "message": f"Message too long. Maximum {MAX_MESSAGE_LENGTH} characters.",
                "code": "MESSAGE_TOO_LONG",
            },
        })
        return

    # Input validation - attachment count
    if len(attachments) > MAX_ATTACHMENTS:
        await websocket.send_json({
            "type": WebMessageType.ERROR,
            "data": {
                "message": f"Too many attachments. Maximum {MAX_ATTACHMENTS} allowed.",
                "code": "TOO_MANY_ATTACHMENTS",
            },
        })
        return

    # Input validation - attachment sizes
    for attachment in attachments:
        if attachment.size > MAX_ATTACHMENT_SIZE:
            await websocket.send_json({
                "type": WebMessageType.ERROR,
                "data": {
                    "message": f"Attachment '{attachment.name}' too large. Maximum 10MB.",
                    "code": "ATTACHMENT_TOO_LARGE",
                },
            })
            return
        # Also validate base64 decoded size (base64 is ~33% larger than raw)
        expected_decoded_size = len(attachment.data) * 3 // 4
        if expected_decoded_size > MAX_ATTACHMENT_SIZE:
            await websocket.send_json({
                "type": WebMessageType.ERROR,
                "data": {
                    "message": f"Attachment '{attachment.name}' too large. Maximum 10MB.",
                    "code": "ATTACHMENT_TOO_LARGE",
                },
            })
            return

    # Process attachments and append to content
    if attachments:
        attachment_content = _process_attachments(attachments)
        content += attachment_content

    # Require either content or attachments
    if not content.strip():
        return

    # Add user message to session
    user_msg = ChatMessage(role="user", content=content, timestamp=datetime.now())
    session.add_chat_message(user_msg)

    # Get or create agent
    agent = await session.get_or_create_agent()

    # Set up approval callback
    async def approval_callback(
        tool_name: str, args: BaseModel, tool_call_id: str
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
            "data": {"content": full_response, "stats": agent.stats.model_dump()},
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
        logger.exception("Agent error: %s", e)
        await websocket.send_json({
            "type": WebMessageType.ERROR,
            "data": {"message": _sanitize_error_message(e), "code": "AGENT_ERROR"},
        })
