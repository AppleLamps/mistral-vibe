/**
 * Mistral Vibe Web Interface
 */

// Message types (must match server)
const MessageType = {
    USER_MESSAGE: 'user_message',
    ASSISTANT_CHUNK: 'assistant_chunk',
    ASSISTANT_DONE: 'assistant_done',
    TOOL_CALL: 'tool_call',
    TOOL_RESULT: 'tool_result',
    TOOL_APPROVAL_REQUEST: 'tool_approval_request',
    TOOL_APPROVAL_RESPONSE: 'tool_approval_response',
    REASONING: 'reasoning',
    ERROR: 'error',
    SESSION_INFO: 'session_info',
    COMPACT_START: 'compact_start',
    COMPACT_END: 'compact_end',
};

// App state
const state = {
    currentSessionId: null,
    sessions: [],
    ws: null,
    isStreaming: false,
    pendingApproval: null,
    config: null,
    theme: 'light',
    searchEnabled: false,
    attachedFiles: [],
};

// DOM elements
const elements = {
    // Core elements
    sessionsList: document.getElementById('sessionsList'),
    messagesContainer: document.getElementById('messagesContainer'),
    messages: document.getElementById('messages'),
    messageInput: document.getElementById('messageInput'),
    sendBtn: document.getElementById('sendBtn'),
    newSessionBtn: document.getElementById('newSessionBtn'),
    startChatBtn: document.getElementById('startChatBtn'),
    welcomeScreen: document.getElementById('welcomeScreen'),
    chatContainer: document.getElementById('chatContainer'),
    sessionName: document.getElementById('sessionName'),
    sessionStats: document.getElementById('sessionStats'),
    streamingStatus: document.getElementById('streamingStatus'),

    // Modals
    approvalModal: document.getElementById('approvalModal'),
    approvalToolName: document.getElementById('approvalToolName'),
    approvalToolArgs: document.getElementById('approvalToolArgs'),
    approveToolBtn: document.getElementById('approveToolBtn'),
    denyToolBtn: document.getElementById('denyToolBtn'),
    approvalClose: document.getElementById('approvalClose'),
    alwaysAllowCheck: document.getElementById('alwaysAllowCheck'),
    imageModal: document.getElementById('imageModal'),
    imageModalImg: document.getElementById('imageModalImg'),
    imageModalClose: document.getElementById('imageModalClose'),
    deleteModal: document.getElementById('deleteModal'),
    deleteModalClose: document.getElementById('deleteModalClose'),
    confirmDeleteBtn: document.getElementById('confirmDeleteBtn'),
    cancelDeleteBtn: document.getElementById('cancelDeleteBtn'),
    deleteSessionBtn: document.getElementById('deleteSessionBtn'),
    toastContainer: document.getElementById('toastContainer'),

    // Theme
    themeToggle: document.getElementById('themeToggle'),
    themeToggleMobile: document.getElementById('themeToggleMobile'),

    // Mobile
    menuToggle: document.getElementById('menuToggle'),
    sidebar: document.getElementById('sidebar'),
    sidebarOverlay: document.getElementById('sidebarOverlay'),

    // Model selector
    modelSelect: document.getElementById('modelSelect'),

    // Session search
    sessionSearch: document.getElementById('sessionSearch'),

    // Rename
    renameBtn: document.getElementById('renameBtn'),

    // File upload
    fileInput: document.getElementById('fileInput'),
    attachBtn: document.getElementById('attachBtn'),
    inputWrapper: document.getElementById('inputWrapper'),
    filePreviewContainer: document.getElementById('filePreviewContainer'),
    filePreviewList: document.getElementById('filePreviewList'),

    // Search
    searchToggle: document.getElementById('searchToggle'),
    searchIndicator: document.getElementById('searchIndicator'),
    searchClose: document.getElementById('searchClose'),
};

// Initialize marked for markdown rendering with code copy buttons
const renderer = new marked.Renderer();
const originalCodeRenderer = renderer.code.bind(renderer);

renderer.code = function(code, language) {
    const highlighted = language && hljs.getLanguage(language)
        ? hljs.highlight(code, { language }).value
        : hljs.highlightAuto(code).value;

    const langLabel = language || 'code';
    return `
        <div class="code-block-wrapper">
            <button class="code-copy-btn" onclick="copyCode(this)" data-code="${escapeHtml(code)}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>
                Copy
            </button>
            <pre><code class="hljs language-${langLabel}">${highlighted}</code></pre>
        </div>
    `;
};

marked.setOptions({
    renderer: renderer,
    breaks: true,
    gfm: true,
});

// Copy code function (global)
window.copyCode = async function(btn) {
    const code = btn.dataset.code;
    try {
        await navigator.clipboard.writeText(code);
        btn.classList.add('copied');
        btn.innerHTML = `
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            Copied!
        `;
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>
                Copy
            `;
        }, 2000);
    } catch (err) {
        console.error('Failed to copy:', err);
    }
};

// Safe HTML sanitization function
function sanitizeHTML(html) {
    if (typeof DOMPurify !== 'undefined') {
        return DOMPurify.sanitize(html, { ADD_ATTR: ['onclick'] });
    }
    // Fallback if DOMPurify not loaded
    return html;
}

// Toast notification system
function showToast(message, type = 'info', duration = 4000) {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-message">${sanitizeHTML(message)}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    elements.toastContainer?.appendChild(toast);

    // Auto-remove after duration
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, duration);

    return toast;
}

// Convenience toast functions
const toast = {
    success: (msg) => showToast(msg, 'success'),
    error: (msg) => showToast(msg, 'error'),
    warning: (msg) => showToast(msg, 'warning'),
    info: (msg) => showToast(msg, 'info'),
};

// API functions
async function fetchAPI(endpoint, options = {}) {
    const response = await fetch(`/api${endpoint}`, {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
        ...options,
    });
    if (!response.ok) {
        throw new Error(`API error: ${response.statusText}`);
    }
    return response.json();
}

async function loadSessions() {
    try {
        state.sessions = await fetchAPI('/sessions');
        renderSessions();
    } catch (error) {
        console.error('Failed to load sessions:', error);
    }
}

async function loadConfig() {
    try {
        state.config = await fetchAPI('/config');
        updateModelSelector();
    } catch (error) {
        console.error('Failed to load config:', error);
    }
}

async function createSession(name = null) {
    try {
        const response = await fetchAPI('/sessions', {
            method: 'POST',
            body: JSON.stringify({ name }),
        });
        await loadSessions();
        await selectSession(response.session_id);
        closeSidebar();
    } catch (error) {
        console.error('Failed to create session:', error);
    }
}

async function selectSession(sessionId) {
    // Close existing WebSocket
    if (state.ws) {
        state.ws.close();
        state.ws = null;
    }

    state.currentSessionId = sessionId;

    // Update UI
    elements.welcomeScreen.classList.add('hidden');
    elements.chatContainer.classList.remove('hidden');
    elements.messages.innerHTML = '';
    clearAttachedFiles();

    // Update active session in sidebar
    document.querySelectorAll('.session-item').forEach(item => {
        item.classList.toggle('active', item.dataset.sessionId === sessionId);
    });

    // Connect WebSocket
    connectWebSocket(sessionId);
}

// WebSocket reconnection state
let wsReconnectAttempts = 0;
const WS_MAX_RECONNECT_ATTEMPTS = 5;
const WS_RECONNECT_DELAY = 2000;

function connectWebSocket(sessionId) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat/${sessionId}`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        console.log('WebSocket connected');
        wsReconnectAttempts = 0; // Reset on successful connection
        updateSendButton();
    };

    state.ws.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleWebSocketMessage(message);
        } catch (error) {
            console.error('Failed to parse WebSocket message:', error);
        }
    };

    state.ws.onclose = (event) => {
        console.log('WebSocket disconnected', event.code, event.reason);
        updateSendButton();

        // Attempt reconnection if not intentionally closed
        if (state.currentSessionId === sessionId && wsReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
            wsReconnectAttempts++;
            const delay = WS_RECONNECT_DELAY * wsReconnectAttempts;
            toast.warning(`Connection lost. Reconnecting in ${delay/1000}s...`);
            setTimeout(() => {
                if (state.currentSessionId === sessionId) {
                    connectWebSocket(sessionId);
                }
            }, delay);
        } else if (wsReconnectAttempts >= WS_MAX_RECONNECT_ATTEMPTS) {
            toast.error('Connection lost. Please refresh the page.');
        }
    };

    state.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        toast.error('Connection error');
    };
}

function handleWebSocketMessage(message) {
    const { type, data } = message;

    switch (type) {
        case MessageType.SESSION_INFO:
            handleSessionInfo(data);
            break;

        case MessageType.ASSISTANT_CHUNK:
            handleAssistantChunk(data);
            break;

        case MessageType.ASSISTANT_DONE:
            handleAssistantDone(data);
            break;

        case MessageType.TOOL_CALL:
            handleToolCall(data);
            break;

        case MessageType.TOOL_RESULT:
            handleToolResult(data);
            break;

        case MessageType.TOOL_APPROVAL_REQUEST:
            handleToolApprovalRequest(data);
            break;

        case MessageType.REASONING:
            handleReasoning(data);
            break;

        case MessageType.ERROR:
            handleError(data);
            break;

        case MessageType.COMPACT_START:
        case MessageType.COMPACT_END:
            // Could show a notification
            break;

        default:
            console.log('Unknown message type:', type, data);
    }
}

function handleSessionInfo(data) {
    elements.sessionName.textContent = data.name || 'New Chat';

    // Render existing messages
    if (data.messages && data.messages.length > 0) {
        data.messages.forEach(msg => {
            if (msg.role === 'user') {
                appendUserMessage(msg.content);
            } else if (msg.role === 'assistant') {
                appendAssistantMessage(msg.content);
            }
        });
        scrollToBottom();
    }

    updateSessionStats(data.stats);
}

function handleAssistantChunk(data) {
    state.isStreaming = true;
    updateSendButton();
    showStreamingStatus(true);

    let streamingMessage = document.querySelector('.message.assistant.streaming');

    if (!streamingMessage) {
        streamingMessage = createAssistantMessage();
        streamingMessage.classList.add('streaming');
        elements.messages.appendChild(streamingMessage);
    }

    const contentEl = streamingMessage.querySelector('.message-content');
    const currentContent = contentEl.dataset.rawContent || '';
    const newContent = currentContent + data.content;
    contentEl.dataset.rawContent = newContent;
    contentEl.innerHTML = sanitizeHTML(marked.parse(newContent));

    scrollToBottom();
}

function handleAssistantDone(data) {
    state.isStreaming = false;
    updateSendButton();
    showStreamingStatus(false);

    const streamingMessage = document.querySelector('.message.assistant.streaming');
    if (streamingMessage) {
        streamingMessage.classList.remove('streaming');
    }

    if (data.stats) {
        updateSessionStats(data.stats);
    }

    scrollToBottom();
}

function handleToolCall(data) {
    const toolCallEl = document.createElement('div');
    toolCallEl.className = 'tool-call';
    toolCallEl.dataset.toolCallId = data.id;
    toolCallEl.innerHTML = `
        <div class="tool-call-header">
            <span class="tool-call-icon">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                </svg>
            </span>
            <span>${escapeHtml(data.name)}</span>
        </div>
        <div class="tool-call-body">
            <pre class="tool-call-args">${escapeHtml(JSON.stringify(data.arguments, null, 2))}</pre>
        </div>
    `;

    // Add to current assistant message or create new one
    let assistantMessage = document.querySelector('.message.assistant.streaming');
    if (!assistantMessage) {
        assistantMessage = createAssistantMessage();
        assistantMessage.classList.add('streaming');
        elements.messages.appendChild(assistantMessage);
    }

    const contentEl = assistantMessage.querySelector('.message-content');
    contentEl.appendChild(toolCallEl);

    scrollToBottom();
}

function handleToolResult(data) {
    const toolCallEl = document.querySelector(`.tool-call[data-tool-call-id="${data.tool_call_id}"]`);

    if (toolCallEl) {
        const resultEl = document.createElement('div');
        resultEl.className = 'tool-result';

        if (data.error) {
            resultEl.classList.add('error');
            resultEl.textContent = `Error: ${data.error}`;
        } else if (data.skipped) {
            resultEl.classList.add('skipped');
            resultEl.textContent = 'Skipped';
        } else if (data.result) {
            // Truncate long results
            const result = data.result.length > 1000
                ? data.result.substring(0, 1000) + '...'
                : data.result;
            resultEl.textContent = result;
        }

        if (data.duration) {
            const durationSpan = document.createElement('span');
            durationSpan.style.opacity = '0.7';
            durationSpan.textContent = ` (${data.duration.toFixed(2)}s)`;
            resultEl.appendChild(durationSpan);
        }

        toolCallEl.querySelector('.tool-call-body').appendChild(resultEl);
    }

    scrollToBottom();
}

function handleToolApprovalRequest(data) {
    state.pendingApproval = data;

    elements.approvalToolName.textContent = data.tool_name;
    elements.approvalToolArgs.textContent = JSON.stringify(data.arguments, null, 2);
    elements.alwaysAllowCheck.checked = false;
    elements.approvalModal.classList.remove('hidden');
}

function handleReasoning(data) {
    // Could display reasoning in a collapsible section
    console.log('Reasoning:', data.content);
}

function handleError(data) {
    state.isStreaming = false;
    updateSendButton();
    showStreamingStatus(false);

    const errorEl = document.createElement('div');
    errorEl.className = 'message error';
    errorEl.innerHTML = `
        <div class="message-header">
            <div class="message-avatar" style="background: var(--error);">!</div>
            <span class="message-role">Error</span>
        </div>
        <div class="message-content" style="color: var(--error);">
            ${escapeHtml(data.message)}
        </div>
    `;
    elements.messages.appendChild(errorEl);
    scrollToBottom();
}

// UI functions
function renderSessions() {
    elements.sessionsList.innerHTML = '';

    state.sessions.forEach(session => {
        const item = document.createElement('div');
        item.className = 'session-item';
        item.dataset.sessionId = session.id;

        if (session.id === state.currentSessionId) {
            item.classList.add('active');
        }

        const date = new Date(session.updated_at);
        const timeStr = formatRelativeTime(date);

        item.innerHTML = `
            <div class="session-item-name">${escapeHtml(session.name)}</div>
            ${session.preview ? `<div class="session-item-preview">${escapeHtml(session.preview)}</div>` : ''}
            <div class="session-item-meta">
                <span>${session.message_count} messages</span>
                <span>${timeStr}</span>
            </div>
        `;

        item.addEventListener('click', () => {
            selectSession(session.id);
            closeSidebar();
        });
        elements.sessionsList.appendChild(item);
    });
}

function appendUserMessage(content) {
    const messageEl = document.createElement('div');
    messageEl.className = 'message user';
    messageEl.innerHTML = `
        <div class="message-header">
            <div class="message-avatar">U</div>
            <span class="message-role">You</span>
        </div>
        <div class="message-content">${escapeHtml(content)}</div>
    `;
    elements.messages.appendChild(messageEl);
}

function createAssistantMessage() {
    const messageEl = document.createElement('div');
    messageEl.className = 'message assistant';
    messageEl.innerHTML = `
        <div class="message-header">
            <div class="message-avatar">V</div>
            <span class="message-role">Vibe</span>
        </div>
        <div class="message-content"></div>
    `;
    return messageEl;
}

function appendAssistantMessage(content) {
    const messageEl = createAssistantMessage();
    const contentEl = messageEl.querySelector('.message-content');
    contentEl.innerHTML = sanitizeHTML(marked.parse(content));
    elements.messages.appendChild(messageEl);
}

function updateModelSelector() {
    if (state.config && elements.modelSelect) {
        elements.modelSelect.innerHTML = '';
        state.config.models.forEach(model => {
            const option = document.createElement('option');
            option.value = model.alias;
            option.textContent = model.alias;
            if (model.alias === state.config.active_model) {
                option.selected = true;
            }
            elements.modelSelect.appendChild(option);
        });
    }
}

function updateSessionStats(stats) {
    if (stats && elements.sessionStats) {
        const tokens = stats.session_total_llm_tokens || 0;
        const cost = stats.session_cost || 0;
        elements.sessionStats.textContent = `${tokens.toLocaleString()} tokens | $${cost.toFixed(4)}`;
    }
}

function updateSendButton() {
    const hasContent = elements.messageInput.value.trim().length > 0 || state.attachedFiles.length > 0;
    const isConnected = state.ws && state.ws.readyState === WebSocket.OPEN;
    const canSend = hasContent && isConnected && !state.isStreaming;

    elements.sendBtn.disabled = !canSend;
}

function showStreamingStatus(show) {
    if (show) {
        elements.streamingStatus.classList.remove('hidden');
    } else {
        elements.streamingStatus.classList.add('hidden');
    }
}

function scrollToBottom() {
    elements.messagesContainer.scrollTop = elements.messagesContainer.scrollHeight;
}

function sendMessage() {
    const content = elements.messageInput.value.trim();
    if ((!content && state.attachedFiles.length === 0) || !state.ws || state.ws.readyState !== WebSocket.OPEN) {
        return;
    }

    // Add user message to UI
    appendUserMessage(content);
    scrollToBottom();

    // Build message with attachments
    const messageData = {
        content,
        search_enabled: state.searchEnabled,
    };

    // Add file info if any
    if (state.attachedFiles.length > 0) {
        messageData.attachments = state.attachedFiles.map(f => ({
            name: f.name,
            type: f.type,
            size: f.size,
            data: f.data, // base64
        }));
    }

    // Send via WebSocket
    state.ws.send(JSON.stringify({
        type: MessageType.USER_MESSAGE,
        data: messageData,
    }));

    // Clear input and files
    elements.messageInput.value = '';
    clearAttachedFiles();
    updateSendButton();
    autoResizeTextarea();
}

function respondToApproval(approved) {
    if (!state.pendingApproval || !state.ws) {
        return;
    }

    const alwaysAllow = elements.alwaysAllowCheck.checked;

    state.ws.send(JSON.stringify({
        type: MessageType.TOOL_APPROVAL_RESPONSE,
        data: {
            tool_call_id: state.pendingApproval.tool_call_id,
            approved,
            always_allow: alwaysAllow,
        },
    }));

    state.pendingApproval = null;
    elements.approvalModal.classList.add('hidden');
}

function autoResizeTextarea() {
    const textarea = elements.messageInput;
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
}

// Theme functions
function initTheme() {
    const savedTheme = localStorage.getItem('vibe-theme') || 'light';
    setTheme(savedTheme);
}

function setTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('vibe-theme', theme);

    // Toggle highlight.js themes
    const lightTheme = document.getElementById('hljs-light');
    const darkTheme = document.getElementById('hljs-dark');
    if (lightTheme && darkTheme) {
        lightTheme.disabled = theme === 'dark';
        darkTheme.disabled = theme === 'light';
    }
}

function toggleTheme() {
    const newTheme = state.theme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);
}

// Mobile sidebar functions
function openSidebar() {
    elements.sidebar.classList.add('open');
    elements.sidebarOverlay.classList.add('visible');
}

function closeSidebar() {
    elements.sidebar.classList.remove('open');
    elements.sidebarOverlay.classList.remove('visible');
}

// Session search
function filterSessions(query) {
    const items = elements.sessionsList.querySelectorAll('.session-item');
    const lowerQuery = query.toLowerCase();

    items.forEach(item => {
        const name = item.querySelector('.session-item-name').textContent.toLowerCase();
        const preview = item.querySelector('.session-item-preview')?.textContent.toLowerCase() || '';

        if (name.includes(lowerQuery) || preview.includes(lowerQuery)) {
            item.classList.remove('hidden');
        } else {
            item.classList.add('hidden');
        }
    });
}

// Session rename
function enableRename() {
    elements.sessionName.contentEditable = 'true';
    elements.sessionName.focus();

    // Select all text
    const range = document.createRange();
    range.selectNodeContents(elements.sessionName);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
}

async function finishRename() {
    elements.sessionName.contentEditable = 'false';
    const newName = elements.sessionName.textContent.trim();

    if (newName && state.currentSessionId) {
        try {
            const response = await fetch(`/api/sessions/${state.currentSessionId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName }),
            });

            if (response.ok) {
                // Update the session in the sidebar
                const item = document.querySelector(
                    `.session-item[data-session-id="${state.currentSessionId}"]`
                );
                if (item) {
                    item.querySelector('.session-item-name').textContent = newName;
                }
                toast.success('Session renamed');
            } else {
                toast.error('Failed to rename session');
            }
        } catch (error) {
            console.error('Failed to rename session:', error);
            toast.error('Failed to rename session');
        }
    }
}

// Delete session functionality
function showDeleteModal() {
    elements.deleteModal?.classList.remove('hidden');
}

function hideDeleteModal() {
    elements.deleteModal?.classList.add('hidden');
}

async function deleteCurrentSession() {
    if (!state.currentSessionId) return;

    try {
        const response = await fetch(`/api/sessions/${state.currentSessionId}`, {
            method: 'DELETE',
        });

        if (response.ok) {
            hideDeleteModal();
            toast.success('Session deleted');

            // Remove from sidebar
            const item = document.querySelector(
                `.session-item[data-session-id="${state.currentSessionId}"]`
            );
            if (item) item.remove();

            // Close WebSocket and reset state
            if (state.ws) {
                state.ws.close();
                state.ws = null;
            }
            state.currentSessionId = null;

            // Show welcome screen
            elements.welcomeScreen?.classList.remove('hidden');
            elements.chatContainer?.classList.add('hidden');
        } else {
            toast.error('Failed to delete session');
        }
    } catch (error) {
        console.error('Failed to delete session:', error);
        toast.error('Failed to delete session');
    }
}

async function changeModel(modelName) {
    try {
        const response = await fetch('/api/config/model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelName }),
        });

        if (response.ok) {
            const data = await response.json();
            if (state.config) {
                state.config.active_model = data.model;
            }
            toast.success(`Model changed to ${modelName}`);
        } else {
            toast.error('Failed to change model');
        }
    } catch (error) {
        console.error('Failed to change model:', error);
        toast.error('Failed to change model');
    }
}

// File handling
function handleFileSelect(files) {
    for (const file of files) {
        if (file.size > 10 * 1024 * 1024) {
            alert(`File ${file.name} is too large (max 10MB)`);
            continue;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            const fileData = {
                name: file.name,
                type: file.type,
                size: file.size,
                data: e.target.result.split(',')[1], // base64 without prefix
            };

            // For images, also store the data URL for preview
            if (file.type.startsWith('image/')) {
                fileData.preview = e.target.result;
            }

            state.attachedFiles.push(fileData);
            renderFilePreview();
            updateSendButton();
        };
        reader.readAsDataURL(file);
    }
}

function renderFilePreview() {
    elements.filePreviewList.innerHTML = '';

    if (state.attachedFiles.length === 0) {
        elements.filePreviewContainer.classList.add('hidden');
        return;
    }

    elements.filePreviewContainer.classList.remove('hidden');

    state.attachedFiles.forEach((file, index) => {
        const item = document.createElement('div');
        item.className = 'file-preview-item';

        let preview;
        if (file.preview) {
            preview = `<img src="${file.preview}" alt="${escapeHtml(file.name)}" />`;
        } else {
            preview = `
                <div class="file-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/>
                    </svg>
                </div>
            `;
        }

        item.innerHTML = `
            ${preview}
            <span class="file-preview-name">${escapeHtml(file.name)}</span>
            <button class="file-preview-remove" data-index="${index}">&times;</button>
        `;

        item.querySelector('.file-preview-remove').addEventListener('click', (e) => {
            e.stopPropagation();
            removeFile(index);
        });

        elements.filePreviewList.appendChild(item);
    });
}

function removeFile(index) {
    state.attachedFiles.splice(index, 1);
    renderFilePreview();
    updateSendButton();
}

function clearAttachedFiles() {
    state.attachedFiles = [];
    renderFilePreview();
}

// Drag and drop
function setupDragAndDrop() {
    const wrapper = elements.inputWrapper;

    wrapper.addEventListener('dragover', (e) => {
        e.preventDefault();
        wrapper.classList.add('drag-over');
    });

    wrapper.addEventListener('dragleave', (e) => {
        e.preventDefault();
        wrapper.classList.remove('drag-over');
    });

    wrapper.addEventListener('drop', (e) => {
        e.preventDefault();
        wrapper.classList.remove('drag-over');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileSelect(files);
        }
    });
}

// Web search toggle
function toggleSearch() {
    state.searchEnabled = !state.searchEnabled;
    elements.searchToggle.classList.toggle('active', state.searchEnabled);
    elements.searchToggle.setAttribute('aria-pressed', state.searchEnabled);
    elements.searchIndicator.classList.toggle('hidden', !state.searchEnabled);
}

// Image modal
function showImageModal(src) {
    elements.imageModalImg.src = src;
    elements.imageModal.classList.remove('hidden');
}

function hideImageModal() {
    elements.imageModal.classList.add('hidden');
    elements.imageModalImg.src = '';
}

// Utility functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatRelativeTime(date) {
    const now = new Date();
    const diff = now - date;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 7) {
        return date.toLocaleDateString();
    } else if (days > 0) {
        return `${days}d ago`;
    } else if (hours > 0) {
        return `${hours}h ago`;
    } else if (minutes > 0) {
        return `${minutes}m ago`;
    } else {
        return 'Just now';
    }
}

// Event listeners
function setupEventListeners() {
    // Message input
    elements.messageInput.addEventListener('input', () => {
        updateSendButton();
        autoResizeTextarea();
    });

    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    elements.sendBtn.addEventListener('click', sendMessage);

    // New session
    elements.newSessionBtn.addEventListener('click', () => createSession());
    elements.startChatBtn.addEventListener('click', () => createSession());

    // Tool approval
    elements.approveToolBtn.addEventListener('click', () => respondToApproval(true));
    elements.denyToolBtn.addEventListener('click', () => respondToApproval(false));
    elements.approvalClose.addEventListener('click', () => respondToApproval(false));
    elements.approvalModal.querySelector('.modal-backdrop').addEventListener('click', () => {
        respondToApproval(false);
    });

    // Theme toggle
    elements.themeToggle?.addEventListener('click', toggleTheme);
    elements.themeToggleMobile?.addEventListener('click', toggleTheme);

    // Mobile sidebar
    elements.menuToggle?.addEventListener('click', openSidebar);
    elements.sidebarOverlay?.addEventListener('click', closeSidebar);

    // Session search
    elements.sessionSearch?.addEventListener('input', (e) => {
        filterSessions(e.target.value);
    });

    // Session rename
    elements.renameBtn?.addEventListener('click', enableRename);
    elements.sessionName?.addEventListener('blur', finishRename);
    elements.sessionName?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            finishRename();
        }
        if (e.key === 'Escape') {
            elements.sessionName.contentEditable = 'false';
        }
    });

    // Session delete
    elements.deleteSessionBtn?.addEventListener('click', showDeleteModal);
    elements.deleteModalClose?.addEventListener('click', hideDeleteModal);
    elements.cancelDeleteBtn?.addEventListener('click', hideDeleteModal);
    elements.confirmDeleteBtn?.addEventListener('click', deleteCurrentSession);
    elements.deleteModal?.querySelector('.modal-backdrop')?.addEventListener('click', hideDeleteModal);

    // File upload
    elements.attachBtn?.addEventListener('click', () => {
        elements.fileInput.click();
    });

    elements.fileInput?.addEventListener('change', (e) => {
        handleFileSelect(e.target.files);
        e.target.value = ''; // Reset for same file selection
    });

    // Model selector
    elements.modelSelect?.addEventListener('change', (e) => {
        changeModel(e.target.value);
    });

    // Search toggle
    elements.searchToggle?.addEventListener('click', toggleSearch);
    elements.searchClose?.addEventListener('click', toggleSearch);

    // Image modal
    elements.imageModalClose?.addEventListener('click', hideImageModal);
    elements.imageModal?.querySelector('.modal-backdrop')?.addEventListener('click', hideImageModal);

    // Click on images in messages
    elements.messages.addEventListener('click', (e) => {
        if (e.target.tagName === 'IMG' && e.target.closest('.message-content')) {
            showImageModal(e.target.src);
        }
    });

    // Drag and drop
    setupDragAndDrop();
}

// Initialize
async function init() {
    initTheme();
    setupEventListeners();

    await Promise.all([
        loadSessions(),
        loadConfig(),
    ]);

    // Check for session ID in URL
    const urlParams = new URLSearchParams(window.location.search);
    const sessionId = urlParams.get('session');
    if (sessionId) {
        await selectSession(sessionId);
    }
}

init();
