// ── Chat elements ──────────────────────────────────────────────────────────
const messagesEl       = document.getElementById('messages');
const form             = document.getElementById('chat-form');
const input            = document.getElementById('input');
const sendBtn          = document.getElementById('send-btn');
const clearBtn         = document.getElementById('clear-btn');
const tokenUsedEl      = document.getElementById('token-used');
const tokenLimitEl     = document.getElementById('token-limit');
const tokenBarFill     = document.getElementById('token-bar-fill');
const tokenWarning     = document.getElementById('token-warning');
const resetTokensBtn   = document.getElementById('reset-tokens-btn');

// ── Memory elements ────────────────────────────────────────────────────────
const refreshMemBtn    = document.getElementById('refresh-memory-btn');
const memStCount       = document.getElementById('mem-st-count');
const memStBarFill     = document.getElementById('mem-st-bar-fill');
const memSummaryToggle = document.getElementById('mem-summary-toggle');
const memSummaryBody   = document.getElementById('mem-summary-body');
const memTaskText      = document.getElementById('mem-task-text');
const memTaskDoneBtn   = document.getElementById('mem-task-done-btn');
const memTaskInput     = document.getElementById('mem-task-input');
const memFactsList     = document.getElementById('mem-facts-list');
const memFactKey       = document.getElementById('mem-fact-key');
const memFactVal       = document.getElementById('mem-fact-val');
const memAddFactBtn    = document.getElementById('mem-add-fact-btn');
const memLtList        = document.getElementById('mem-lt-list');
const memLtKey         = document.getElementById('mem-lt-key');
const memLtVal         = document.getElementById('mem-lt-val');
const memAddLtBtn      = document.getElementById('mem-add-lt-btn');
const memTabs          = document.querySelectorAll('.mem-tab');

let currentLtCategory = 'profile';

const WARNING_THRESHOLD = 0.8;

// ── Token panel ────────────────────────────────────────────────────────────
function updateTokenDisplay(stats) {
    const used  = stats.total_tokens ?? 0;
    const limit = stats.limit ?? 1_000_000;
    const pct   = limit > 0 ? Math.min(used / limit, 1) : 0;

    tokenUsedEl.textContent  = used.toLocaleString();
    tokenLimitEl.textContent = limit.toLocaleString();
    tokenBarFill.style.width = `${(pct * 100).toFixed(2)}%`;

    tokenBarFill.className = 'token-bar-fill';
    if      (pct >= 1)                 tokenBarFill.classList.add('danger');
    else if (pct >= WARNING_THRESHOLD) tokenBarFill.classList.add('warn');

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

// ── Chat ───────────────────────────────────────────────────────────────────
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
    sendBtn.disabled  = loading;
    input.disabled    = loading;
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
                (u.response_time_ms != null
                    ? ` · <span class="mu-time"><b>time:</b> ${(u.response_time_ms / 1000).toFixed(2)} s</span>`
                    : '');
            msgEl.appendChild(tokens);
        }

        await Promise.all([loadTokenStats(), loadMemory(), loadShortTerm()]);
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

input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        form.dispatchEvent(new Event('submit'));
    }
});

input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = `${input.scrollHeight}px`;
});

clearBtn.addEventListener('click', async () => {
    await fetch('/history', { method: 'DELETE' });
    messagesEl.innerHTML = '<div class="empty-state">Start a conversation...</div>';
    await loadShortTerm();
});

// ── Memory panel ───────────────────────────────────────────────────────────

function renderEntry(key, value, onDelete) {
    const el = document.createElement('div');
    el.className = 'mem-entry';
    el.innerHTML =
        `<span class="mem-entry-text">` +
            `<span class="mem-entry-key">${escHtml(key)}:</span> ` +
            `<span class="mem-entry-val">${escHtml(value)}</span>` +
        `</span>` +
        `<button class="mem-del-btn" title="Delete">×</button>`;
    el.querySelector('.mem-del-btn').addEventListener('click', onDelete);
    return el;
}

function renderEmptyNote(list) {
    const el = document.createElement('div');
    el.className = 'mem-empty';
    el.textContent = '(empty)';
    list.appendChild(el);
}

function renderWorkingMemory(w) {
    if (w.task) {
        memTaskText.textContent = w.task;
        memTaskText.classList.remove('empty');
        memTaskDoneBtn.hidden = false;
    } else {
        memTaskText.textContent = '(no task)';
        memTaskText.classList.add('empty');
        memTaskDoneBtn.hidden = true;
    }

    memFactsList.innerHTML = '';
    if (w.facts && w.facts.length > 0) {
        w.facts.forEach(f => {
            memFactsList.appendChild(renderEntry(f.key, f.value, async () => {
                await apiDeleteWorkingFact(f.key);
                await loadMemory();
            }));
        });
    } else {
        renderEmptyNote(memFactsList);
    }
}

function renderLongTermMemory(entries) {
    memLtList.innerHTML = '';
    if (entries && entries.length > 0) {
        entries.forEach(e => {
            memLtList.appendChild(renderEntry(e.key, e.value, async () => {
                await apiDeleteLtEntry(currentLtCategory, e.key);
                await loadMemory();
            }));
        });
    } else {
        renderEmptyNote(memLtList);
    }
}

async function loadMemory() {
    try {
        const res = await fetch('/memory');
        if (!res.ok) return;
        const data = await res.json();
        renderWorkingMemory(data.working);
        renderLongTermMemory(data.long_term[currentLtCategory]);
    } catch (_) {}
}

// Short-term memory
async function loadShortTerm() {
    try {
        const res = await fetch('/memory/short-term');
        if (!res.ok) return;
        const { message_count, max_history, summary } = await res.json();

        const pct = max_history > 0 ? Math.min(message_count / max_history, 1) : 0;
        memStCount.textContent = `${message_count} / ${max_history} messages`;
        memStBarFill.style.width = `${(pct * 100).toFixed(1)}%`;
        memStBarFill.className = 'mem-st-bar-fill';
        if      (pct >= 1)   memStBarFill.classList.add('danger');
        else if (pct >= 0.7) memStBarFill.classList.add('warn');

        if (summary) {
            memSummaryBody.textContent = summary;
            memSummaryBody.classList.remove('empty');
            memSummaryToggle.classList.add('has-summary');
        } else {
            memSummaryBody.textContent = '(none)';
            memSummaryBody.classList.add('empty');
            memSummaryToggle.classList.remove('has-summary');
        }
    } catch (_) {}
}

loadMemory();
loadShortTerm();
refreshMemBtn.addEventListener('click', () => { loadMemory(); loadShortTerm(); });

// Tab switching
memTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        memTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        currentLtCategory = tab.dataset.cat;
        loadMemory();
    });
});

// Set task on Enter
memTaskInput.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter') return;
    const desc = memTaskInput.value.trim();
    if (!desc) return;
    await fetch('/memory/working/task', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: desc }),
    });
    memTaskInput.value = '';
    await loadMemory();
});

// Complete task
memTaskDoneBtn.addEventListener('click', async () => {
    await fetch('/memory/working', { method: 'DELETE' });
    await loadMemory();
});

// Add working fact
memAddFactBtn.addEventListener('click', async () => {
    const key = memFactKey.value.trim();
    const val = memFactVal.value.trim();
    if (!key || !val) return;
    await fetch('/memory/working/fact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value: val }),
    });
    memFactKey.value = '';
    memFactVal.value = '';
    await loadMemory();
});

// Add long-term entry
memAddLtBtn.addEventListener('click', async () => {
    const key = memLtKey.value.trim();
    const val = memLtVal.value.trim();
    if (!key || !val) return;
    await fetch(`/memory/long-term/${currentLtCategory}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value: val }),
    });
    memLtKey.value = '';
    memLtVal.value = '';
    await loadMemory();
});

// API helpers
async function apiDeleteWorkingFact(key) {
    await fetch(`/memory/working/fact/${encodeURIComponent(key)}`, { method: 'DELETE' });
}

async function apiDeleteLtEntry(category, key) {
    const encodedKey = encodeURIComponent(key);
    await fetch(`/memory/long-term/${category}/${encodedKey}`, { method: 'DELETE' });
}

function escHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}