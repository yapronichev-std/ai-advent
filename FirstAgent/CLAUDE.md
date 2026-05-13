# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

Copy `.env.example` to `.env` and set your OpenRouter API key (plus optional Telegram/Search settings):
```
OPENROUTER_API_KEY=your_api_key
```

Install Python dependencies:
```bash
pip install -r requirements.txt
```

RAG requires Ollama running locally with the embedding model pulled:
```bash
ollama pull nomic-embed-text
```

## Running

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Or `run.bat` on Windows. App is at `http://localhost:8000`.

## Architecture

This is a multi-user chat agent web app with memory, MCP tool integration, RAG, and a diagram pipeline.

**Backend layers:**

- **`main.py`** — FastAPI app, lifespan wiring, ~25 REST endpoints (chat, memory, invariants, task FSM, RAG, user management, system prompt, tokens, demo)
- **`agent.py`** — `ChatAgent`: message routing, history management (max 10 messages + summary compression), LLM calls via OpenRouter (`https://openrouter.ai/api/v1/chat/completions`), tool-calling loop, slash-command parsing, RAG context injection, diagram request classification
- **`memory.py`** — `MemoryStore`: three-tier memory per user — working (task + facts), task FSM state, long-term (profile/decisions/knowledge). All persisted as JSON under `memory/users/<user_id>/`
- **`config.py`** — Load/save system prompt from `memory/system_prompt.json`
- **`rag.py`** — `RAGStore`: ChromaDB (persistent, cosine) + Ollama `nomic-embed-text`. Two chunking strategies (`fixed` 500-char windows with 50-char overlap, `structural` by markdown headings). SSE streaming upload. Compare endpoint without indexing.
- **`diagram_pipeline.py`** — `DiagramPipeline`: 4-step orchestrated flow (mcp-search → LLM refine → mcp-drawio → mcp-telegram) with per-step timeouts. Used for diagram requests classified by the agent.
- **`task_state.py`** — `TaskFSM`: finite state machine with states planning/execution/validation/blocked/done and strict transitions. Injects FSM rules + allowed commands into system prompt.
- **`invariants.py`** — `InvariantStore`: global rules the assistant must never violate, injected as a system block.

**MCP subsystem** (all via stdio subprocesses):

- **`mcp_multi.py`** — `MultiMCPClient`: composite that aggregates multiple MCP clients into a unified tool list + dispatch map
- **`mcp_drawio_client.py`** — Client for `mcp_drawio_server/` (generates draw.io XML for class/component/use-case diagrams)
- **`mcp_weather.py`** — Client for weather MCP server
- **`mcp_telegram_client.py`** / `mcp_telegram_server/` — Client for sending messages/documents to Telegram
- **`mcp_search_client.py`** / `mcp_search_server/` — Client for web search (currently disabled in lifespan)

**Frontend (`static/`):**

- `index.html` — Tab-based layout: Chat (messages + memory sidebar) and RAG (document management + query comparison)
- `app.js` — Vanilla JS: chat submission, user switching, memory/invariant/FSM/RAG management, SSE document upload with progress, strategy comparison, RAG query comparison
- `style.css` — Styling including draw.io diagram viewer widgets

**Data directories** (created at runtime):
- `memory/users/<id>/` — per-user history.json, tokens.json, summary.json, working/ task state, long_term/ (profile, decisions, knowledge)
- `memory/invariants.json` — global invariants
- `memory/system_prompt.json` — editable system prompt
- `memory/rag/` — ChromaDB persistent storage
- `diagrams/` — served statically, populated by diagram pipeline

## Key design points

- **Model**: hardcoded in `main.py` (`MODEL = "nvidia/nemotron-3-super-120b-a12b:free"`). No temperature/sampling params passed.
- **Per-user agents**: `ChatAgent` instances are created lazily per `user_id`, held in a dict. Each gets its own MCP client reference, history, memory, and token stats.
- **Message construction** (`_build_messages`): system prompt → invariants block → memory context → RAG context → task FSM rules → summary → conversation history. Each block only included if non-empty.
- **Tool calling**: agent loops until `finish_reason != "tool_calls"`. Tool results > 6000 chars are truncated. `diagram_url` is extracted from JSON results and stripped before sending to LLM.
- **History compression**: when > 10 messages, older messages are summarized via LLM and stored as `self.summary`, injected as a system message.
- **Diagram classification**: `_classify_as_diagram` makes a lightweight LLM call (no history) to decide YES/NO before the main pipeline runs.
- **RAG graceful degradation**: if Ollama is down or `rag_store` is None, agent works without RAG — no errors.
- **MCP graceful degradation**: any MCP client that fails to connect is logged; others still work.