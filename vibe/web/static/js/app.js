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
};

// DOM elements
const elements = {
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
    modelInfo: document.getElementById('modelInfo'),
    approvalModal: document.getElementById('approvalModal'),
    approvalToolName: document.getElementById('approvalToolName'),
    approvalToolArgs: document.getElementById('approvalToolArgs'),
    approveToolBtn: document.getElementById('approveToolBtn'),
    denyToolBtn: document.getElementById('denyToolBtn'),
};

// Initialize marked for markdown rendering
marked.setOptions({
    highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
    },
    breaks: true,
    gfm: true,
});

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
        updateModelInfo();
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

    // Update active session in sidebar
    document.querySelectorAll('.session-item').forEach(item => {
        item.classList.toggle('active', item.dataset.sessionId === sessionId);
    });

    // Connect WebSocket
    connectWebSocket(sessionId);
}

function connectWebSocket(sessionId) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat/${sessionId}`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        console.log('WebSocket connected');
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

    state.ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateSendButton();
    };

    state.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
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
    contentEl.innerHTML = marked.parse(newContent);

    scrollToBottom();
}

function handleAssistantDone(data) {
    state.isStreaming = false;
    updateSendButton();

    const streamingMessage = document.querySelector('.message.assistant.streaming');
    if (streamingMessage) {
        streamingMessage.classList.remove('streaming');

        // Remove streaming indicator if present
        const indicator = streamingMessage.querySelector('.streaming-indicator');
        if (indicator) {
            indicator.remove();
        }
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
            <span class="tool-call-icon">&#9881;</span>
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
            resultEl.textContent += ` (${data.duration.toFixed(2)}s)`;
        }

        toolCallEl.querySelector('.tool-call-body').appendChild(resultEl);
    }

    scrollToBottom();
}

function handleToolApprovalRequest(data) {
    state.pendingApproval = data;

    elements.approvalToolName.textContent = data.tool_name;
    elements.approvalToolArgs.textContent = JSON.stringify(data.arguments, null, 2);
    elements.approvalModal.classList.remove('hidden');
}

function handleReasoning(data) {
    // Could display reasoning in a collapsible section
    console.log('Reasoning:', data.content);
}

function handleError(data) {
    state.isStreaming = false;
    updateSendButton();

    const errorEl = document.createElement('div');
    errorEl.className = 'message error';
    errorEl.innerHTML = `
        <div class="message-content" style="color: var(--error);">
            Error: ${escapeHtml(data.message)}
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

        item.addEventListener('click', () => selectSession(session.id));
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
    contentEl.innerHTML = marked.parse(content);
    elements.messages.appendChild(messageEl);
}

function updateModelInfo() {
    if (state.config) {
        const modelName = elements.modelInfo.querySelector('.model-name');
        modelName.textContent = state.config.active_model;
    }
}

function updateSessionStats(stats) {
    if (stats) {
        const tokens = stats.session_total_llm_tokens || 0;
        const cost = stats.session_cost || 0;
        elements.sessionStats.textContent = `${tokens} tokens | $${cost.toFixed(4)}`;
    }
}

function updateSendButton() {
    const hasContent = elements.messageInput.value.trim().length > 0;
    const isConnected = state.ws && state.ws.readyState === WebSocket.OPEN;
    const canSend = hasContent && isConnected && !state.isStreaming;

    elements.sendBtn.disabled = !canSend;
}

function scrollToBottom() {
    elements.messagesContainer.scrollTop = elements.messagesContainer.scrollHeight;
}

function sendMessage() {
    const content = elements.messageInput.value.trim();
    if (!content || !state.ws || state.ws.readyState !== WebSocket.OPEN) {
        return;
    }

    // Add user message to UI
    appendUserMessage(content);
    scrollToBottom();

    // Send via WebSocket
    state.ws.send(JSON.stringify({
        type: MessageType.USER_MESSAGE,
        data: { content },
    }));

    // Clear input
    elements.messageInput.value = '';
    updateSendButton();
    autoResizeTextarea();
}

function respondToApproval(approved) {
    if (!state.pendingApproval || !state.ws) {
        return;
    }

    state.ws.send(JSON.stringify({
        type: MessageType.TOOL_APPROVAL_RESPONSE,
        data: {
            tool_call_id: state.pendingApproval.tool_call_id,
            approved,
            always_allow: false,
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

elements.newSessionBtn.addEventListener('click', () => createSession());
elements.startChatBtn.addEventListener('click', () => createSession());

elements.approveToolBtn.addEventListener('click', () => respondToApproval(true));
elements.denyToolBtn.addEventListener('click', () => respondToApproval(false));

// Close modal on backdrop click
elements.approvalModal.querySelector('.modal-backdrop').addEventListener('click', () => {
    respondToApproval(false);
});

// Initialize
async function init() {
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
