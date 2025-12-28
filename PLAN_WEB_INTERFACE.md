# Web Interface Implementation Plan for Mistral Vibe

## Overview

Add an optional web interface to Mistral Vibe that provides a Claude Code-style experience:
- Clean, modern design with left sidebar for sessions
- Main content area for conversation
- Real-time streaming responses
- Tool execution previews and results
- Session management and persistence

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web Browser                              │
│  ┌──────────────┐  ┌───────────────────────────────────────┐   │
│  │   Sessions   │  │          Chat Interface                │   │
│  │   Sidebar    │  │  ┌─────────────────────────────────┐  │   │
│  │              │  │  │      Message History            │  │   │
│  │  - Session 1 │  │  │  - User messages                │  │   │
│  │  - Session 2 │  │  │  - Assistant responses          │  │   │
│  │  - Session 3 │  │  │  - Tool calls/results           │  │   │
│  │              │  │  └─────────────────────────────────┘  │   │
│  │  [+ New]     │  │  ┌─────────────────────────────────┐  │   │
│  │              │  │  │      Input Area                 │  │   │
│  └──────────────┘  │  └─────────────────────────────────┘  │   │
│                    └───────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                │
│  │  REST API  │  │ WebSocket  │  │   Static   │                │
│  │  /api/*    │  │  /ws/chat  │  │   Files    │                │
│  └────────────┘  └────────────┘  └────────────┘                │
│         │              │                                        │
│         ▼              ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │               Core Agent (vibe/core/agent.py)            │  │
│  │  - Message handling                                       │  │
│  │  - Tool execution                                         │  │
│  │  - LLM streaming                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
vibe/
├── web/                           # New web module
│   ├── __init__.py
│   ├── server.py                  # FastAPI application
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── chat.py                # Chat endpoints (WebSocket)
│   │   ├── sessions.py            # Session CRUD operations
│   │   ├── tools.py               # Tool listing/approval
│   │   └── config.py              # Configuration endpoints
│   ├── schemas.py                 # Pydantic request/response models
│   ├── session_manager.py         # Web session state management
│   └── static/                    # Frontend assets
│       ├── index.html             # Main HTML template
│       ├── css/
│       │   └── style.css          # Claude Code-inspired styles
│       └── js/
│           ├── app.js             # Main application logic
│           ├── chat.js            # Chat/WebSocket handling
│           ├── sessions.js        # Session management
│           └── markdown.js        # Markdown rendering
```

## Implementation Steps

### Phase 1: Backend API (Core)

#### Step 1.1: Create Web Module Structure
- Create `vibe/web/` directory
- Add `__init__.py` with module exports
- Create `server.py` with FastAPI app factory

#### Step 1.2: Add API Schemas
```python
# vibe/web/schemas.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "tool"
    content: str
    timestamp: datetime
    tool_call: Optional[dict] = None
    tool_result: Optional[dict] = None

class Session(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    message_count: int

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ToolApprovalRequest(BaseModel):
    session_id: str
    tool_call_id: str
    approved: bool
```

#### Step 1.3: Implement WebSocket Chat Handler
```python
# vibe/web/routes/chat.py
@router.websocket("/ws/chat/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time chat streaming.

    Message Types:
    - user_message: User sends a message
    - assistant_chunk: Streaming assistant response
    - tool_call: Tool execution preview
    - tool_result: Tool execution result
    - tool_approval_request: Request user approval
    - error: Error message
    """
```

#### Step 1.4: Session Manager
```python
# vibe/web/session_manager.py
class WebSessionManager:
    """Manages web sessions with Agent instances."""

    async def create_session(self, name: str) -> Session
    async def get_session(self, session_id: str) -> Session
    async def list_sessions(self) -> List[Session]
    async def delete_session(self, session_id: str) -> bool
    async def get_agent(self, session_id: str) -> Agent
```

#### Step 1.5: Tool Approval Integration
- Hook into agent's tool permission system
- Send approval requests via WebSocket
- Wait for user response before executing

### Phase 2: Frontend UI

#### Step 2.1: HTML Structure (Claude Code-inspired)
```html
<!-- index.html -->
<div class="app-container">
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1>Mistral Vibe</h1>
      <span class="version">Web</span>
    </div>
    <button class="new-session-btn">+ New Chat</button>
    <div class="sessions-list"></div>
  </aside>

  <main class="chat-container">
    <div class="messages"></div>
    <div class="input-container">
      <textarea placeholder="Ask me anything..."></textarea>
      <button class="send-btn">Send</button>
    </div>
  </main>
</div>
```

#### Step 2.2: CSS Styling (Claude Code-inspired)
```css
/* Modern, clean design */
:root {
  --bg-primary: #faf9f7;      /* Warm off-white */
  --bg-secondary: #f5f4f2;    /* Sidebar background */
  --text-primary: #1a1a1a;
  --text-secondary: #666;
  --accent: #d4a574;          /* Warm accent color */
  --border: #e5e5e5;
  --code-bg: #f8f8f8;
}

/* Responsive layout with sidebar */
/* Message bubbles with tool call formatting */
/* Tables for structured data */
/* Syntax highlighting for code blocks */
```

#### Step 2.3: JavaScript Application
- WebSocket connection management
- Message rendering with Markdown support
- Session management UI
- Tool approval dialogs
- Streaming response handling

### Phase 3: CLI Integration

#### Step 3.1: Add Web Command Flag
```python
# vibe/cli/entrypoint.py
parser.add_argument(
    "--web",
    action="store_true",
    help="Start web interface instead of TUI"
)
parser.add_argument(
    "--web-port",
    type=int,
    default=8080,
    help="Port for web interface (default: 8080)"
)
parser.add_argument(
    "--web-host",
    type=str,
    default="127.0.0.1",
    help="Host for web interface (default: 127.0.0.1)"
)
```

#### Step 3.2: Web Server Launcher
```python
# vibe/cli/entrypoint.py
if args.web:
    from vibe.web.server import run_server
    run_server(host=args.web_host, port=args.web_port)
```

### Phase 4: Dependencies

Add to `pyproject.toml`:
```toml
[project.optional-dependencies]
web = [
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
    "websockets>=14.0",
    "python-multipart>=0.0.20",  # For file uploads
]
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sessions` | List all sessions |
| POST | `/api/sessions` | Create new session |
| GET | `/api/sessions/{id}` | Get session details |
| DELETE | `/api/sessions/{id}` | Delete session |
| GET | `/api/sessions/{id}/messages` | Get session messages |
| WS | `/ws/chat/{session_id}` | WebSocket chat stream |
| GET | `/api/tools` | List available tools |
| GET | `/api/config` | Get current configuration |
| POST | `/api/tools/{id}/approve` | Approve tool execution |

## WebSocket Message Protocol

### Client → Server
```json
{
  "type": "user_message",
  "content": "Hello, help me with..."
}
```

```json
{
  "type": "tool_approval",
  "tool_call_id": "abc123",
  "approved": true
}
```

### Server → Client
```json
{
  "type": "assistant_chunk",
  "content": "partial response...",
  "done": false
}
```

```json
{
  "type": "tool_call",
  "id": "abc123",
  "name": "read_file",
  "arguments": {"path": "/src/main.py"},
  "requires_approval": true
}
```

```json
{
  "type": "tool_result",
  "tool_call_id": "abc123",
  "result": "file contents..."
}
```

## UI Features (Claude Code-inspired)

### 1. Session Sidebar
- List of previous sessions with timestamps
- Session rename/delete options
- "New Chat" button
- Session search/filter

### 2. Message Display
- User messages (right-aligned or distinct styling)
- Assistant responses with Markdown rendering
- Tool call previews with syntax highlighting
- Tool results in collapsible sections
- Code blocks with copy button
- Tables rendered cleanly

### 3. Input Area
- Multi-line text input
- File attachment support (drag & drop)
- Keyboard shortcuts (Ctrl+Enter to send)
- Input history

### 4. Tool Approval Dialog
- Modal showing tool name and arguments
- "Approve" / "Deny" / "Always Allow" buttons
- Syntax-highlighted preview of arguments

### 5. Status Indicators
- Connection status (WebSocket)
- Streaming indicator
- Model/provider display
- Token usage (optional)

## Security Considerations

1. **CORS Configuration**
   - Default: localhost only
   - Configurable for remote access

2. **Authentication (Optional)**
   - API key authentication
   - Session tokens

3. **Tool Sandboxing**
   - Same security model as CLI
   - Web-specific permission overrides

4. **Rate Limiting**
   - Configurable request limits
   - Prevent abuse

## Configuration

Add to `config.toml`:
```toml
[web]
enabled = false
host = "127.0.0.1"
port = 8080
open_browser = true
cors_origins = ["http://localhost:*"]

[web.auth]
enabled = false
api_key = ""  # Optional API key
```

## Testing Plan

1. **Unit Tests**
   - API endpoint tests
   - WebSocket message handling
   - Session manager operations

2. **Integration Tests**
   - Full chat flow with mocked agent
   - Tool approval workflow
   - Session persistence

3. **E2E Tests**
   - Browser automation (Playwright)
   - Multi-session handling

## Timeline Estimate

| Phase | Tasks |
|-------|-------|
| Phase 1 | Backend API with WebSocket streaming |
| Phase 2 | Frontend UI with Claude Code styling |
| Phase 3 | CLI integration and configuration |
| Phase 4 | Testing and polish |

## Future Enhancements

1. **Progressive Web App (PWA)**
   - Offline support
   - Install to desktop

2. **Collaboration Features**
   - Share sessions
   - Export conversations

3. **Advanced UI**
   - Dark mode toggle
   - Custom themes
   - Keyboard navigation

4. **Mobile Support**
   - Responsive design
   - Touch-friendly interactions

## Questions for User

1. **Authentication**: Should the web interface require authentication, or is localhost-only sufficient?

2. **Browser Auto-Open**: Should `vibe --web` automatically open the browser?

3. **Session Sync**: Should web sessions be separate from CLI sessions, or shared?

4. **File Upload**: Should users be able to attach files directly in the web UI?

5. **Tool Auto-Approval**: Should there be a "trust all" mode for the web interface?

---

This plan leverages your existing architecture's strengths:
- Reuses core Agent logic entirely
- Uses existing Pydantic models
- Maintains tool permission system
- Keeps session persistence compatible
- Async-first design fits perfectly with FastAPI/WebSockets
