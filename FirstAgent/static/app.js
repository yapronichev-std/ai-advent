// ── State ───────────────────────────────────────────────────────────────────
let currentUserId = 'default';

// ── Main tab switching ───────────────────────────────────────────────────────
document.querySelectorAll('.main-nav-tab').forEach(btn => {
    btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        document.querySelectorAll('.main-nav-tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.main-tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`tab-${tab}`).classList.add('active');
        if (tab === 'rag') loadRagDocuments();
    });
});

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

// ── System prompt elements ─────────────────────────────────────────────────
const syspromptInput   = document.getElementById('sysprompt-input');
const syspromptSaveBtn = document.getElementById('sysprompt-save-btn');
const syspromptStatus  = document.getElementById('sysprompt-status');

// ── User selector elements ─────────────────────────────────────────────────
const userSelect       = document.getElementById('user-select');
const userAddBtn       = document.getElementById('user-add-btn');
const userDelBtn       = document.getElementById('user-del-btn');
const userNewRow       = document.getElementById('user-new-row');
const userNewInput     = document.getElementById('user-new-input');
const userNewConfirm   = document.getElementById('user-new-confirm');
const userNewCancel    = document.getElementById('user-new-cancel');

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
const taskFsmBar       = document.getElementById('task-fsm-bar');
const taskFsmMeta      = document.getElementById('task-fsm-meta');
const taskFsmStates    = document.querySelectorAll('.task-fsm-state');

let currentLtCategory = 'profile';
const WARNING_THRESHOLD = 0.8;

// ── User management ─────────────────────────────────────────────────────────

async function loadUsers() {
    try {
        const res = await fetch('/users');
        if (!res.ok) return;
        const { users } = await res.json();

        userSelect.innerHTML = '';
        const all = users.includes('default') ? users : ['default', ...users];
        all.forEach(uid => {
            const opt = document.createElement('option');
            opt.value = uid;
            opt.textContent = uid;
            if (uid === currentUserId) opt.selected = true;
            userSelect.appendChild(opt);
        });
        // Ensure current user exists in list (edge case after creation)
        if (!all.includes(currentUserId)) {
            const opt = document.createElement('option');
            opt.value = currentUserId;
            opt.textContent = currentUserId;
            opt.selected = true;
            userSelect.appendChild(opt);
        }
    } catch (_) {}
}

async function switchUser(uid) {
    currentUserId = uid;
    messagesEl.innerHTML = '<div class="empty-state">Start a conversation...</div>';
    await Promise.all([loadTokenStats(), loadMemory(), loadShortTerm()]);
}

userSelect.addEventListener('change', () => switchUser(userSelect.value));

userAddBtn.addEventListener('click', () => {
    userNewRow.hidden = false;
    userNewInput.focus();
});

userNewCancel.addEventListener('click', () => {
    userNewRow.hidden = true;
    userNewInput.value = '';
});

async function createUser() {
    const uid = userNewInput.value.trim().replace(/\s+/g, '_');
    if (!uid) return;
    userNewRow.hidden = true;
    userNewInput.value = '';
    currentUserId = uid;
    await loadUsers();
    await switchUser(uid);
}

userNewConfirm.addEventListener('click', createUser);
userNewInput.addEventListener('keydown', e => { if (e.key === 'Enter') createUser(); });

userDelBtn.addEventListener('click', async () => {
    if (currentUserId === 'default') {
        alert('Cannot delete the default user.');
        return;
    }
    if (!confirm(`Delete user "${currentUserId}" and all their data?`)) return;
    await fetch(`/users/${encodeURIComponent(currentUserId)}`, { method: 'DELETE' });
    currentUserId = 'default';
    await loadUsers();
    await switchUser('default');
});

// ── System prompt ──────────────────────────────────────────────────────────

async function loadSystemPrompt() {
    try {
        const res = await fetch('/system-prompt');
        if (res.ok) {
            const { prompt } = await res.json();
            syspromptInput.value = prompt;
        }
    } catch (_) {}
}

syspromptSaveBtn.addEventListener('click', async () => {
    const prompt = syspromptInput.value;
    try {
        const res = await fetch('/system-prompt', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt }),
        });
        if (res.ok) {
            syspromptStatus.textContent = 'Saved';
            setTimeout(() => { syspromptStatus.textContent = ''; }, 2000);
        }
    } catch (_) {}
});

loadSystemPrompt();

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
        const res = await fetch(`/tokens?user_id=${encodeURIComponent(currentUserId)}`);
        if (res.ok) updateTokenDisplay(await res.json());
    } catch (_) {}
}

loadTokenStats();

resetTokensBtn.addEventListener('click', async () => {
    await fetch(`/tokens?user_id=${encodeURIComponent(currentUserId)}`, { method: 'DELETE' });
    updateTokenDisplay({ total_tokens: 0, limit: 1_000_000 });
});

// ── Chat ───────────────────────────────────────────────────────────────────

/** Fetch XML from url and inject a draw.io viewer widget into container. */
async function renderDiagram(url, container) {
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const xml = await res.text();

        const wrapper = document.createElement('div');
        wrapper.className = 'diagram-wrapper';

        const label = document.createElement('div');
        label.className = 'diagram-label';
        label.innerHTML =
            `<span>${escHtml(url.split('/').pop())}</span>` +
            `<a class="diagram-download" href="${url}" download>↓ скачать</a>`;

        const viewer = document.createElement('div');
        viewer.className = 'mxgraph';
        viewer.setAttribute('data-mxgraph', JSON.stringify({
            xml,
            nav: true,
            resize: true,
            toolbar: 'zoom layers lightbox',
            'auto-fit': true,
        }));

        wrapper.appendChild(label);
        wrapper.appendChild(viewer);
        container.appendChild(wrapper);

        // Let the viewer script process the new element
        if (window.GraphViewer && typeof window.GraphViewer.processElements === 'function') {
            window.GraphViewer.processElements();
        }
    } catch (err) {
        const errEl = document.createElement('div');
        errEl.className = 'diagram-error';
        errEl.textContent = `Не удалось загрузить диаграмму: ${err.message}`;
        container.appendChild(errEl);
    }
}

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

function appendDiagrams(msgEl, diagramUrls) {
    if (!diagramUrls || diagramUrls.length === 0) return;
    const container = document.createElement('div');
    container.className = 'diagrams-container';
    msgEl.appendChild(container);
    diagramUrls.forEach(url => renderDiagram(url, container));
    messagesEl.scrollTop = messagesEl.scrollHeight;
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
            body: JSON.stringify({ text, user_id: currentUserId }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        const data = await res.json();
        thinking.remove();
        const msgEl = appendMessage('assistant', data.response);
        appendDiagrams(msgEl, data.diagram_urls);

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
    await fetch(`/history?user_id=${encodeURIComponent(currentUserId)}`, { method: 'DELETE' });
    messagesEl.innerHTML = '<div class="empty-state">Start a conversation...</div>';
    await loadShortTerm();
});

// ── Invariants ─────────────────────────────────────────────────────────────

const invList    = document.getElementById('inv-list');
const invInput   = document.getElementById('inv-input');
const invAddBtn  = document.getElementById('inv-add-btn');

async function loadInvariants() {
    try {
        const res = await fetch('/invariants');
        if (!res.ok) return;
        const { invariants } = await res.json();
        renderInvariants(invariants);
    } catch (_) {}
}

function renderInvariants(invariants) {
    invList.innerHTML = '';
    if (!invariants || invariants.length === 0) {
        renderEmptyNote(invList);
        return;
    }
    invariants.forEach(inv => {
        const isActive = inv.active !== false;
        const el = document.createElement('div');
        el.className = `mem-entry inv-entry${isActive ? '' : ' inv-inactive'}`;
        el.innerHTML =
            `<button class="inv-toggle-btn mem-icon-btn" title="${isActive ? 'Disable' : 'Enable'}">${isActive ? '●' : '○'}</button>` +
            `<span class="mem-entry-text inv-text">${escHtml(inv.text)}</span>` +
            `<button class="mem-del-btn" title="Delete">×</button>`;

        el.querySelector('.mem-del-btn').addEventListener('click', async () => {
            await fetch(`/invariants/${encodeURIComponent(inv.id)}`, { method: 'DELETE' });
            await loadInvariants();
        });

        el.querySelector('.inv-toggle-btn').addEventListener('click', async () => {
            await fetch(`/invariants/${encodeURIComponent(inv.id)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ active: !isActive }),
            });
            await loadInvariants();
        });

        invList.appendChild(el);
    });
}

invAddBtn.addEventListener('click', async () => {
    const text = invInput.value.trim();
    if (!text) return;
    await fetch('/invariants', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
    });
    invInput.value = '';
    await loadInvariants();
});

invInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') invAddBtn.click();
});

loadInvariants();

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

function renderTaskFsm(ts) {
    if (!ts) {
        taskFsmBar.hidden = true;
        return;
    }
    taskFsmBar.hidden = false;

    const isBlocked = ts.state === 'blocked';
    taskFsmStates.forEach(el => {
        const s = el.dataset.state;
        el.className = 'task-fsm-state';
        if (s === ts.state || (isBlocked && s === 'execution')) {
            el.classList.add(isBlocked ? 'blocked' : 'active');
        }
        if (ts.state === 'done' && s === 'done') el.classList.add('done');
    });

    let meta = '';
    if (ts.step_total > 0) {
        meta += `${ts.step_current}/${ts.step_total}`;
        if (ts.step_description) meta += `: ${ts.step_description}`;
    }
    if (ts.expected_action && ts.expected_action !== 'none') {
        if (meta) meta += ' · ';
        meta += ts.expected_action;
    }
    taskFsmMeta.textContent = meta;
}

async function loadMemory() {
    try {
        const res = await fetch(`/memory?user_id=${encodeURIComponent(currentUserId)}`);
        if (!res.ok) return;
        const data = await res.json();
        renderWorkingMemory(data.working);
        renderTaskFsm(data.task_state);
        renderLongTermMemory(data.long_term[currentLtCategory]);
    } catch (_) {}
}

async function loadShortTerm() {
    try {
        const res = await fetch(`/memory/short-term?user_id=${encodeURIComponent(currentUserId)}`);
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

loadUsers();
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
    await fetch(`/memory/working/task?user_id=${encodeURIComponent(currentUserId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: desc }),
    });
    memTaskInput.value = '';
    await loadMemory();
});

// Complete task
memTaskDoneBtn.addEventListener('click', async () => {
    await fetch(`/memory/working?user_id=${encodeURIComponent(currentUserId)}`, { method: 'DELETE' });
    await loadMemory();
});

// Add working fact
memAddFactBtn.addEventListener('click', async () => {
    const key = memFactKey.value.trim();
    const val = memFactVal.value.trim();
    if (!key || !val) return;
    await fetch(`/memory/working/fact?user_id=${encodeURIComponent(currentUserId)}`, {
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
    await fetch(`/memory/long-term/${currentLtCategory}?user_id=${encodeURIComponent(currentUserId)}`, {
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
    await fetch(
        `/memory/working/fact/${encodeURIComponent(key)}?user_id=${encodeURIComponent(currentUserId)}`,
        { method: 'DELETE' }
    );
}

async function apiDeleteLtEntry(category, key) {
    await fetch(
        `/memory/long-term/${category}/${encodeURIComponent(key)}?user_id=${encodeURIComponent(currentUserId)}`,
        { method: 'DELETE' }
    );
}

function escHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── RAG Documents ───────────────────────────────────────────────────────────

const ragDocsList        = document.getElementById('rag-docs-list');
const ragFileInput       = document.getElementById('rag-file-input');
const ragUploadBtn       = document.querySelector('.rag-upload-btn');
const ragUploadStatus    = document.getElementById('rag-upload-status');
const ragUploadStatusIdle = document.getElementById('rag-upload-status-idle');
const ragStrategySelect  = document.getElementById('rag-strategy-select');
const ragCompareBtn      = document.getElementById('rag-compare-btn');
const ragCompareInput    = document.getElementById('rag-compare-input');
const ragCompareResult   = document.getElementById('rag-compare-result');
const ragProgressWrap    = document.getElementById('rag-progress-wrap');
const ragProgressLabel   = document.getElementById('rag-progress-label');
const ragProgressFill    = document.getElementById('rag-progress-fill');

const STRATEGY_LABELS = { fixed: 'Fixed', structural: 'Structural' };

async function loadRagDocuments() {
    try {
        const res = await fetch('/rag/documents');
        if (!res.ok) return;
        const { documents } = await res.json();
        renderRagDocuments(documents);
    } catch (_) {}
}

function renderRagDocuments(docs) {
    ragDocsList.innerHTML = '';
    if (!docs || docs.length === 0) {
        const el = document.createElement('div');
        el.className = 'mem-empty';
        el.textContent = '(no documents)';
        ragDocsList.appendChild(el);
        return;
    }
    docs.forEach(doc => {
        const label = doc.title || doc.source || doc.doc_id;
        const strategyBadge = doc.strategy ? `<span class="rag-strategy-badge rag-strategy-${doc.strategy}">${STRATEGY_LABELS[doc.strategy] || doc.strategy}</span>` : '';
        const el = document.createElement('div');
        el.className = 'rag-doc-entry';
        el.innerHTML =
            `<span class="rag-doc-name" title="${escHtml(doc.source || doc.doc_id)}">${escHtml(label)}</span>` +
            strategyBadge +
            `<span class="rag-doc-chunks">${doc.chunks} chunk${doc.chunks !== 1 ? 's' : ''}</span>` +
            `<button class="mem-del-btn" title="Delete">×</button>`;
        el.querySelector('.mem-del-btn').addEventListener('click', async () => {
            await fetch(`/rag/documents/${encodeURIComponent(doc.doc_id)}`, { method: 'DELETE' });
            await loadRagDocuments();
        });
        ragDocsList.appendChild(el);
    });
}

function setRagUploading(uploading) {
    ragUploadBtn.classList.toggle('uploading', uploading);
    ragFileInput.disabled = uploading;
    ragProgressWrap.hidden = !uploading;
    if (!uploading) {
        ragProgressFill.style.width = '0%';
        ragProgressLabel.textContent = '';
        ragUploadStatus.textContent = '';
    }
}

function setRagProgress(current, total, section) {
    const pct = total > 0 ? (current / total) * 100 : 0;
    ragProgressFill.style.width = `${pct.toFixed(1)}%`;
    ragProgressFill.className = 'rag-progress-fill' + (pct >= 100 ? ' done' : '');
    ragProgressLabel.textContent =
        `Embedding ${current} / ${total}` + (section ? ` — ${section}` : '');
}

function setRagIdleStatus(text, isError = false) {
    ragUploadStatusIdle.textContent = text;
    ragUploadStatusIdle.className = 'rag-upload-status' + (isError ? ' rag-status-error' : '');
    if (text) setTimeout(() => { ragUploadStatusIdle.textContent = ''; ragUploadStatusIdle.className = 'rag-upload-status'; }, isError ? 5000 : 3000);
}

ragFileInput.addEventListener('change', async () => {
    const file = ragFileInput.files[0];
    if (!file) return;
    ragFileInput.value = '';
    const strategy = ragStrategySelect.value || 'fixed';

    setRagUploading(true);
    setRagProgress(0, 1, `Reading ${file.name}…`);

    try {
        const text = await file.text();
        setRagProgress(0, 0, `Connecting…`);

        const res = await fetch('/rag/documents/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, source: file.name, strategy }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let finalChunks = 0;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split('\n\n');
            buffer = parts.pop(); // keep incomplete tail

            for (const part of parts) {
                const line = part.trim();
                if (!line.startsWith('data: ')) continue;
                let event;
                try { event = JSON.parse(line.slice(6)); } catch { continue; }

                if (event.type === 'start') {
                    setRagProgress(0, event.total, 'starting…');
                } else if (event.type === 'progress') {
                    setRagProgress(event.current, event.total, event.section);
                } else if (event.type === 'done') {
                    finalChunks = event.chunks;
                    setRagProgress(event.chunks, event.chunks, 'done');
                } else if (event.type === 'error') {
                    throw new Error(event.message);
                }
            }
        }

        setRagUploading(false);
        setRagIdleStatus(`✓ ${file.name} (${finalChunks} chunks, ${strategy})`);
        await loadRagDocuments();
    } catch (err) {
        setRagUploading(false);
        setRagIdleStatus(`✗ ${err.message}`, true);
    }
});

// ── Compare strategies ────────────────────────────────────────────────────────

ragCompareBtn.addEventListener('click', () => ragCompareInput.click());

ragCompareInput.addEventListener('change', async () => {
    const file = ragCompareInput.files[0];
    if (!file) return;
    ragCompareInput.value = '';

    ragCompareResult.hidden = false;
    ragCompareResult.innerHTML = `<div class="rag-compare-loading">Comparing strategies for ${escHtml(file.name)}…</div>`;

    try {
        const text = await file.text();
        const res = await fetch('/rag/compare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, source: file.name }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        renderCompareResult(file.name, data);
    } catch (err) {
        ragCompareResult.innerHTML = `<div class="rag-compare-error">✗ ${escHtml(err.message)}</div>`;
    }
});

function renderCompareResult(filename, data) {
    const { total_chars, fixed, structural, verdict } = data;

    function strategyHtml(label, s, isWinner) {
        const winnerMark = isWinner ? ' <span class="rag-compare-winner">✓ recommended</span>' : '';
        const previewHtml = (s.preview || []).map(p =>
            `<div class="rag-compare-preview-item"><b>${escHtml(p.section)}</b>: ${escHtml(p.text)}</div>`
        ).join('');
        return `
        <div class="rag-compare-col${isWinner ? ' rag-compare-col-winner' : ''}">
            <div class="rag-compare-col-title">${label}${winnerMark}</div>
            <div class="rag-compare-stats">
                <span><b>chunks:</b> ${s.count}</span>
                <span><b>avg:</b> ${s.avg_len} chars</span>
                <span><b>min:</b> ${s.min_len}</span>
                <span><b>max:</b> ${s.max_len}</span>
            </div>
            <div class="rag-compare-sections"><b>sections:</b> ${s.sections.slice(0, 6).map(escHtml).join(', ')}${s.sections.length > 6 ? '…' : ''}</div>
            <div class="rag-compare-previews">${previewHtml}</div>
        </div>`;
    }

    ragCompareResult.innerHTML = `
        <div class="rag-compare-header">
            <span class="rag-compare-title">Chunking comparison — ${escHtml(filename)}</span>
            <span class="rag-compare-chars">${total_chars.toLocaleString()} chars</span>
            <button class="rag-compare-close" id="rag-compare-close-btn">×</button>
        </div>
        <div class="rag-compare-cols">
            ${strategyHtml('Fixed-size', fixed, verdict === 'fixed')}
            ${strategyHtml('Structural', structural, verdict === 'structural')}
        </div>`;

    ragCompareResult.hidden = false;
    document.getElementById('rag-compare-close-btn').addEventListener('click', () => {
        ragCompareResult.hidden = true;
    });
}

loadRagDocuments();

// ── RAG Query Comparison ──────────────────────────────────────────────────────

const ragQueryInput  = document.getElementById('rag-query-input');
const ragQueryBtn    = document.getElementById('rag-query-btn');
const ragQueryResult = document.getElementById('rag-query-result');

async function runRagQueryCompare() {
    const question = ragQueryInput.value.trim();
    if (!question) return;

    ragQueryBtn.disabled = true;
    ragQueryBtn.textContent = '…';
    ragQueryResult.hidden = false;
    ragQueryResult.innerHTML = '<div class="rag-compare-loading">Asking LLM with and without RAG context…</div>';

    try {
        const res = await fetch('/rag/query-compare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, user_id: currentUserId, top_k: 5 }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        renderRagQueryCompare(data);
    } catch (err) {
        ragQueryResult.innerHTML = `<div class="rag-compare-error">✗ ${escHtml(err.message)}</div>`;
    } finally {
        ragQueryBtn.disabled = false;
        ragQueryBtn.textContent = 'Ask';
    }
}

function renderRagQueryCompare(data) {
    const { question, without_rag, with_rag, rag_available, elapsed_ms } = data;

    const chunksHtml = (with_rag.chunks || []).map((c, i) =>
        `<div class="rag-qc-chunk">
            <span class="rag-qc-chunk-idx">#${i + 1}</span>
            <span class="rag-qc-chunk-meta">${escHtml(c.source || '')}${c.section ? ' / ' + escHtml(c.section) : ''}</span>
            <span class="rag-qc-chunk-score">score: ${c.score}</span>
            <div class="rag-qc-chunk-text">${escHtml(c.text)}</div>
        </div>`
    ).join('');

    const ragBadge = rag_available
        ? `<span class="rag-qc-badge rag-qc-badge-on">${with_rag.chunks_used} chunk${with_rag.chunks_used !== 1 ? 's' : ''} used</span>`
        : `<span class="rag-qc-badge rag-qc-badge-off">no docs indexed</span>`;

    ragQueryResult.innerHTML = `
        <div class="rag-qc-header">
            <span class="rag-qc-question">${escHtml(question)}</span>
            <span class="rag-qc-elapsed">${elapsed_ms} ms</span>
            <button class="rag-compare-close" id="rag-qc-close-btn">×</button>
        </div>
        <div class="rag-qc-cols">
            <div class="rag-qc-col">
                <div class="rag-qc-col-title">Without RAG</div>
                <div class="rag-qc-answer">${escHtml(without_rag.answer)}</div>
                <div class="rag-qc-tokens">tokens: ${without_rag.usage.total_tokens || 0}</div>
            </div>
            <div class="rag-qc-col rag-qc-col-rag">
                <div class="rag-qc-col-title">With RAG ${ragBadge}</div>
                <div class="rag-qc-answer">${escHtml(with_rag.answer)}</div>
                <div class="rag-qc-tokens">tokens: ${with_rag.usage.total_tokens || 0}</div>
                ${rag_available ? `<details class="rag-qc-chunks-details"><summary>Retrieved chunks (${with_rag.chunks_used})</summary>${chunksHtml}</details>` : ''}
            </div>
        </div>`;

    ragQueryResult.hidden = false;
    document.getElementById('rag-qc-close-btn').addEventListener('click', () => {
        ragQueryResult.hidden = true;
    });
}

ragQueryBtn.addEventListener('click', runRagQueryCompare);
ragQueryInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runRagQueryCompare(); }
});