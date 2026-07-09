// ── State ───────────────────────────────────────────────────────────────────
let currentUserId = 'default';
let currentModelId = '';

// ── Utilities ────────────────────────────────────────────────────────────────
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Main tab switching ───────────────────────────────────────────────────────
document.querySelectorAll('.main-nav-tab').forEach(btn => {
    btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        document.querySelectorAll('.main-nav-tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.main-tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`tab-${tab}`).classList.add('active');
        if (tab === 'rag') loadRagDocuments();
        if (tab === 'local') {
            if (!localModelsLoaded) {
                loadLocalModels();
            }
            if (!localHistoryLoaded) {
                localHistoryLoaded = true;
                loadLocalHistory();
            }
            loadLocalParams();
            loadLocalPromptTemplate();
            loadTemplateDefinitions();
            if (currentLocalModelId) {
                loadLocalModelDetail(currentLocalModelId);
            }
        }
        if (tab === 'remote') {
            if (!remoteChecked) {
                remoteChecked = true;
                checkRemoteHealth();
            }
            loadRemoteHistory();
        }
        if (tab === 'support') {
            loadSupportUsers();
            loadSupportStatus();
        }
        if (tab === 'file') {
            loadFileStatus();
        }
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

// ── Model selector ──────────────────────────────────────────────────────────
const modelSelect      = document.getElementById('model-select');


// ── Project bar elements ────────────────────────────────────────────────────
const projectBar       = document.getElementById('project-bar');
const projectPathInput = document.getElementById('project-path-input');
const projectSwitchBtn = document.getElementById('project-switch-btn');
const projectBranch    = document.getElementById('project-branch');
const projectChunks    = document.getElementById('project-chunks');
const projectBrowseBtn = document.getElementById('project-browse-btn');
const projectsSidebarList = document.getElementById('projects-sidebar-list');

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

// ── Users panel elements ───────────────────────────────────────────────────
const usersPanel       = document.getElementById('users-panel');
const usersList        = document.getElementById('users-list');
const usersAddBtn      = document.getElementById('users-add-btn');
const usersAddRow      = document.getElementById('users-add-row');
const usersAddInput    = document.getElementById('users-add-input');
const usersAddConfirm  = document.getElementById('users-add-confirm');
const usersAddCancel   = document.getElementById('users-add-cancel');
const usersPanelToggle = document.getElementById('users-panel-toggle');

let currentLtCategory = 'profile';
const WARNING_THRESHOLD = 0.8;

// ── Code Review elements ────────────────────────────────────────────────────────
let reviewMode = 'local';
const reviewModeTabs       = document.querySelectorAll('.review-mode-tab');
const reviewModePanels = {
    local:  document.getElementById('review-mode-local'),
    manual: document.getElementById('review-mode-manual'),
};
const reviewRunLocalBtn    = document.getElementById('review-run-local-btn');
const reviewRunManualBtn   = document.getElementById('review-run-manual-btn');
const reviewBaseBranch     = document.getElementById('review-base-branch');
const reviewPrTitle        = document.getElementById('review-pr-title');
const reviewPrDesc         = document.getElementById('review-pr-desc');
const reviewDiffInput      = document.getElementById('review-diff-input');
const reviewChangedFiles   = document.getElementById('review-changed-files');
const reviewResult         = document.getElementById('review-result');
const reviewLoading        = document.getElementById('review-loading');
const reviewLoadingText    = document.getElementById('review-loading-text');
const reviewError          = document.getElementById('review-error');
const reviewOverall        = document.getElementById('review-overall');
const reviewTotalCount     = document.getElementById('review-total-count');
const reviewResultMeta     = document.getElementById('review-result-meta');
const reviewStatusText     = document.getElementById('review-status-text');
const reviewResultClose    = document.getElementById('review-result-close');
const reviewRagDetails     = document.getElementById('review-rag-details');
const reviewRagSources     = document.getElementById('review-rag-sources');

// ── Message history (Up/Down arrow navigation) ────────────────────────────────
const MAX_MESSAGE_HISTORY = 10;
const MH_STORAGE_KEY = 'chat_message_history';

/**
 * Factory: creates input history navigation for a chat textarea.
 *
 * Sets up keydown listeners for Enter (submit), ArrowUp/ArrowDown (history)
 * on the given input element. Returns { push, clear } to manage history.
 *
 * If storageKey is provided, history is persisted to localStorage.
 */
function createInputHistory({ input, form, clearBtn, storageKey, maxHistory = MAX_MESSAGE_HISTORY }) {
    let history = storageKey ? _load(storageKey) : [];
    let cursor = -1;
    let draft = '';

    function _load(key) {
        try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : []; }
        catch { return []; }
    }
    function _save() {
        if (!storageKey) return;
        try { localStorage.setItem(storageKey, JSON.stringify(history)); }
        catch { /* quota exceeded */ }
    }

    function push(text) {
        if (history[0] !== text) {
            history.unshift(text);
            if (history.length > maxHistory) history.pop();
            _save();
        }
        cursor = -1;
        draft = '';
    }

    function clear() {
        history = storageKey ? _load(storageKey) : [];
        if (storageKey) { history.length = 0; _save(); }
        else { history = []; }
        cursor = -1;
        draft = '';
    }

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            form.dispatchEvent(new Event('submit'));
            return;
        }

        if (e.key === 'ArrowUp' && history.length > 0) {
            e.preventDefault();
            if (cursor === -1) {
                draft = input.value;
                cursor = 0;
            } else if (cursor < history.length - 1) {
                cursor++;
            }
            input.value = history[cursor];
            input.setSelectionRange(input.value.length, input.value.length);
            input.dispatchEvent(new Event('input'));
        }

        if (e.key === 'ArrowDown') {
            if (cursor > 0) {
                e.preventDefault();
                cursor--;
                input.value = history[cursor];
                input.setSelectionRange(input.value.length, input.value.length);
                input.dispatchEvent(new Event('input'));
            } else if (cursor === 0) {
                e.preventDefault();
                cursor = -1;
                input.value = draft;
                draft = '';
                input.dispatchEvent(new Event('input'));
            }
        }
    });

    if (clearBtn) {
        clearBtn.addEventListener('click', clear);
    }

    return { push, clear };
}

// ── Chat tab history (persisted to localStorage) ─────────────────────────────
const chatHistory = createInputHistory({
    input: document.getElementById('input'),
    form: document.getElementById('chat-form'),
    storageKey: MH_STORAGE_KEY,
});

// ── Project switching ────────────────────────────────────────────────────────

async function loadProjectInfo() {
    try {
        const res = await fetch('/project');
        if (!res.ok) return;
        const info = await res.json();
        projectPathInput.value = info.project_root || '';
        projectBranch.textContent = info.git_branch || '—';
        const count = info.rag_doc_count || 0;
        projectChunks.textContent = count ? `${count} chunks indexed` : '';
    } catch (_) {}
}

function setProjectLoading(loading) {
    const progressWrap = document.getElementById('project-progress-wrap');
    const progressFill = document.getElementById('project-progress-fill');
    const progressLabel = document.getElementById('project-progress-label');

    if (loading) {
        projectBar.classList.add('project-loading');
        projectSwitchBtn.disabled = true;
        projectSwitchBtn.textContent = '⏳';
        projectBrowseBtn.disabled = true;
        projectPathInput.disabled = true;
        projectsSidebarList.style.pointerEvents = 'none';
        projectsSidebarList.style.opacity = '0.5';
        if (progressWrap) progressWrap.hidden = false;
        if (progressFill) progressFill.style.width = '0%';
        if (progressLabel) progressLabel.textContent = 'Connecting...';
    } else {
        projectBar.classList.remove('project-loading');
        projectSwitchBtn.disabled = false;
        projectSwitchBtn.textContent = 'Switch';
        projectBrowseBtn.disabled = false;
        projectPathInput.disabled = false;
        projectsSidebarList.style.pointerEvents = '';
        projectsSidebarList.style.opacity = '';
        if (progressWrap) progressWrap.hidden = true;
    }
}

function setProjectProgress(current, total, message) {
    const fill = document.getElementById('project-progress-fill');
    const label = document.getElementById('project-progress-label');
    if (fill) fill.style.width = total > 0 ? `${Math.round((current / total) * 100)}%` : '0%';
    if (label) label.textContent = message || '';
}

async function switchProject() {
    const newPath = projectPathInput.value.trim();
    if (!newPath) return;

    setProjectLoading(true);
    setProjectProgress(0, 1, 'Validating...');

    try {
        const res = await fetch('/project/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_root: newPath }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let result = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split('\n\n');
            buffer = parts.pop();

            for (const part of parts) {
                const line = part.trim();
                if (!line.startsWith('data: ')) continue;
                let event;
                try { event = JSON.parse(line.slice(6)); } catch { continue; }

                if (event.type === 'progress') {
                    setProjectProgress(event.current, event.total, event.message);
                } else if (event.type === 'done') {
                    result = event;
                } else if (event.type === 'error') {
                    throw new Error(event.message || 'Switch failed');
                }
            }
        }

        if (result) {
            projectBranch.textContent = result.git_branch || '?';
            const skipped = result.rag_skipped ? ' (reuse)' : '';
            projectChunks.textContent = result.rag_chunks
                ? `${result.rag_chunks} chunks indexed${skipped}`
                : '';
            loadRecentProjects();
            projectBar.style.background = '#ecfdf5';
            setTimeout(() => { projectBar.style.background = ''; }, 1500);
        }
    } catch (err) {
        alert('Failed to switch project: ' + err.message);
        projectBar.style.background = '#fef2f2';
        setTimeout(() => { projectBar.style.background = ''; }, 2000);
    } finally {
        setProjectLoading(false);
    }
}

// ── Native folder picker ──────────────────────────────────────────────────────

async function pickFolder() {
    projectBrowseBtn.disabled = true;
    projectBrowseBtn.textContent = '…';
    try {
        const res = await fetch('/pick-folder', { method: 'POST' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            alert('Folder picker failed: ' + (err.detail || 'HTTP ' + res.status));
            return;
        }
        const data = await res.json();
        if (data.path) {
            projectPathInput.value = data.path;
            switchProject();
        }
        // cancelled → do nothing
    } catch (_) {
        alert('Folder picker unavailable');
    } finally {
        projectBrowseBtn.disabled = false;
        projectBrowseBtn.textContent = '📂';
    }
}

// ── Recent projects sidebar ───────────────────────────────────────────────────

async function loadRecentProjects() {
    try {
        const res = await fetch('/projects/recent');
        if (!res.ok) return;
        const { projects } = await res.json();
        renderRecentProjects(projects || []);
    } catch (_) {}
}

function renderRecentProjects(projects) {
    if (!projects || projects.length === 0) {
        projectsSidebarList.innerHTML = '<div class="project-sidebar-empty">No recent projects</div>';
        return;
    }
    const currentPath = projectPathInput.value.trim();
    projectsSidebarList.innerHTML = projects.map(p => {
        const active = p.path === currentPath ? ' active' : '';
        return `<div class="project-sidebar-item${active}" data-path="${p.path}" title="${p.path}">
            <span class="ps-name">📁 ${p.name || p.path.split('/').pop()}</span>
            <span class="ps-branch">${p.branch || ''}</span>
            <span class="ps-remove" data-remove="${p.path}">✕</span>
        </div>`;
    }).join('');

    // Click to switch
    projectsSidebarList.querySelectorAll('.project-sidebar-item').forEach(el => {
        el.addEventListener('click', (e) => {
            if (e.target.classList.contains('ps-remove')) return;
            const path = el.dataset.path;
            projectPathInput.value = path;
            switchProject();
        });
    });

    // Click to remove
    projectsSidebarList.querySelectorAll('.ps-remove').forEach(el => {
        el.addEventListener('click', async (e) => {
            e.stopPropagation();
            const path = el.dataset.remove;
            const res = await fetch(`/projects/recent?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
            const data = await res.json().catch(() => ({}));
            const deleted = data.rag_deleted || 0;
            if (deleted > 0) {
                projectChunks.textContent = `🗑️ ${deleted} RAG chunks deleted`;
                setTimeout(() => loadProjectInfo(), 1500);
            }
            loadRecentProjects();
        });
    });
}

// ── User management ─────────────────────────────────────────────────────────

async function loadUsers() {
    try {
        const res = await fetch('/users');
        if (!res.ok) return;
        const { users } = await res.json();

        usersList.innerHTML = '';
        const all = users.includes('default') ? users : ['default', ...users];

        // Ensure current user exists in list
        const finalList = all.includes(currentUserId) ? all : [...all, currentUserId];

        finalList.forEach(uid => {
            const item = document.createElement('div');
            item.className = 'users-list-item';
            if (uid === currentUserId) item.classList.add('active');
            item.dataset.uid = uid;

            const nameSpan = document.createElement('span');
            nameSpan.className = 'users-list-name';
            nameSpan.textContent = uid;

            const delBtn = document.createElement('button');
            delBtn.className = 'users-list-del';
            delBtn.title = 'Delete user';
            delBtn.textContent = '×';
            if (uid === 'default') delBtn.hidden = true;

            item.appendChild(nameSpan);
            item.appendChild(delBtn);

            // Click user to switch
            item.addEventListener('click', (e) => {
                if (e.target === delBtn) return;
                if (uid !== currentUserId) switchUser(uid);
            });

            // Delete user
            delBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (!confirm(`Delete user "${uid}" and all their data?`)) return;
                await fetch(`/users/${encodeURIComponent(uid)}`, { method: 'DELETE' });
                if (uid === currentUserId) {
                    currentUserId = 'default';
                    await loadUsers();
                    await switchUser('default');
                } else {
                    await loadUsers();
                }
            });

            usersList.appendChild(item);
        });
    } catch (_) {}
}

async function switchUser(uid) {
    currentUserId = uid;
    messagesEl.innerHTML = '<div class="empty-state">Start a conversation...</div>';
    await Promise.all([loadModels(), loadTokenStats(), loadMemory(), loadShortTerm()]);
    // Update active state in users list
    usersList.querySelectorAll('.users-list-item').forEach(el => {
        el.classList.toggle('active', el.dataset.uid === uid);
    });
}

// ── Users panel event handlers ──────────────────────────────────────────────

// Collapse/expand toggle
usersPanelToggle.addEventListener('click', () => {
    usersPanel.classList.toggle('collapsed');
});

// Show add user form
usersAddBtn.addEventListener('click', () => {
    usersAddRow.hidden = false;
    usersAddInput.focus();
});

// Cancel add
usersAddCancel.addEventListener('click', () => {
    usersAddRow.hidden = true;
    usersAddInput.value = '';
});

// Create user
async function createUser() {
    const uid = usersAddInput.value.trim().replace(/\s+/g, '_');
    if (!uid) return;
    usersAddRow.hidden = true;
    usersAddInput.value = '';
    currentUserId = uid;
    await loadUsers();
    await switchUser(uid);
}

usersAddConfirm.addEventListener('click', createUser);
usersAddInput.addEventListener('keydown', e => { if (e.key === 'Enter') createUser(); });

// ── Model selection ────────────────────────────────────────────────────────

async function loadModels() {
    try {
        const res = await fetch('/models');
        if (!res.ok) return;
        const { models, default: defaultModel } = await res.json();

        modelSelect.innerHTML = '';
        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.label + (m.available ? '' : ' (no key)');
            opt.disabled = !m.available;
            if (m.id === currentModelId) opt.selected = true;
            modelSelect.appendChild(opt);
        });

        // Load current model for this user
        const modelRes = await fetch(`/model?user_id=${encodeURIComponent(currentUserId)}`);
        if (modelRes.ok) {
            const { model } = await modelRes.json();
            currentModelId = model;
            if (modelSelect.querySelector(`option[value="${model}"]`)) {
                modelSelect.value = model;
            }
        }
    } catch (_) {}
}

modelSelect.addEventListener('change', async () => {
    const modelId = modelSelect.value;
    try {
        const res = await fetch(`/model?user_id=${encodeURIComponent(currentUserId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: modelId }),
        });
        if (res.ok) {
            currentModelId = modelId;
        }
    } catch (_) {}
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

function appendRagSources(msgEl, sources, noContext, scrollEl) {
    const scroll = scrollEl || messagesEl;
    // Show "no context found" note
    if (noContext) {
        const el = document.createElement('div');
        el.className = 'rag-sources';
        el.innerHTML = '<div class="rag-sources-header">📚 RAG — no relevant documents found</div>' +
            '<div class="rag-sources-none">All retrieved chunks were below the relevance threshold. ' +
            'Try rephrasing your question.</div>';
        msgEl.appendChild(el);
        scroll.scrollTop = scroll.scrollHeight;
        return;
    }

    if (!sources || sources.length === 0) return;

    const container = document.createElement('div');
    container.className = 'rag-sources';

    const headerLabel = sources.length === 1 ? '1 source' : `${sources.length} sources`;
    const header = document.createElement('div');
    header.className = 'rag-sources-header';
    header.textContent = `📚 ${headerLabel} ▸`;

    const list = document.createElement('div');
    list.className = 'rag-sources-list';
    list.style.display = 'none';  // collapsed by default (inline style beats CSS)

    sources.forEach((r, i) => {
        const item = document.createElement('div');
        item.className = 'rag-source-item';

        // Location: source > section
        const locParts = [];
        if (r.source) locParts.push(r.source);
        if (r.title && r.title !== r.source) locParts.push(r.title);
        if (r.section && !locParts.includes(r.section)) locParts.push(r.section);
        const loc = locParts.join(' › ') || '(unknown)';

        const scorePct = Math.round((r.score || 0) * 100);
        const scoreClass = scorePct >= 70 ? 'rag-score-high' : (scorePct >= 40 ? 'rag-score-mid' : 'rag-score-low');

        // Preview text
        const preview = (r.text || '').substring(0, 250).replace(/\n/g, ' ');
        const ellipsis = (r.text || '').length > 250 ? '…' : '';

        item.innerHTML =
            `<span class="rag-source-loc">${loc}</span>` +
            `<span class="rag-source-score ${scoreClass}">${scorePct}%</span>` +
            `<span class="rag-source-preview">${preview}${ellipsis}</span>`;

        list.appendChild(item);
    });

    // Toggle expand/collapse on header click
    header.style.cursor = 'pointer';
    header.addEventListener('click', () => {
        const collapsed = list.style.display === 'none';
        list.style.display = collapsed ? '' : 'none';
        header.textContent = `📚 ${headerLabel} ${collapsed ? '▾' : '▸'}`;
    });

    container.appendChild(header);
    container.appendChild(list);
    msgEl.appendChild(container);
    scroll.scrollTop = scroll.scrollHeight;
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
        appendRagSources(msgEl, data.rag_sources || [], data.rag_no_context);
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

    chatHistory.push(text);

    input.value = '';
    input.style.height = 'auto';
    sendMessage(text);
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

// ── Local Chat (Ollama + llama.cpp) ──────────────────────────────────────────

const localMessagesEl   = document.getElementById('local-messages');
const localForm         = document.getElementById('local-chat-form');
const localInput        = document.getElementById('local-input');
const localSendBtn      = document.getElementById('local-send-btn');
const localClearBtn     = document.getElementById('local-clear-btn');
const localInputHistory = createInputHistory({
    input: localInput,
    form: localForm,
    clearBtn: localClearBtn,
});
const localModelSelect  = document.getElementById('local-model-select');

let localHistoryLoaded  = false;
let localModelsLoaded   = false;
let currentLocalModelId = '';

// ── Local parameters ────────────────────────────────────────────────────
const paramTemperature    = document.getElementById('param-temperature');
const paramTemperatureNum = document.getElementById('param-temperature-num');
const paramMaxTokens      = document.getElementById('param-max-tokens');
const paramMaxTokensNum   = document.getElementById('param-max-tokens-num');
const paramTopP           = document.getElementById('param-top-p');
const paramTopPNum    = document.getElementById('param-top-p-num');
const paramTopK           = document.getElementById('param-top-k');
const paramTopKNum    = document.getElementById('param-top-k-num');
const paramRepeatPenalty  = document.getElementById('param-repeat-penalty');
const paramRepeatPenaltyNum = document.getElementById('param-repeat-penalty-num');
const paramNumCtx         = document.getElementById('param-num-ctx');
const paramNumCtxNum  = document.getElementById('param-num-ctx-num');
const paramRowTopK        = document.getElementById('param-row-top-k');
const paramRowNumCtx      = document.getElementById('param-row-num-ctx');
const paramNumCtxNote = document.getElementById('param-num-ctx-note');
const paramStatus     = document.getElementById('param-status');

// ── Local prompt template ───────────────────────────────────────────────
const localTemplateSelect = document.getElementById('local-template-select');
const localTemplateDesc   = document.getElementById('local-template-desc');
const localSyspromptInput = document.getElementById('local-sysprompt-input');
const localSyspromptSaveBtn = document.getElementById('local-sysprompt-save-btn');
const localSyspromptStatus  = document.getElementById('local-sysprompt-status');

// ── Quantization badge ──────────────────────────────────────────────────
const localQuantBadge = document.getElementById('local-quant-badge');

// ── Slider ↔ Number syncing ──────────────────────────────────────────────
function syncRangeAndNumber(rangeEl, numEl) {
    rangeEl.addEventListener('input', () => { numEl.value = rangeEl.value; });
    numEl.addEventListener('input', () => {
        let v = parseFloat(numEl.value);
        const min = parseFloat(numEl.min);
        const max = parseFloat(numEl.max);
        if (!isNaN(v) && v >= min && v <= max) rangeEl.value = v;
    });
}

// Wire each pair
syncRangeAndNumber(paramTemperature, paramTemperatureNum);
syncRangeAndNumber(paramMaxTokens, paramMaxTokensNum);
syncRangeAndNumber(paramTopP, paramTopPNum);
syncRangeAndNumber(paramTopK, paramTopKNum);
syncRangeAndNumber(paramRepeatPenalty, paramRepeatPenaltyNum);
syncRangeAndNumber(paramNumCtx, paramNumCtxNum);

// ── Load / Save params ──────────────────────────────────────────────────
async function loadLocalParams() {
    try {
        const res = await fetch(`/chat/local/params?user_id=${encodeURIComponent(currentUserId)}`);
        if (!res.ok) return;
        const { params } = await res.json();
        paramTemperature.value = paramTemperatureNum.value = params.temperature ?? 0.8;
        paramMaxTokens.value = paramMaxTokensNum.value = params.max_tokens ?? 2048;
        paramTopP.value = paramTopPNum.value = params.top_p ?? 0.9;
        paramTopK.value = paramTopKNum.value = params.top_k ?? 40;
        paramRepeatPenalty.value = paramRepeatPenaltyNum.value = params.repeat_penalty ?? 1.1;
        paramNumCtx.value = paramNumCtxNum.value = params.num_ctx ?? 4096;
    } catch (_) {}
}

let paramSaveTimer = null;

function scheduleParamSave() {
    if (paramSaveTimer) clearTimeout(paramSaveTimer);
    paramSaveTimer = setTimeout(saveLocalParams, 500);
}

async function saveLocalParams() {
    const body = {
        temperature: parseFloat(paramTemperature.value),
        max_tokens: parseInt(paramMaxTokens.value),
        top_p: parseFloat(paramTopP.value),
        top_k: parseInt(paramTopK.value),
        repeat_penalty: parseFloat(paramRepeatPenalty.value),
        num_ctx: parseInt(paramNumCtx.value),
    };
    try {
        const res = await fetch(`/chat/local/params?user_id=${encodeURIComponent(currentUserId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (res.ok) {
            paramStatus.textContent = 'Saved';
            setTimeout(() => { paramStatus.textContent = ''; }, 1500);
        }
    } catch (_) {}
}

// Wire each control to debounced save
[paramTemperature, paramTemperatureNum,
 paramMaxTokens, paramMaxTokensNum,
 paramTopP, paramTopPNum,
 paramTopK, paramTopKNum,
 paramRepeatPenalty, paramRepeatPenaltyNum,
 paramNumCtx, paramNumCtxNum
].forEach(el => el.addEventListener('input', scheduleParamSave));

// ── Prompt template ─────────────────────────────────────────────────────
async function loadLocalPromptTemplate() {
    try {
        const res = await fetch(`/chat/local/prompt-template?user_id=${encodeURIComponent(currentUserId)}`);
        if (!res.ok) return;
        const { template_key, prompt, custom_prompt } = await res.json();
        localTemplateSelect.value = template_key;
        localSyspromptInput.value = prompt || custom_prompt || '';
        updateTemplateDescription(template_key);
    } catch (_) {}
}

async function loadTemplateDefinitions() {
    try {
        const res = await fetch('/chat/local/templates');
        if (!res.ok) return;
        const { templates } = await res.json();
        window._localTemplateDefs = templates;
        updateTemplateDescription(localTemplateSelect.value);
    } catch (_) {}
}

function updateTemplateDescription(key) {
    const defs = window._localTemplateDefs || {};
    const t = defs[key];
    localTemplateDesc.textContent = t ? t.description : '';
}

localTemplateSelect.addEventListener('change', async () => {
    const key = localTemplateSelect.value;
    const defs = window._localTemplateDefs || {};
    const t = defs[key];
    if (key === 'custom') {
        // Keep existing text — user writes their own
    } else if (t) {
        localSyspromptInput.value = t.prompt;
    }
    updateTemplateDescription(key);
    await saveLocalTemplate(key);
});

async function saveLocalTemplate(templateKey) {
    const key = templateKey || localTemplateSelect.value;
    const customPrompt = key === 'custom' ? localSyspromptInput.value : '';
    try {
        const res = await fetch(`/chat/local/prompt-template?user_id=${encodeURIComponent(currentUserId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ template_key: key, custom_prompt: customPrompt }),
        });
        if (res.ok) {
            localSyspromptStatus.textContent = 'Saved';
            setTimeout(() => { localSyspromptStatus.textContent = ''; }, 2000);
        }
    } catch (_) {}
}

localSyspromptSaveBtn.addEventListener('click', () => saveLocalTemplate(null));

// ── Model detail / Quantization ─────────────────────────────────────────
async function loadLocalModelDetail(modelId) {
    if (!modelId) { localQuantBadge.hidden = true; return; }
    try {
        const res = await fetch(`/chat/local/model-detail?model_id=${encodeURIComponent(modelId)}`);
        if (!res.ok) { localQuantBadge.hidden = true; return; }
        const data = await res.json();
        if (data.quantization) {
            localQuantBadge.textContent = data.quantization;
            localQuantBadge.hidden = false;
            const q = data.quantization.toLowerCase();
            localQuantBadge.className = 'quant-badge';
            if (q.startsWith('q4') || q.startsWith('q3') || q.startsWith('q2')) {
                localQuantBadge.classList.add('quant-low');
            } else if (q.startsWith('q6') || q.startsWith('q8') || q.startsWith('f16') || q.startsWith('fp16') || q.startsWith('bf16')) {
                localQuantBadge.classList.add('quant-high');
            } else {
                localQuantBadge.classList.add('quant-mid');
            }
        } else {
            localQuantBadge.hidden = true;
        }

        // Provider-specific UI adjustments
        if (data.provider === 'llamacpp') {
            paramRowTopK.style.display = 'none';
            paramNumCtx.disabled = true;
            paramNumCtxNum.disabled = true;
            paramNumCtxNote.textContent = '(requires server restart)';
        } else {
            paramRowTopK.style.display = '';
            paramNumCtx.disabled = false;
            paramNumCtxNum.disabled = false;
            paramNumCtxNote.textContent = '';
        }
    } catch (_) { localQuantBadge.hidden = true; }
}

const LOCAL_EMPTY_STATE = 'Start a conversation with a local model...';

async function loadLocalModels() {
    try {
        const res = await fetch('/chat/local/models');
        if (!res.ok) return;
        const { models, default: defaultModel } = await res.json();

        localModelSelect.innerHTML = '';
        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.label + (m.available ? '' : ' (offline)');
            opt.disabled = !m.available;
            if (m.id === currentLocalModelId) opt.selected = true;
            localModelSelect.appendChild(opt);
        });

        // Load current model for this user
        const modelRes = await fetch(`/chat/local/model?user_id=${encodeURIComponent(currentUserId)}`);
        if (modelRes.ok) {
            const { model } = await modelRes.json();
            currentLocalModelId = model;
            if (localModelSelect.querySelector(`option[value="${model}"]`)) {
                localModelSelect.value = model;
            }
        } else {
            currentLocalModelId = defaultModel;
        }

        localModelsLoaded = true;
        loadLocalModelDetail(currentLocalModelId);
    } catch (_) {}
}

localModelSelect.addEventListener('change', async () => {
    const modelId = localModelSelect.value;
    try {
        const res = await fetch(`/chat/local/model?user_id=${encodeURIComponent(currentUserId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: modelId }),
        });
        if (res.ok) {
            currentLocalModelId = modelId;
            loadLocalModelDetail(modelId);
        }
    } catch (_) {}
});

async function loadLocalHistory() {
    try {
        const res = await fetch(`/chat/local/history?user_id=${encodeURIComponent(currentUserId)}`);
        if (!res.ok) return;
        const { history } = await res.json();
        localMessagesEl.innerHTML = '';
        if (history.length === 0) {
            localMessagesEl.innerHTML = `<div class="empty-state">${LOCAL_EMPTY_STATE}</div>`;
        } else {
            history.forEach(m => {
                appendLocalMessage(m.role, m.content);
            });
        }
    } catch (_) {}
}

function appendLocalMessage(role, text) {
    const emptyState = localMessagesEl.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    const el = document.createElement('div');
    el.className = `message ${role}`;
    el.textContent = text;
    localMessagesEl.appendChild(el);
    localMessagesEl.scrollTop = localMessagesEl.scrollHeight;
    return el;
}

function setLocalLoading(loading) {
    localSendBtn.disabled = loading;
    localInput.disabled   = loading;
    localModelSelect.disabled = loading;
}

async function sendLocalMessage(text) {
    appendLocalMessage('user', text);
    const thinking = appendLocalMessage('thinking', 'Thinking...');
    setLocalLoading(true);

    try {
        const res = await fetch('/chat/local', {
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
        const msgEl = appendLocalMessage('assistant', data.response);
        appendRagSources(msgEl, data.rag_sources || [], data.rag_no_context, localMessagesEl);
        if (data.model_label || data.elapsed_ms) {
            const badge = document.createElement('span');
            badge.className = 'local-model-badge';
            const parts = [];
            if (data.model_label) parts.push(data.model_label);
            if (data.elapsed_ms != null) parts.push(`${(data.elapsed_ms / 1000).toFixed(2)}s`);
            badge.textContent = parts.join(' · ');
            msgEl.appendChild(badge);
        }
    } catch (err) {
        thinking.remove();
        appendLocalMessage('error', `Error: ${err.message}`);
    } finally {
        setLocalLoading(false);
        localInput.focus();
    }
}

localForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = localInput.value.trim();
    if (!text) return;

    localInputHistory.push(text);

    localInput.value = '';
    localInput.style.height = 'auto';
    sendLocalMessage(text);
});

localInput.addEventListener('input', () => {
    localInput.style.height = 'auto';
    localInput.style.height = `${localInput.scrollHeight}px`;
});

localClearBtn.addEventListener('click', async () => {
    await fetch(`/chat/local/history?user_id=${encodeURIComponent(currentUserId)}`, { method: 'DELETE' });
    localMessagesEl.innerHTML = `<div class="empty-state">${LOCAL_EMPTY_STATE}</div>`;
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

loadModels();
loadUsers();
loadMemory();
loadShortTerm();
loadProjectInfo();
loadRecentProjects();
refreshMemBtn.addEventListener('click', () => { loadMemory(); loadShortTerm(); });
projectSwitchBtn.addEventListener('click', switchProject);
projectBrowseBtn.addEventListener('click', pickFolder);
projectPathInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') switchProject();
});

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
const ragFormatSelect    = document.getElementById('rag-format-select');
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
    const format = ragFormatSelect.value || 'auto';

    setRagUploading(true);
    setRagProgress(0, 1, `Reading ${file.name}…`);

    try {
        const text = await file.text();
        setRagProgress(0, 0, `Connecting…`);

        const res = await fetch('/rag/documents/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, source: file.name, strategy, format }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let finalChunks = 0;
        let finalFormat = '';

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
                    finalFormat = event.detected_format || '';
                    setRagProgress(event.chunks, event.chunks, 'done');
                } else if (event.type === 'error') {
                    throw new Error(event.message);
                }
            }
        }

        setRagUploading(false);
        const fmtLabel = finalFormat && finalFormat !== 'text' ? `, ${finalFormat}` : '';
        setRagIdleStatus(`✓ ${file.name} (${finalChunks} chunks, ${strategy}${fmtLabel})`);
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

const ragQueryInput   = document.getElementById('rag-query-input');
const ragQueryBtn     = document.getElementById('rag-query-btn');
const ragQueryResult  = document.getElementById('rag-query-result');
const ragPreK         = document.getElementById('rag-prek');
const ragPostK        = document.getElementById('rag-postk');
const ragThreshold    = document.getElementById('rag-threshold');
const ragMmr          = document.getElementById('rag-mmr');
const ragRewriteSel   = document.getElementById('rag-rewrite-select');
const ragModeTabs     = document.querySelectorAll('.rag-mode-tab');

let ragCompareMode = 'all'; // 'simple' | 'all'

ragModeTabs.forEach(btn => {
    btn.addEventListener('click', () => {
        ragModeTabs.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        ragCompareMode = btn.dataset.mode;
    });
});

function _getExpectedAnswer(question) {
    const matched = controlQuestions.find(q => q.question === question);
    return matched ? matched.expected_answer : '';
}

async function runRagQueryCompare() {
    const question = ragQueryInput.value.trim();
    if (!question) return;

    const expectedAnswer = _getExpectedAnswer(question);

    ragQueryBtn.disabled = true;
    ragQueryBtn.textContent = '…';
    ragQueryResult.hidden = false;
    ragQueryResult.innerHTML = '<div class="rag-compare-loading">Running RAG pipeline comparison…</div>';

    try {
        if (ragCompareMode === 'simple') {
            const res = await fetch('/rag/query-compare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question, user_id: currentUserId, top_k: parseInt(ragPostK.value) || 5, expected_answer: expectedAnswer }),
            });
            if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || `HTTP ${res.status}`); }
            const data = await res.json();
            renderRagQueryCompare(data);
        } else {
            const body = {
                question,
                user_id: currentUserId,
                pre_k: parseInt(ragPreK.value) || 10,
                post_k: parseInt(ragPostK.value) || 5,
                threshold: parseFloat(ragThreshold.value) || 0.3,
                rewrite: ragRewriteSel.value || 'keywords',
                use_mmr: ragMmr.checked,
                expected_answer: expectedAnswer,
            };
            const res = await fetch('/rag/compare-all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || `HTTP ${res.status}`); }
            const data = await res.json();
            renderRagCompareAll(data);
        }
    } catch (err) {
        ragQueryResult.innerHTML = `<div class="rag-compare-error">✗ ${escHtml(err.message)}</div>`;
    } finally {
        ragQueryBtn.disabled = false;
        ragQueryBtn.textContent = 'Ask';
    }
}

// ── Simple A/B comparison (kept for backward compatibility) ────────────────

function renderRagQueryCompare(data) {
    const { question, without_rag, with_rag, rag_available, elapsed_ms, expected_answer } = data;

    const expectedBlock = expected_answer ? `
        <div class="rag-qc-expected">
            <div class="rag-qc-expected-label">Ожидаемый ответ</div>
            <div class="rag-qc-expected-text">${escHtml(expected_answer)}</div>
        </div>` : '';

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
        ${expectedBlock}
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

// ── Full 5-mode comparison ─────────────────────────────────────────────────

function renderRagCompareAll(data) {
    const { question, modes, pipeline_info, total_elapsed_ms, expected_answer } = data;

    const expectedBlock = expected_answer ? `
        <div class="rag-qc-expected">
            <div class="rag-qc-expected-label">Ожидаемый ответ</div>
            <div class="rag-qc-expected-text">${escHtml(expected_answer)}</div>
        </div>` : '';

    const MODE_LABELS = {
        'no-rag': 'No RAG',
        'rag-basic': 'RAG basic',
        'rag+rewrite': 'RAG + rewrite',
        'rag+rerank': 'RAG + rerank',
        'rag+rewrite+rerank': 'RAG + rewrite + rerank',
    };
    const MODE_CLASSES = {
        'no-rag': '',
        'rag-basic': 'rag-qc-col-rag',
        'rag+rewrite': 'rag-qc-col-rag',
        'rag+rerank': 'rag-qc-col-rag',
        'rag+rewrite+rerank': 'rag-qc-col-winner',
    };

    const modeOrder = ['no-rag', 'rag-basic', 'rag+rewrite', 'rag+rerank', 'rag+rewrite+rerank'];

    const colsHtml = modeOrder.map(mode => {
        const m = modes[mode];
        if (!m) return '';
        return `
        <div class="rag-qc-col ${MODE_CLASSES[mode]}">
            <div class="rag-qc-col-title">${MODE_LABELS[mode] || mode}</div>
            <div class="rag-qc-answer">${escHtml(m.answer)}</div>
            <div class="rag-qc-stats">
                <span class="rag-qc-tokens">tokens: ${m.usage.total_tokens || 0}</span>
                <span class="rag-qc-time">${m.elapsed_ms} ms</span>
            </div>
        </div>`;
    }).join('');

    const chunksHtml = (pipeline_info.retrieved_chunks || []).map((c, i) =>
        `<div class="rag-qc-chunk ${c.score < pipeline_info.threshold ? 'rag-qc-chunk-filtered' : ''}">
            <span class="rag-qc-chunk-idx">#${i + 1}</span>
            <span class="rag-qc-chunk-meta">${escHtml(c.source || '')}${c.section ? ' / ' + escHtml(c.section) : ''}</span>
            <span class="rag-qc-chunk-score ${c.score < pipeline_info.threshold ? 'rag-qc-score-low' : 'rag-qc-score-ok'}">score: ${c.score}</span>
            <div class="rag-qc-chunk-text">${escHtml(c.text)}</div>
        </div>`
    ).join('');

    ragQueryResult.innerHTML = `
        ${expectedBlock}
        <div class="rag-qc-header">
            <span class="rag-qc-question">${escHtml(question)}</span>
            <span class="rag-qc-elapsed">${total_elapsed_ms} ms total</span>
            <button class="rag-compare-close" id="rag-qc-close-btn">×</button>
        </div>
        <div class="rag-pipeline-info">
            <span>Pre-K: ${pipeline_info.pre_k}</span>
            <span>Post-K: ${pipeline_info.post_k}</span>
            <span>Threshold: ${pipeline_info.threshold}</span>
            <span>Rewrite: ${pipeline_info.rewrite_strategy}</span>
            <span>MMR: ${pipeline_info.use_mmr ? 'on' : 'off'}</span>
            ${pipeline_info.rewritten_query ? `<span>Rewritten: «${escHtml(pipeline_info.rewritten_query)}»</span>` : ''}
            <span>Chunks: ${pipeline_info.chunks_before_rerank} → ${pipeline_info.chunks_after_rerank}</span>
        </div>
        <div class="rag-qc-cols rag-qc-cols-all">${colsHtml}</div>
        ${pipeline_info.retrieved_chunks.length ? `<details class="rag-qc-chunks-details"><summary>Retrieved chunks (${pipeline_info.chunks_after_rerank} after rerank)</summary>${chunksHtml}</details>` : ''}
    `;

    ragQueryResult.hidden = false;
    document.getElementById('rag-qc-close-btn').addEventListener('click', () => {
        ragQueryResult.hidden = true;
    });
}

ragQueryBtn.addEventListener('click', runRagQueryCompare);
ragQueryInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runRagQueryCompare(); }
});

// ── Control Questions ──────────────────────────────────────────────────────────

const ragCtrlList     = document.getElementById('rag-ctrl-list');
const ragCtrlExpected = document.getElementById('rag-ctrl-expected');
const ragCtrlExpectedText = document.getElementById('rag-ctrl-expected-text');

let controlQuestions = [];
let selectedQuestionId = null;

async function loadControlQuestions() {
    try {
        const res = await fetch('/rag/control-questions');
        if (!res.ok) return;
        const data = await res.json();
        controlQuestions = data.questions || [];
        renderControlQuestions();
    } catch (_) {}
}

function renderControlQuestions() {
    ragCtrlList.innerHTML = '';
    if (!controlQuestions.length) {
        const el = document.createElement('div');
        el.className = 'mem-empty';
        el.textContent = '(no questions)';
        ragCtrlList.appendChild(el);
        return;
    }
    controlQuestions.forEach(q => {
        const el = document.createElement('div');
        el.className = 'rag-ctrl-item';
        if (q.id === selectedQuestionId) el.classList.add('selected');
        el.innerHTML = `<span class="rag-ctrl-item-num">${q.id}.</span>${escHtml(q.question)}`;
        el.title = q.question;
        el.addEventListener('click', () => selectControlQuestion(q));
        ragCtrlList.appendChild(el);
    });
}

function selectControlQuestion(q) {
    selectedQuestionId = q.id;
    renderControlQuestions();

    // Fill the query input
    ragQueryInput.value = q.question;

    // Show expected answer in the left panel
    ragCtrlExpected.hidden = false;
    ragCtrlExpectedText.textContent = q.expected_answer;
}

// Load control questions when switching to RAG tab
const ragTabBtn = document.querySelector('.main-nav-tab[data-tab="rag"]');
if (ragTabBtn) {
    ragTabBtn.addEventListener('click', () => {
        loadControlQuestions();
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// ── Remote LLM tab ──────────────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════════════

let remoteChecked = false;
let remoteAvailable = false;

const remoteMessages = document.getElementById('remote-messages');
const remoteForm = document.getElementById('remote-chat-form');
const remoteInput = document.getElementById('remote-input');
const remoteSendBtn = document.getElementById('remote-send-btn');
const remoteStopBtn = document.getElementById('remote-stop-btn');
const remoteClearBtn = document.getElementById('remote-clear-btn');
const remoteInputHistory = createInputHistory({
    input: remoteInput,
    form: remoteForm,
    clearBtn: remoteClearBtn,
});
let remoteAbortController = null;  // for stopping in-flight generation
const remoteStatusDot = document.getElementById('remote-status-dot');
const remoteDiagBar = document.getElementById('remote-diag-bar');
const remoteModelName = document.getElementById('remote-model-name');
const remoteModelParams = document.getElementById('remote-model-params');
const remoteModelCtx = document.getElementById('remote-model-ctx');
const remoteLatency = document.getElementById('remote-latency');

// ── Health check ──────────────────────────────────────────────────────────

async function checkRemoteHealth() {
    remoteStatusDot.className = 'remote-status-dot checking';
    remoteStatusDot.title = 'Checking server...';

    try {
        const resp = await fetch('/chat/remote/health');
        const data = await resp.json();

        remoteAvailable = data.available;

        if (data.available) {
            remoteStatusDot.className = 'remote-status-dot online';
            remoteStatusDot.title = `Server online (${data.latency_ms}ms)`;
            remoteLatency.textContent = `${data.latency_ms}ms`;
            remoteDiagBar.classList.remove('offline');

            // Show model info
            if (data.models.length > 0) {
                const m = data.models[0];
                remoteModelName.textContent = m.id || '—';
                const paramsB = (m.parameter_size / 1e9).toFixed(1);
                remoteModelParams.textContent = m.parameter_size
                    ? `${paramsB}B`
                    : '—';
                remoteModelCtx.textContent = m.context_size
                    ? m.context_size.toLocaleString()
                    : '—';
            }

            // Enable input
            remoteInput.disabled = false;
            remoteSendBtn.disabled = false;

            // Update empty state
            const emptyState = remoteMessages.querySelector('.empty-state');
            if (emptyState) {
                emptyState.textContent = 'Start a conversation with the remote model...';
            }
        } else {
            setRemoteOffline(data.error || 'Server unreachable');
        }
    } catch (e) {
        setRemoteOffline(`Health check failed: ${e.message}`);
    }
}

function setRemoteOffline(reason) {
    remoteAvailable = false;
    remoteStatusDot.className = 'remote-status-dot offline';
    remoteStatusDot.title = `Server offline: ${reason}`;
    remoteDiagBar.classList.add('offline');
    remoteInput.disabled = true;
    remoteSendBtn.disabled = true;
    remoteLatency.textContent = '—';
    remoteModelName.textContent = '—';
    remoteModelParams.textContent = '—';
    remoteModelCtx.textContent = '—';

    const emptyState = remoteMessages.querySelector('.empty-state');
    if (emptyState) {
        emptyState.innerHTML = `<span style="color:#ef4444">⚠ Server unavailable</span><br><small>${escapeHtml(reason)}</small><br><small><a href="#" onclick="remoteChecked=false;checkRemoteHealth();return false;">↻ Retry</a></small>`;
    }
}

// ── Chat ──────────────────────────────────────────────────────────────────

remoteInput.addEventListener('input', () => {
    remoteInput.style.height = 'auto';
    remoteInput.style.height = `${remoteInput.scrollHeight}px`;
});

remoteForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = remoteInput.value.trim();
    if (!text || !remoteAvailable) return;

    remoteInputHistory.push(text);

    remoteInput.value = '';
    remoteInput.style.height = 'auto';
    remoteSendBtn.style.display = 'none';
    remoteStopBtn.style.display = '';
    remoteStopBtn.disabled = false;
    remoteInput.disabled = true;

    appendRemoteMessage('user', text);
    appendRemoteMessage('thinking', '');

    const thinkingEl = remoteMessages.querySelector('.message.thinking');
    let fullText = '';

    remoteAbortController = new AbortController();
    const t0 = performance.now();

    try {
        const resp = await fetch(`/chat/remote?user_id=${encodeURIComponent(currentUserId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, user_id: currentUserId }),
            signal: remoteAbortController.signal,
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

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

                if (!event.done) {
                    // Streaming token
                    fullText += event.token;
                    if (thinkingEl) {
                        thinkingEl.innerHTML = escapeHtml(fullText).replace(/\n/g, '<br>');
                        remoteMessages.scrollTop = remoteMessages.scrollHeight;
                    }
                } else {
                    // Stream finished
                    if (thinkingEl) {
                        thinkingEl.classList.remove('thinking');
                        thinkingEl.classList.add(event.server_available ? 'assistant' : 'error');

                        const elapsedSec = (event.elapsed_ms / 1000).toFixed(1);
                        const tps = fullText.length
                            ? (fullText.length / (event.elapsed_ms / 1000)).toFixed(1)
                            : 0;
                        let footerHtml = `<div class="msg-footer"><span class="msg-time">${elapsedSec}s · ~${tps} tok/s</span>`;
                        if (!event.server_available) {
                            footerHtml += ` <span class="msg-error-tag">OFFLINE</span>`;
                        }
                        footerHtml += '</div>';

                        const contentHtml = event.server_available
                            ? escapeHtml(fullText).replace(/\n/g, '<br>')
                            : `<span style="color:#ef4444">${escapeHtml(fullText || event.error || '')}</span>`;

                        thinkingEl.innerHTML = contentHtml + footerHtml;
                    }

                    if (!event.server_available) {
                        setRemoteOffline(event.error);
                    }
                }
            }
        }
    } catch (err) {
        if (err.name === 'AbortError') {
            // User pressed Stop — leave partial text
            if (thinkingEl && fullText) {
                thinkingEl.classList.remove('thinking');
                thinkingEl.classList.add('assistant');
                thinkingEl.innerHTML = escapeHtml(fullText).replace(/\n/g, '<br>') +
                    '<div class="msg-footer"><span class="msg-time">stopped</span></div>';
            } else if (thinkingEl) {
                thinkingEl.remove();
            }
        } else {
            if (thinkingEl) {
                thinkingEl.classList.remove('thinking');
                thinkingEl.classList.add('error');
                thinkingEl.innerHTML = `⚠ Request failed: ${escapeHtml(err.message)}`;
            }
            setRemoteOffline(err.message);
        }
    }

    remoteAbortController = null;
    remoteSendBtn.style.display = '';
    remoteStopBtn.style.display = 'none';
    remoteStopBtn.disabled = true;
    remoteSendBtn.disabled = !remoteAvailable;
    remoteInput.disabled = !remoteAvailable;
    if (remoteAvailable) remoteInput.focus();
});

// ── Stop button ───────────────────────────────────────────────────────────

remoteStopBtn.addEventListener('click', () => {
    if (remoteAbortController) {
        remoteAbortController.abort();
        remoteStopBtn.disabled = true;
    }
});

// ── Clear ─────────────────────────────────────────────────────────────────

remoteClearBtn.addEventListener('click', async () => {
    try {
        await fetch(`/chat/remote/history?user_id=${encodeURIComponent(currentUserId)}`, {
            method: 'DELETE',
        });
    } catch (e) { /* ignore */ }
    remoteMessages.innerHTML = '<div class="empty-state">Start a conversation with the remote model...</div>';
});

// ── History ───────────────────────────────────────────────────────────────

async function loadRemoteHistory() {
    try {
        const resp = await fetch(`/chat/remote/history?user_id=${encodeURIComponent(currentUserId)}`);
        const data = await resp.json();
        if (data.history && data.history.length > 0) {
            remoteMessages.innerHTML = '';
            data.history.forEach(msg => {
                appendRemoteMessage(msg.role, msg.content, false);
            });
        }
    } catch (e) { /* ignore */ }
}

// ── Helpers ───────────────────────────────────────────────────────────────

function appendRemoteMessage(role, content, scroll = true) {
    const emptyState = remoteMessages.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = escapeHtml(content).replace(/\n/g, '<br>');
    remoteMessages.appendChild(div);

    if (scroll) {
        remoteMessages.scrollTop = remoteMessages.scrollHeight;
    }
}

// ── Periodic health check when tab is visible ──────────────────────────────

let remoteHealthInterval = null;

const remoteTabBtn = document.querySelector('.main-nav-tab[data-tab="remote"]');
if (remoteTabBtn) {
    remoteTabBtn.addEventListener('click', () => {
        if (remoteHealthInterval) clearInterval(remoteHealthInterval);
        // Check immediately if not checked yet or server is down
        if (!remoteChecked || !remoteAvailable) {
            checkRemoteHealth();
        }
        // Refresh health every 30 seconds while on this tab
        remoteHealthInterval = setInterval(checkRemoteHealth, 30000);
    });

    // A global observer: if tab switches away, stop polling
    document.querySelectorAll('.main-nav-tab').forEach(btn => {
        if (btn.dataset.tab !== 'remote') {
            btn.addEventListener('click', () => {
                if (remoteHealthInterval) {
                    clearInterval(remoteHealthInterval);
                    remoteHealthInterval = null;
                }
            });
        }
    });

    // ── Code Review ──────────────────────────────────────────────────────────

    async function loadReviewStatus() {
        try {
            const res = await fetch('/review/status');
            const data = await res.json();
            if (data.available) {
                const ragStatus = data.rag_available
                    ? `${data.rag_chunks} RAG chunks`
                    : 'no RAG context';
                reviewStatusText.textContent = `✅ Review ready · ${data.model} · ${ragStatus}`;
                reviewRunLocalBtn.disabled = false;
                reviewRunManualBtn.disabled = false;

                // Show current branch
                const currentBranchEl = document.getElementById('review-current-branch');
                if (currentBranchEl) {
                    if (data.current_branch) {
                        currentBranchEl.textContent = data.current_branch;
                        currentBranchEl.title = `Current branch: ${data.current_branch}`;
                    } else {
                        currentBranchEl.textContent = '—';
                        currentBranchEl.title = 'Current branch unknown';
                    }
                }

                // Populate base branch dropdown
                const branches = data.all_branches || [];
                if (branches.length > 0) {
                    const currentValue = reviewBaseBranch.value;
                    reviewBaseBranch.innerHTML = '';
                    branches.forEach(b => {
                        const opt = document.createElement('option');
                        opt.value = b;
                        opt.textContent = b;
                        reviewBaseBranch.appendChild(opt);
                    });
                    // Restore previous selection if still exists
                    if (currentValue && branches.includes(currentValue)) {
                        reviewBaseBranch.value = currentValue;
                    }
                }
            } else {
                reviewStatusText.textContent = `❌ Review unavailable${data.error ? ': ' + data.error : ''}`;
                reviewRunLocalBtn.disabled = true;
                reviewRunManualBtn.disabled = true;
            }
        } catch (e) {
            reviewStatusText.textContent = '❌ Cannot reach review service';
            reviewRunLocalBtn.disabled = true;
            reviewRunManualBtn.disabled = true;
        }
    }

    async function runLocalReview() {
        const baseBranch = reviewBaseBranch.value.trim() || 'main';

        setReviewLoading(true, 'Fetching diff from git MCP...');
        hideReviewResult();
        hideReviewError();

        try {
            const res = await fetch('/review/local', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ base_branch: baseBranch }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            renderReviewResult(data);
        } catch (err) {
            showReviewError(err.message);
        } finally {
            setReviewLoading(false);
        }
    }

    async function runManualReview() {
        const diffText = reviewDiffInput.value.trim();
        if (!diffText) {
            showReviewError('Please paste a git diff first.');
            return;
        }

        const filesStr = reviewChangedFiles.value.trim();
        const changedFiles = filesStr
            ? filesStr.split(',').map(s => s.trim()).filter(Boolean)
            : [];

        setReviewLoading(true, 'Analyzing diff...');
        hideReviewResult();
        hideReviewError();

        try {
            const res = await fetch('/review/pr', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    pr_title: reviewPrTitle.value.trim(),
                    pr_description: reviewPrDesc.value.trim(),
                    diff_text: diffText,
                    changed_files: changedFiles,
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            renderReviewResult(data);
        } catch (err) {
            showReviewError(err.message);
        } finally {
            setReviewLoading(false);
        }
    }

    function renderReviewResult(data) {
        const r = data.result || {};
        const s = r.summary || {};

        reviewOverall.textContent = `📋 ${s.overall_assessment || 'Review complete'}`;
        reviewTotalCount.textContent = `${s.total_issues || 0} issues found`;

        const model = r.model_used || '?';
        const elapsed = data.elapsed_ms || r.elapsed_ms || 0;
        const elapsedSec = (elapsed / 1000).toFixed(1);
        reviewResultMeta.textContent = `${model} · ${elapsedSec}s`;

        // Категории — ключ результата → ключ DOM
        const categories = [
            { key: 'bugs',                   domKey: 'bugs' },
            { key: 'architecture_issues',    domKey: 'architecture' },
            { key: 'security_issues',        domKey: 'security' },
            { key: 'performance_issues',     domKey: 'performance' },
            { key: 'recommendations',        domKey: 'recommendations' },
        ];

        categories.forEach(cat => {
            const items = r[cat.key] || [];
            const countEl = document.getElementById(`review-cat-${cat.domKey}-count`);
            const bodyEl  = document.getElementById(`review-cat-${cat.domKey}`);
            const headerEl = bodyEl ? bodyEl.closest('.review-cat')?.querySelector('.review-cat-header') : null;

            if (!countEl || !bodyEl) return;

            countEl.textContent = items.length;
            bodyEl.innerHTML = '';

            if (items.length === 0) {
                bodyEl.innerHTML = '<div class="review-cat-empty">No issues found</div>';
                if (headerEl) headerEl.classList.remove('has-issues');
            } else {
                if (headerEl) headerEl.classList.add('has-issues');
                bodyEl.style.display = 'none';  // свёрнуто по умолчанию

                items.forEach(issue => {
                    const sev = issue.severity || 'minor';
                    const sevClass = `review-sev-${sev}`;
                    const sevIcon = sev === 'critical' ? '🔴' : sev === 'major' ? '🟡' : '🟢';
                    const loc = issue.file_path ? `<span class="review-issue-file">${escHtml(issue.file_path)}</span>` : '';
                    const line = issue.line_number != null ? `<span class="review-issue-line">:${issue.line_number}</span>` : '';

                    const el = document.createElement('div');
                    el.className = 'review-issue';
                    el.innerHTML =
                        `<div class="review-issue-head">
                            ${sevIcon} <span class="review-issue-sev ${sevClass}">${sev.toUpperCase()}</span>
                            ${loc}${line}
                        </div>
                        <div class="review-issue-desc">${escHtml(issue.description)}</div>
                        ${issue.suggestion ? `<div class="review-issue-suggestion">💡 ${escHtml(issue.suggestion)}</div>` : ''}`;
                    bodyEl.appendChild(el);
                });
            }
        });

        // RAG sources
        const ragSources = data.rag_sources || r.rag_sources || [];
        if (ragSources.length > 0) {
            reviewRagSources.innerHTML = ragSources.map(rs =>
                `<div class="review-rag-source">
                    <span class="rag-source-loc">${escHtml(rs.source || '')} ${rs.section ? '/ ' + escHtml(rs.section) : ''}</span>
                    <span class="rag-source-score">${Math.round((rs.score || 0) * 100)}%</span>
                </div>`
            ).join('');
            reviewRagDetails.hidden = false;
        } else {
            reviewRagDetails.hidden = true;
        }

        showReviewResult();
    }

    function setReviewLoading(loading, text) {
        reviewLoading.style.display = loading ? '' : 'none';
        if (loading && text) {
            reviewLoadingText.textContent = text;
        }
        reviewRunLocalBtn.disabled = loading;
        reviewRunManualBtn.disabled = loading;
    }

    function showReviewResult() {
        reviewResult.style.display = '';
        reviewError.style.display = 'none';
    }

    function hideReviewResult() {
        reviewResult.style.display = 'none';
    }

    function showReviewError(msg) {
        reviewError.style.display = '';
        reviewError.textContent = `❌ ${msg}`;
        reviewResult.style.display = 'none';
    }

    function hideReviewError() {
        reviewError.style.display = 'none';
        reviewError.textContent = '';
    }

    // ── Mode tabs ──
    reviewModeTabs.forEach(btn => {
        btn.addEventListener('click', () => {
            reviewModeTabs.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            reviewMode = btn.dataset.mode;
            Object.values(reviewModePanels).forEach(p => p.classList.remove('active'));
            const panel = reviewModePanels[reviewMode];
            if (panel) panel.classList.add('active');
            hideReviewResult();
            hideReviewError();
        });
    });

    // ── Event bindings ──
    reviewRunLocalBtn.addEventListener('click', runLocalReview);
    reviewRunManualBtn.addEventListener('click', runManualReview);
    reviewResultClose.addEventListener('click', hideReviewResult);

    // Ctrl+Enter shortcut for diff textarea
    reviewDiffInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            runManualReview();
        }
    });

    // ── Category toggle ──
    document.addEventListener('click', e => {
        const header = e.target.closest('.review-cat-header');
        if (!header) return;
        const body = header.parentElement.querySelector('.review-cat-body');
        const toggle = header.querySelector('.review-cat-toggle');
        if (body) {
            const isOpen = body.style.display !== 'none';
            body.style.display = isOpen ? 'none' : '';
            if (toggle) toggle.textContent = isOpen ? '▸' : '▾';
        }
    });

    // ── Tab activation hook ──
    const reviewTabBtn = document.querySelector('.main-nav-tab[data-tab="review"]');
    if (reviewTabBtn) {
        reviewTabBtn.addEventListener('click', () => {
            loadReviewStatus();
        });
    }
}

// ── Support Tab ───────────────────────────────────────────────────────────────

let supportSelectedUserId = null;
let supportSelectedUser = null;
let supportSelectedTicketId = null;
let supportHistory = [];

const supportUserSelect   = document.getElementById('support-user-select');
const supportUserRefreshBtn = document.getElementById('support-user-refresh-btn');
const supportUserCard      = document.getElementById('support-user-card');
const supportNoUser        = document.getElementById('support-no-user');
const supportUserName      = document.getElementById('support-user-name');
const supportUserMeta      = document.getElementById('support-user-meta');
const supportUserTickets   = document.getElementById('support-user-tickets');
const supportContextBadge  = document.getElementById('support-context-badge');
const supportStatusBar     = document.getElementById('support-status-bar');
const supportMessages      = document.getElementById('support-messages');
const supportForm          = document.getElementById('support-chat-form');
const supportInput         = document.getElementById('support-input');
const supportSendBtn       = document.getElementById('support-send-btn');
const supportClearBtn      = document.getElementById('support-clear-btn');
const supportInputHistory = createInputHistory({
    input: supportInput,
    form: supportForm,
    clearBtn: supportClearBtn,
});

// ── Load users into dropdown ──────────────────────────────────────────────

supportUserSelect.addEventListener('change', () => {
    const userId = supportUserSelect.value;
    if (userId) {
        supportSelectedTicketId = null;
        selectSupportUser(userId);
    } else {
        supportUserCard.hidden = true;
        supportNoUser.hidden = false;
        supportContextBadge.hidden = true;
        supportSelectedUserId = null;
        supportSelectedTicketId = null;
    }
});

supportUserRefreshBtn.addEventListener('click', loadSupportUsers);

async function loadSupportUsers() {
    try {
        // Empty query returns all users
        const resp = await fetch('/support/users/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: '' }),
        });
        const data = await resp.json();

        const currentVal = supportUserSelect.value;
        supportUserSelect.innerHTML = '<option value="">— выберите пользователя —</option>';

        for (const u of (data.results || [])) {
            const opt = document.createElement('option');
            opt.value = u.id;
            opt.textContent = `${u.name} (${u.email || u.id})`;
            if (u.id === currentVal) opt.selected = true;
            supportUserSelect.appendChild(opt);
        }
    } catch (e) {
        console.error('loadSupportUsers:', e);
    }
}

// ── Select user ───────────────────────────────────────────────────────────

async function selectSupportUser(userId) {
    supportSelectedUserId = userId;
    supportSelectedUser = null;

    // Fetch user + tickets
    try {
        const [userResp, ticketsResp] = await Promise.all([
            fetch(`/support/users/${userId}`),
            fetch(`/support/users/${userId}/tickets`),
        ]);
        const userData = await userResp.json();
        const ticketsData = await ticketsResp.json();

        supportSelectedUser = userData.user;
        supportUserCard.hidden = false;
        supportNoUser.hidden = true;

        const u = supportSelectedUser;
        supportUserName.textContent = u.name;
        supportUserMeta.innerHTML = [
            `${escapeHtml(u.email)}`,
            `Тариф: ${escapeHtml(u.plan)}`,
            `Статус: ${escapeHtml(u.status)}`,
            `Компания: ${escapeHtml(u.company || '—')}`,
            `Теги: ${u.tags.length ? u.tags.join(', ') : '—'}`,
        ].join('<br>');

        const tickets = ticketsData.tickets || [];
        const active = tickets.filter(t => t.status === 'open' || t.status === 'in_progress');
        const closed = tickets.filter(t => t.status === 'closed' || t.status === 'resolved');

        const statusLabels = { open: 'открыт', in_progress: 'в работе', resolved: 'решён', closed: 'закрыт' };

        let html = '';
        if (active.length > 0) {
            html += '<div style="font-size:11px;color:#6b7280;margin-bottom:4px;">Активные</div>';
            html += active.map(t => `
                <div class="support-user-ticket-item" data-ticket-id="${escapeHtml(t.id)}">
                    <span class="support-ticket-status ${t.status}">${statusLabels[t.status] || t.status}</span>
                    ${escapeHtml(t.subject)}
                </div>
            `).join('');
        }
        if (closed.length > 0) {
            html += '<div style="font-size:11px;color:#6b7280;margin:8px 0 4px;">Закрытые</div>';
            html += closed.map(t => `
                <div class="support-user-ticket-item" data-ticket-id="${escapeHtml(t.id)}" style="opacity:0.6;">
                    <span class="support-ticket-status ${t.status}">${statusLabels[t.status] || t.status}</span>
                    ${escapeHtml(t.subject)}
                </div>
            `).join('');
        }
        supportUserTickets.innerHTML = html || '<div style="font-size:11px;color:#9ca3af;">Нет тикетов</div>';

        // Clickable tickets — select/deselect
        const attachTicketClicks = () => {
            supportUserTickets.querySelectorAll('.support-user-ticket-item').forEach(el => {
                el.addEventListener('click', () => {
                    const tid = el.dataset.ticketId;
                    if (supportSelectedTicketId === tid) {
                        supportSelectedTicketId = null;
                        supportContextBadge.textContent = `${u.name} · ${tickets.length} тикетов`;
                    } else {
                        supportSelectedTicketId = tid;
                        supportContextBadge.textContent = `${u.name} · ${tid}`;
                    }
                    supportContextBadge.hidden = false;
                    supportInput.focus();
                    // Refresh to update highlighting
                    refreshUserTickets(userId);
                });
            });
            // Restore highlight on previously selected ticket
            if (supportSelectedTicketId) {
                const selected = supportUserTickets.querySelector(`[data-ticket-id="${supportSelectedTicketId}"]`);
                if (selected) selected.classList.add('selected');
            }
        };
        attachTicketClicks();

        supportContextBadge.hidden = false;
        if (supportSelectedTicketId) {
            supportContextBadge.textContent = `${u.name} · ${supportSelectedTicketId}`;
        } else {
            supportContextBadge.textContent = `${u.name} · ${tickets.length} тикетов`;
        }
    } catch (e) {
        supportStatusBar.innerHTML = `<span style="color:#ef4444;">Ошибка: ${escapeHtml(e.message)}</span>`;
    }
}

// ── Refresh tickets only (lightweight, no profile reload) ────────────────

async function refreshUserTickets(userId) {
    try {
        const resp = await fetch(`/support/users/${userId}/tickets`);
        const ticketsData = await resp.json();
        const tickets = ticketsData.tickets || [];
        const active = tickets.filter(t => t.status === 'open' || t.status === 'in_progress');
        const closed = tickets.filter(t => t.status === 'closed' || t.status === 'resolved');
        const statusLabels = { open: 'открыт', in_progress: 'в работе', resolved: 'решён', closed: 'закрыт' };

        let html = '';
        if (active.length > 0) {
            html += '<div style="font-size:11px;color:#6b7280;margin-bottom:4px;">Активные</div>';
            html += active.map(t => `
                <div class="support-user-ticket-item" data-ticket-id="${escapeHtml(t.id)}">
                    <span class="support-ticket-status ${t.status}">${statusLabels[t.status] || t.status}</span>
                    ${escapeHtml(t.subject)}
                </div>
            `).join('');
        }
        if (closed.length > 0) {
            html += '<div style="font-size:11px;color:#6b7280;margin:8px 0 4px;">Закрытые</div>';
            html += closed.map(t => `
                <div class="support-user-ticket-item" data-ticket-id="${escapeHtml(t.id)}" style="opacity:0.6;">
                    <span class="support-ticket-status ${t.status}">${statusLabels[t.status] || t.status}</span>
                    ${escapeHtml(t.subject)}
                </div>
            `).join('');
        }
        supportUserTickets.innerHTML = html || '<div style="font-size:11px;color:#9ca3af;">Нет тикетов</div>';

        // Re-attach click handlers
        supportUserTickets.querySelectorAll('.support-user-ticket-item').forEach(el => {
            el.addEventListener('click', () => {
                const tid = el.dataset.ticketId;
                if (supportSelectedTicketId === tid) {
                    supportSelectedTicketId = null;
                    el.classList.remove('selected');
                    supportContextBadge.textContent = `${supportSelectedUser?.name || userId} · ${tickets.length} тикетов`;
                } else {
                    supportUserTickets.querySelectorAll('.support-user-ticket-item').forEach(e => e.classList.remove('selected'));
                    supportSelectedTicketId = tid;
                    el.classList.add('selected');
                    supportContextBadge.textContent = `${supportSelectedUser?.name || userId} · ${tid}`;
                }
                supportContextBadge.hidden = false;
                supportInput.focus();
            });
        });
    } catch (e) {
        // silently fail — ticket refresh is not critical
    }
}

// ── Chat ──────────────────────────────────────────────────────────────────

supportInput.addEventListener('input', () => {
    supportInput.style.height = 'auto';
    supportInput.style.height = `${supportInput.scrollHeight}px`;
});

supportForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const question = supportInput.value.trim();
    if (!question) return;

    supportInputHistory.push(question);

    supportInput.value = '';
    supportInput.style.height = 'auto';
    supportInput.disabled = true;
    supportSendBtn.disabled = true;

    // Add user message
    appendSupportMessage('user', question);
    // Show loading
    const loadingEl = appendSupportMessage('loading', '');

    try {
        const resp = await fetch('/support/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                user_identifier: supportSelectedUserId || '',
                ticket_id: supportSelectedTicketId || '',
                session_id: 'support_' + (supportSelectedUserId || 'default'),
            }),
        });
        const data = await resp.json();

        // Remove loading
        loadingEl.remove();

        if (data.error) {
            appendSupportMessage('assistant', `❌ Ошибка: ${data.error}`);
        } else {
            appendSupportMessage('assistant', data.answer, {
                ragSources: data.rag_sources,
                userContext: data.user_context,
                ticket: data.ticket,
                elapsedMs: data.elapsed_ms,
                ticketClosed: data.ticket_closed,
            });
            // Refresh ticket list after each message
            if (supportSelectedUserId) {
                refreshUserTickets(supportSelectedUserId);
            }
        }
    } catch (err) {
        loadingEl.remove();
        appendSupportMessage('assistant', `❌ Ошибка сети: ${escapeHtml(err.message)}`);
    }

    supportInput.disabled = false;
    supportSendBtn.disabled = false;
    supportInput.focus();
});

supportClearBtn.addEventListener('click', () => {
    supportHistory = [];
    supportMessages.innerHTML = '<div class="empty-state">Выберите пользователя в панели слева и задайте вопрос...</div>';
    supportContextBadge.hidden = true;
});

// ── Create ticket ─────────────────────────────────────────────────────────

const supportTicketSubject  = document.getElementById('support-ticket-subject');
const supportTicketDesc     = document.getElementById('support-ticket-desc');
const supportTicketPriority = document.getElementById('support-ticket-priority');
const supportTicketCategory = document.getElementById('support-ticket-category');
const supportTicketCreateBtn = document.getElementById('support-ticket-create-btn');
const supportTicketResult   = document.getElementById('support-ticket-result');

supportTicketCreateBtn.addEventListener('click', async () => {
    const subject = supportTicketSubject.value.trim();
    const description = supportTicketDesc.value.trim();
    if (!subject || !description) {
        supportTicketResult.hidden = false;
        supportTicketResult.className = 'support-ticket-result error';
        supportTicketResult.textContent = 'Тема и описание обязательны';
        return;
    }
    if (!supportSelectedUserId) {
        supportTicketResult.hidden = false;
        supportTicketResult.className = 'support-ticket-result error';
        supportTicketResult.textContent = 'Сначала выберите пользователя (поиск слева)';
        return;
    }

    supportTicketCreateBtn.disabled = true;
    supportTicketCreateBtn.textContent = '...';

    try {
        const resp = await fetch('/support/tickets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: supportSelectedUserId,
                subject,
                description,
                priority: supportTicketPriority.value,
                category: supportTicketCategory.value,
            }),
        });
        const data = await resp.json();
        if (resp.ok && data.ticket) {
            supportTicketResult.hidden = false;
            supportTicketResult.className = 'support-ticket-result success';
            supportTicketResult.textContent = `✅ Тикет ${data.ticket.id} создан`;
            // Clear form
            supportTicketSubject.value = '';
            supportTicketSubject.value = '';
            supportTicketDesc.value = '';
            // Auto-select new ticket and refresh
            supportSelectedTicketId = data.ticket.id;
            if (supportSelectedUserId) selectSupportUser(supportSelectedUserId);
        } else {
            throw new Error(data.error || data.detail || 'Unknown error');
        }
    } catch (e) {
        supportTicketResult.hidden = false;
        supportTicketResult.className = 'support-ticket-result error';
        supportTicketResult.textContent = `❌ ${escapeHtml(e.message)}`;
    }

    supportTicketCreateBtn.disabled = false;
    supportTicketCreateBtn.textContent = 'Создать';
});

function appendSupportMessage(role, text, meta = {}) {
    // Remove empty-state
    const empty = supportMessages.querySelector('.empty-state');
    if (empty) empty.remove();

    if (role === 'loading') {
        const div = document.createElement('div');
        div.className = 'support-loading';
        div.innerHTML = '<div class="support-loading-spinner"></div> Анализирую тикет и документацию...';
        supportMessages.appendChild(div);
        supportMessages.scrollTop = supportMessages.scrollHeight;
        return div;
    }

    const div = document.createElement('div');
    div.className = `message ${role}`;

    let html = escapeHtml(text).replace(/\n/g, '<br>');

    // Ticket auto-closed notification
    if (role === 'assistant' && meta.ticketClosed) {
        html = `<div style="background:#d1fae5;border:1px solid #22c55e;border-radius:6px;padding:8px 12px;margin-bottom:10px;font-size:13px;color:#065f46;">✅ Тикет закрыт — пользователь подтвердил решение проблемы.</div>` + html;
    }

    // Add meta info for assistant messages
    if (role === 'assistant' && meta.elapsedMs) {
        html += `<div style="font-size:10px;color:#9ca3af;margin-top:4px;">⏱ ${(meta.elapsedMs / 1000).toFixed(1)}s</div>`;
    }

    // RAG sources
    if (meta.ragSources && meta.ragSources.length > 0) {
        html += `
            <div class="support-message-sources">
                <details>
                    <summary>📚 Источники (${meta.ragSources.length})</summary>
                    <ul>
                        ${meta.ragSources.map(s => `<li>${escapeHtml(s.source || s.title || '—')} · ${escapeHtml(s.section || '')} · score: ${s.score?.toFixed(2) || '?'}</li>`).join('')}
                    </ul>
                </details>
            </div>`;
    }

    div.innerHTML = html;
    supportMessages.appendChild(div);
    supportMessages.scrollTop = supportMessages.scrollHeight;

    supportHistory.push({ role, text, meta });
    return div;
}

// ── Status ────────────────────────────────────────────────────────────────

async function loadSupportStatus() {
    try {
        const resp = await fetch('/support/status');
        const data = await resp.json();
        supportStatusBar.innerHTML = [
            `CRM: ${data.crm_available ? '✅ доступна' : '❌ недоступна'}`,
            `RAG: ${data.rag_available ? '✅ ' + data.rag_chunks + ' чанков' : '❌ недоступен'}`,
            `FAQ: ${data.faq_files ? data.faq_files.map(f => f.replace('docs/support/', '')).join(', ') : 'нет'}`,
        ].join('<br>');
    } catch (e) {
        supportStatusBar.innerHTML = `<span style="color:#ef4444;">Ошибка загрузки статуса</span>`;
    }
}

// ── File Assistant Tab ─────────────────────────────────────────────────────────

let fileFilesAffected = [];
let fileSessionId = 'file_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);

const fileStatusBar    = document.getElementById('file-status-bar');
const fileMessages     = document.getElementById('file-messages');
const fileForm         = document.getElementById('file-chat-form');
const fileInput        = document.getElementById('file-input');
const fileSendBtn      = document.getElementById('file-send-btn');
const fileClearBtn     = document.getElementById('file-clear-btn');
const fileInputHistory  = createInputHistory({
    input: fileInput,
    form: fileForm,
    clearBtn: fileClearBtn,
});
const fileAffectedList = document.getElementById('file-affected-list');

async function loadFileStatus() {
    try {
        const res = await fetch('/file/status');
        const data = await res.json();
        if (data.available) {
            fileStatusBar.innerHTML = `<span>Ready &middot; ${data.tool_count} tools &middot; ${escapeHtml(data.model)}</span>`;
        } else {
            fileStatusBar.innerHTML = `<span style="color:#ef4444;">Unavailable: ${escapeHtml(data.error || 'unknown')}</span>`;
        }
    } catch (e) {
        fileStatusBar.innerHTML = `<span style="color:#ef4444;">Cannot reach file assistant</span>`;
    }
}

function appendFileMessage(role, text) {
    const emptyState = fileMessages.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    const el = document.createElement('div');
    el.className = `message ${role}`;
    el.textContent = text;
    fileMessages.appendChild(el);
    fileMessages.scrollTop = fileMessages.scrollHeight;
    return el;
}

function renderFileFilesAffected() {
    fileAffectedList.innerHTML = '';
    if (fileFilesAffected.length === 0) {
        fileAffectedList.innerHTML = '<div class="file-empty">No files affected yet.</div>';
    } else {
        fileFilesAffected.forEach(f => {
            const el = document.createElement('div');
            el.className = 'file-affected-item';
            el.textContent = f;
            fileAffectedList.appendChild(el);
        });
    }
}

// Tab activation hook for the nav button
const fileTabBtn = document.querySelector('.main-nav-tab[data-tab="file"]');
if (fileTabBtn) {
    fileTabBtn.addEventListener('click', loadFileStatus);
}

fileInput.addEventListener('input', () => {
    fileInput.style.height = 'auto';
    fileInput.style.height = `${fileInput.scrollHeight}px`;
});

fileForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const task = fileInput.value.trim();
    if (!task) return;

    fileInputHistory.push(task);

    fileInput.value = '';
    fileInput.style.height = 'auto';
    fileInput.disabled = true;
    fileSendBtn.disabled = true;

    appendFileMessage('user', task);

    // Create a streaming message element
    const streamEl = document.createElement('div');
    streamEl.className = 'message assistant';
    fileMessages.appendChild(streamEl);
    fileMessages.scrollTop = fileMessages.scrollHeight;

    const emptyState = fileMessages.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    try {
        const resp = await fetch('/file/query/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task, session_id: fileSessionId }),
        });

        if (!resp.ok) {
            streamEl.textContent = `Error: HTTP ${resp.status}`;
        } else {
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';  // keep incomplete line

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const dataStr = line.slice(6);
                    try {
                        const event = JSON.parse(dataStr);
                        if (event.token) {
                            streamEl.textContent += event.token;
                        }
                        if (event.tool) {
                            // Show tool usage as a subtle indicator
                            const toolNote = document.createElement('span');
                            toolNote.className = 'file-tool-note';
                            toolNote.textContent = ` 🔧 ${event.tool}`;
                            streamEl.appendChild(toolNote);
                        }
                        if (event.done) {
                            fileFilesAffected = event.files_affected || [];
                            renderFileFilesAffected();
                        }
                        fileMessages.scrollTop = fileMessages.scrollHeight;
                    } catch (e) {
                        // skip malformed JSON
                    }
                }
            }
        }
    } catch (err) {
        streamEl.textContent = `Network error: ${escapeHtml(err.message)}`;
    }

    fileInput.disabled = false;
    fileSendBtn.disabled = false;
    fileInput.focus();
});

fileClearBtn.addEventListener('click', () => {
    fileSessionId = 'file_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
    fileFilesAffected = [];
    fileMessages.innerHTML = '<div class="empty-state">Give me a file-related task. Examples:<br>'
        + '"Find all usages of ChatAgent across the codebase"<br>'
        + '"Check all Python files for error handling patterns"<br>'
        + '"Generate a CHANGELOG.md from recent git commits"</div>';
    renderFileFilesAffected();
});