// ── State ──────────────────────────────────────────────────────────────────

let currentStrategy = 'sliding_window';
let windowSizeTimer = null;
let factsOpen = true;

// ── DOM refs ───────────────────────────────────────────────────────────────

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
const windowSizeInput  = document.getElementById('window-size-input');
const windowSizeSfInput = document.getElementById('window-size-sf-input');
const checkpointBtn    = document.getElementById('checkpoint-btn');
const branchTabs       = document.getElementById('branch-tabs');
const factsToggleBtn   = document.getElementById('facts-toggle-btn');
const factsPanel       = document.getElementById('facts-panel');
const factsList        = document.getElementById('facts-list');
const factsEmpty       = document.getElementById('facts-empty');

const WARNING_THRESHOLD = 0.8;

// ── Tokens ─────────────────────────────────────────────────────────────────

function updateTokenDisplay(stats) {
    const used  = stats.total_tokens ?? 0;
    const limit = stats.limit ?? 1_000_000;
    const pct   = limit > 0 ? Math.min(used / limit, 1) : 0;
    tokenUsedEl.textContent  = used.toLocaleString();
    tokenLimitEl.textContent = limit.toLocaleString();
    tokenBarFill.style.width = `${(pct * 100).toFixed(2)}%`;
    tokenBarFill.className   = 'token-bar-fill';
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

resetTokensBtn.addEventListener('click', async () => {
    await fetch('/tokens', { method: 'DELETE' });
    updateTokenDisplay({ total_tokens: 0, limit: 1_000_000 });
});

// ── Strategy ───────────────────────────────────────────────────────────────

function showStrategyOptions(strategy) {
    document.querySelectorAll('.strategy-options').forEach(el => { el.hidden = true; });
    const el = document.getElementById(`options-${strategy}`);
    if (el) el.hidden = false;
}

function activateStrategyBtn(strategy) {
    document.querySelectorAll('.strategy-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.strategy === strategy);
    });
}

function currentWindowSize() {
    if (currentStrategy === 'sticky_facts') {
        return parseInt(windowSizeSfInput.value) || 10;
    }
    return parseInt(windowSizeInput.value) || 10;
}

async function applyStrategy(strategy, windowSize) {
    const body = { strategy };
    if (windowSize !== undefined) body.window_size = windowSize;
    try {
        const res = await fetch('/strategy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (res.ok) {
            const data = await res.json();
            currentStrategy = data.strategy;
            activateStrategyBtn(currentStrategy);
            showStrategyOptions(currentStrategy);
            await Promise.all([reloadMessages(), loadTokenStats()]);
            if (currentStrategy === 'branching') await loadBranches();
            if (currentStrategy === 'sticky_facts') await loadFacts();
        }
    } catch (_) {}
}

async function loadStrategy() {
    try {
        const res = await fetch('/strategy');
        if (!res.ok) return;
        const data = await res.json();
        currentStrategy = data.strategy;
        const ws = data.window_size ?? 10;
        windowSizeInput.value   = ws;
        windowSizeSfInput.value = ws;
        activateStrategyBtn(currentStrategy);
        showStrategyOptions(currentStrategy);
    } catch (_) {}
}

document.querySelectorAll('.strategy-btn').forEach(btn => {
    btn.addEventListener('click', () => applyStrategy(btn.dataset.strategy, currentWindowSize()));
});

function onWindowSizeChange(input) {
    clearTimeout(windowSizeTimer);
    windowSizeTimer = setTimeout(() => {
        applyStrategy(currentStrategy, parseInt(input.value) || 10);
    }, 600);
}

windowSizeInput.addEventListener('input',   () => onWindowSizeChange(windowSizeInput));
windowSizeSfInput.addEventListener('input', () => onWindowSizeChange(windowSizeSfInput));

// ── Sticky Facts ───────────────────────────────────────────────────────────

factsToggleBtn.addEventListener('click', () => {
    factsOpen = !factsOpen;
    factsPanel.hidden    = !factsOpen;
    factsToggleBtn.textContent = factsOpen ? 'Facts ▾' : 'Facts ▸';
});

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function renderFacts(facts) {
    const entries = Object.entries(facts);
    if (entries.length === 0) {
        factsEmpty.hidden = false;
        factsList.innerHTML = '';
        return;
    }
    factsEmpty.hidden   = true;
    factsList.innerHTML = entries
        .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`)
        .join('');
}

async function loadFacts() {
    try {
        const res = await fetch('/facts');
        if (res.ok) renderFacts((await res.json()).facts ?? {});
    } catch (_) {}
}

// ── Branching ──────────────────────────────────────────────────────────────

function renderBranches(branches) {
    branchTabs.innerHTML = '';
    branches.forEach(b => {
        const btn = document.createElement('button');
        btn.className   = 'branch-tab' + (b.active ? ' active' : '');
        btn.textContent = `${b.name} (${b.message_count})`;
        btn.dataset.branchId = b.id;
        btn.title = b.active ? 'Active branch' : 'Switch to this branch';
        btn.addEventListener('click', () => switchBranch(b.id));
        branchTabs.appendChild(btn);
    });
}

async function loadBranches() {
    try {
        const res = await fetch('/branches');
        if (res.ok) renderBranches((await res.json()).branches ?? []);
    } catch (_) {}
}

checkpointBtn.addEventListener('click', async () => {
    try {
        const res = await fetch('/checkpoint', { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            renderBranches(data.branches ?? []);
            await reloadMessages();
        }
    } catch (_) {}
});

async function switchBranch(branchId) {
    try {
        const res = await fetch('/branch/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ branch_id: branchId }),
        });
        if (res.ok) {
            const data = await res.json();
            await loadBranches();
            renderHistory(data.history ?? []);
        }
    } catch (_) {}
}

// ── Messages ───────────────────────────────────────────────────────────────

function appendMessage(role, text, usage) {
    const emptyState = messagesEl.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    const el       = document.createElement('div');
    el.className   = `message ${role}`;
    el.textContent = text;
    if (usage && role === 'assistant') el.appendChild(buildUsageEl(usage));
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
}

function buildUsageEl(u) {
    const el = document.createElement('div');
    el.className = 'token-usage';
    el.innerHTML =
        `<span class="mu-prompt"><b>prompt:</b> ${u.prompt_tokens ?? '?'}</span>` +
        ` · <span class="mu-completion"><b>completion:</b> ${u.completion_tokens ?? '?'}</span>` +
        ` · <span class="mu-total"><b>total:</b> ${u.total_tokens ?? '?'}</span>` +
        (u.response_time_ms != null
            ? ` · <span class="mu-time"><b>time:</b> ${(u.response_time_ms / 1000).toFixed(2)} s</span>`
            : '');
    return el;
}

function renderHistory(history) {
    messagesEl.innerHTML = '';
    if (!history.length) {
        messagesEl.innerHTML = '<div class="empty-state">Start a conversation...</div>';
        return;
    }
    history.forEach(msg => appendMessage(msg.role, msg.content, msg.usage));
}

async function reloadMessages() {
    try {
        const res = await fetch('/history');
        if (res.ok) renderHistory((await res.json()).history ?? []);
    } catch (_) {}
}

function setLoading(loading) {
    sendBtn.disabled = loading;
    input.disabled   = loading;
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

        const data  = await res.json();
        thinking.remove();
        appendMessage('assistant', data.response, data.usage);

        await loadTokenStats();

        if (currentStrategy === 'sticky_facts') await loadFacts();
        if (currentStrategy === 'branching')    await loadBranches();

    } catch (err) {
        thinking.remove();
        appendMessage('error', `Error: ${err.message}`);
    } finally {
        setLoading(false);
        input.focus();
    }
}

// ── Form & input events ────────────────────────────────────────────────────

form.addEventListener('submit', e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value        = '';
    input.style.height = 'auto';
    sendMessage(text);
});

input.addEventListener('keydown', e => {
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
    if (currentStrategy === 'sticky_facts') renderFacts({});
    if (currentStrategy === 'branching')    await loadBranches();
});

// ── Init ───────────────────────────────────────────────────────────────────

async function init() {
    await loadStrategy();
    await loadTokenStats();
    await reloadMessages();
    if (currentStrategy === 'sticky_facts') await loadFacts();
    if (currentStrategy === 'branching')    await loadBranches();
}

init();
