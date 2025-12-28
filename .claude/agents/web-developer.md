# Web Developer Agent

Agent specialized for developing and debugging the Mistral Vibe web interface.

## Tools Available
- bash: Run commands (npm, uvicorn, curl for testing)
- grep: Search code patterns
- read_file: Read source files
- write_file: Create new files
- search_replace: Edit existing files
- list_dir: Explore directory structure

## Architecture Overview

### Server (vibe/web/server.py)
- FastAPI application with WebSocket support
- Rate limiting middleware (120 req/min per IP)
- CORS enabled for all origins
- Static file serving from `vibe/web/static/`

Key endpoints:
- `GET /` - Serves index.html
- `GET /api/sessions` - List all sessions
- `POST /api/sessions` - Create new session
- `GET /api/sessions/{id}` - Get session details
- `DELETE /api/sessions/{id}` - Delete session
- `PATCH /api/sessions/{id}` - Rename session
- `GET /api/config` - Get configuration
- `POST /api/config/model` - Set active model
- `GET /api/tools` - List available tools
- `WS /ws/chat/{session_id}` - Real-time chat WebSocket

### Session Manager (vibe/web/session_manager.py)
- `WebSessionManager` - Manages session lifecycle
- `WebSession` - Individual chat session with agent

Tool approval pattern:
```python
# Per-tool-call event tracking (NOT per-session!)
self._pending_approvals: dict[str, tuple[asyncio.Event, tuple[bool, bool] | None]] = {}

async def request_tool_approval(self, tool_call_id: str) -> tuple[bool, bool]:
    event = asyncio.Event()
    self._pending_approvals[tool_call_id] = (event, None)
    await event.wait()
    # Returns (approved, always_allow)
```

### Schemas (vibe/web/schemas.py)
All Pydantic v2 models for API request/response:
- `WebMessageType` - StrEnum for WebSocket message types
- `ChatMessage` - Single message with role, content, timestamp
- `SessionSummary/SessionDetail` - Session data models
- `AttachmentData` - File attachment (name, type, size, base64 data)
- `UserMessageData` - User message with attachments and search flag
- `ToolApprovalResponseData` - Approval response from client

### Frontend (vibe/web/static/)

**index.html** - Main HTML with:
- Semantic HTML5 structure with ARIA attributes
- DOMPurify for XSS protection
- Marked.js for markdown rendering
- Highlight.js for code syntax highlighting
- Modal dialogs for tool approval and delete confirmation
- Toast notification container

**css/style.css** - Styles with:
- CSS custom properties for theming (light/dark)
- Responsive design with mobile sidebar
- `.visually-hidden` for accessibility
- Focus-visible outlines for keyboard navigation
- Toast notification animations

**js/app.js** - Main JavaScript:
- WebSocket connection with exponential backoff reconnection
- `sanitizeHTML()` using DOMPurify
- `showToast()` notification system
- `renderMarkdown()` with code highlighting
- Session CRUD operations
- File attachment handling with base64 encoding
- Tool approval modal flow

## WebSocket Message Types

From server to client:
- `session_info` - Session details on connect
- `assistant_chunk` - Streaming response content
- `assistant_done` - Response complete with stats
- `reasoning` - Model reasoning content
- `tool_call` - Tool being called
- `tool_result` - Tool execution result
- `tool_approval_request` - Approval needed
- `compact_start/compact_end` - Context compaction events
- `error` - Error message

From client to server:
- `user_message` - User sends message
- `tool_approval_response` - Approval decision

## Common Patterns

### Adding a new API endpoint:
```python
@app.post("/api/example")
async def example_endpoint(request: ExampleRequest) -> ExampleResponse:
    manager = get_session_manager()
    # ... implementation
    return ExampleResponse(...)
```

### Adding WebSocket message handling:
```python
elif msg_type == WebMessageType.NEW_TYPE:
    data = NewTypeData(**data)
    # Handle the message
    await websocket.send_json({
        "type": WebMessageType.RESPONSE_TYPE,
        "data": {...},
    })
```

### Frontend event handling:
```javascript
elements.newButton.addEventListener('click', async () => {
    try {
        const response = await fetch('/api/endpoint', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!response.ok) throw new Error('Request failed');
        const result = await response.json();
        showToast('Success!', 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
});
```

## Security Considerations

1. **XSS Protection**: Always use `sanitizeHTML()` before setting innerHTML
2. **Rate Limiting**: RateLimiter class at 120 req/min per IP
3. **Input Validation**: Pydantic models validate all inputs
4. **Tool Approval**: User must approve dangerous tool calls
5. **Always Allow**: Persisted to config via `VibeConfig.save_updates()`

## Testing

Run the web server:
```bash
cd /home/user/mistral-vibe
python -m vibe.web
```

Test endpoints:
```bash
curl http://localhost:8080/api/sessions
curl http://localhost:8080/api/config
```
