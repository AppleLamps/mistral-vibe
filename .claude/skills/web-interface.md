# Web Interface Skill

Knowledge for working with the Mistral Vibe web interface (`vibe/web/`).

## Quick Reference

### File Locations
- Server: `vibe/web/server.py` - FastAPI app, routes, WebSocket
- Session: `vibe/web/session_manager.py` - WebSession, WebSessionManager
- Schemas: `vibe/web/schemas.py` - Pydantic request/response models
- Static: `vibe/web/static/` - Frontend HTML/CSS/JS
- Entry: `vibe/web/__main__.py` - CLI entry point

### Running the Server
```bash
python -m vibe.web --port 8080 --host 0.0.0.0
```

## Key Patterns

### WebSocket Message Flow
```
Client                          Server
  |                               |
  |--- user_message ------------->|
  |                               |--- agent.act() starts
  |<-- assistant_chunk -----------|  (streaming)
  |<-- tool_call -----------------|
  |<-- tool_approval_request -----|
  |--- tool_approval_response --->|
  |<-- tool_result ---------------|
  |<-- assistant_chunk -----------|
  |<-- assistant_done ------------|
```

### Tool Approval Concurrency
CRITICAL: Use per-tool-call events, not per-session:
```python
# WRONG - breaks with concurrent tool calls
self._approval_event = asyncio.Event()

# RIGHT - track each tool call separately
self._pending_approvals: dict[str, tuple[asyncio.Event, tuple[bool, bool] | None]] = {}
```

### Always Allow Persistence
```python
if always_allow and approved:
    VibeConfig.save_updates({"tools": {tool_name: {"permission": "always"}}})
```

### Attachment Processing
- Text files: Base64 decode to UTF-8, wrap in code block
- Images: Note as attached (vision requires model changes)
- Other: Note as attached with MIME type

### XSS Prevention
Always sanitize HTML before inserting into DOM:
```javascript
function sanitizeHTML(html) {
    if (typeof DOMPurify !== 'undefined') {
        return DOMPurify.sanitize(html, { ADD_ATTR: ['onclick'] });
    }
    return html;
}
```

### Toast Notifications
```javascript
showToast('Success message', 'success');  // green
showToast('Error message', 'error');      // red
showToast('Info message', 'info');        // blue (default)
showToast('Warning', 'warning');          // orange
```

### WebSocket Reconnection
Exponential backoff: 2s, 4s, 8s, 16s, 32s (max 5 attempts)
```javascript
const delay = WS_RECONNECT_DELAY * Math.pow(2, wsReconnectAttempts);
```

## Schema Reference

### WebMessageType (StrEnum)
- `user_message` - Client sends message
- `assistant_chunk` - Streaming response
- `assistant_done` - Response complete
- `tool_call` - Tool being called
- `tool_result` - Tool result
- `tool_approval_request` - Need approval
- `tool_approval_response` - Approval response
- `reasoning` - Model reasoning
- `error` - Error occurred
- `session_info` - Session details
- `compact_start` / `compact_end` - Context compaction

### Key Models
- `ChatMessage(role, content, timestamp, tool_call?, tool_result?, reasoning?)`
- `SessionSummary(id, name, created_at, updated_at, message_count, preview)`
- `SessionDetail(id, name, created_at, updated_at, messages, stats)`
- `AttachmentData(name, type, size, data)` - type is MIME, data is base64
- `UserMessageData(content, attachments, search_enabled)`

## CSS Variables (Theming)

Light mode (`data-theme="light"`):
```css
--bg-primary: #ffffff;
--text-primary: #1a1a2e;
--accent: #6366f1;
```

Dark mode (`data-theme="dark"`):
```css
--bg-primary: #0f0f1a;
--text-primary: #e8e8f0;
--accent: #818cf8;
```

## Accessibility Checklist
- [ ] Semantic HTML (`<main>`, `<nav>`, `<aside>`)
- [ ] ARIA labels on interactive elements
- [ ] `role="log"` on message container
- [ ] `role="alertdialog"` on modals
- [ ] `.visually-hidden` for screen reader text
- [ ] `:focus-visible` outlines
- [ ] `aria-live="polite"` for dynamic content
