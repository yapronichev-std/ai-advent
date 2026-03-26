const messagesEl = document.getElementById('messages');
const form = document.getElementById('chat-form');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send-btn');
const clearBtn = document.getElementById('clear-btn');
const tokenUsedEl = document.getElementById('token-used');
const tokenLimitEl = document.getElementById('token-limit');
const tokenBarFill = document.getElementById('token-bar-fill');
const tokenWarning = document.getElementById('token-warning');
const resetTokensBtn = document.getElementById('reset-tokens-btn');

const WARNING_THRESHOLD = 0.8;

function updateTokenDisplay(stats) {
    const used = stats.total_tokens ?? 0;
    const limit = stats.limit ?? 1_000_000;
    const pct = limit > 0 ? Math.min(used / limit, 1) : 0;

    tokenUsedEl.textContent = used.toLocaleString();
    tokenLimitEl.textContent = limit.toLocaleString();
    tokenBarFill.style.width = `${(pct * 100).toFixed(2)}%`;

    tokenBarFill.className = 'token-bar-fill';
    if (pct >= WARNING_THRESHOLD && pct < 1) tokenBarFill.classList.add('warn');
    else if (pct >= 1) tokenBarFill.classList.add('danger');

    tokenWarning.hidden = pct < WARNING_THRESHOLD;
}

async function loadTokenStats() {
    try {
        const res = await fetch('/tokens');
        if (res.ok) updateTokenDisplay(await res.json());
    } catch (_) {}
}

loadTokenStats();

resetTokensBtn.addEventListener('click', async () => {
    await fetch('/tokens', { method: 'DELETE' });
    updateTokenDisplay({ total_tokens: 0, limit: 1_000_000 });
});

function appendMessage(role, text) {
    const emptyState = messagesEl.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    const el = document.createElement('div');
    el.className = `message ${role}`;
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
}

function setLoading(loading) {
    sendBtn.disabled = loading;
    input.disabled = loading;
}

async function sendMessage(text) {
    appendMessage('user', text);
    const thinking = appendMessage('thinking', 'Thinking...');
    setLoading(true);

    try {
        const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        const data = await res.json();
        thinking.remove();
        const msgEl = appendMessage('assistant', data.response);
        if (data.usage) {
            const u = data.usage;
            const tokens = document.createElement('div');
            tokens.className = 'token-usage';
            tokens.innerHTML =
                `<span class="mu-prompt"><b>prompt:</b> ${u.prompt_tokens ?? '?'}</span>` +
                ` · <span class="mu-completion"><b>completion:</b> ${u.completion_tokens ?? '?'}</span>` +
                ` · <span class="mu-total"><b>total:</b> ${u.total_tokens ?? '?'}</span>` +
                (u.response_time_ms != null ? ` · <span class="mu-time"><b>time:</b> ${(u.response_time_ms / 1000).toFixed(2)} s</span>` : '');
            msgEl.appendChild(tokens);
        }
        await loadTokenStats();
    } catch (err) {
        thinking.remove();
        appendMessage('error', `Error: ${err.message}`);
    } finally {
        setLoading(false);
        input.focus();
    }
}

form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.style.height = 'auto';
    sendMessage(text);
});

// Submit on Enter, new line on Shift+Enter
input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        form.dispatchEvent(new Event('submit'));
    }
});

// Auto-resize textarea
input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = `${input.scrollHeight}px`;
});

clearBtn.addEventListener('click', async () => {
    await fetch('/history', { method: 'DELETE' });
    messagesEl.innerHTML = '<div class="empty-state">Start a conversation...</div>';
});
