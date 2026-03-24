# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

Copy `.env.example` to `.env` and set your OpenRouter API key:
```
OPENROUTER_API_KEY=your_api_key
```

Install dependencies:
```bash
pip install -r requirements.txt
```

## Running

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Or use `run.bat` on Windows. The app is then available at `http://localhost:8000`.

## Architecture

This is a minimal chat agent web app with two layers:

**Backend (`main.py` + `agent.py`)**
- FastAPI app serves the frontend and exposes three endpoints: `POST /chat`, `GET /history`, `DELETE /history`
- `ChatAgent` (`agent.py`) manages conversation state (in-memory history list) and calls the OpenRouter API (`https://openrouter.ai/api/v1/chat/completions`) via `httpx`
- The agent is instantiated once at startup via FastAPI's lifespan and held as a global — meaning history is shared across all browser sessions and lost on restart
- Model and system prompt are hardcoded in `main.py`

**Frontend (`static/`)**
- Single-page vanilla JS chat UI; communicates with the backend via `fetch`
- Enter submits, Shift+Enter inserts a newline

## Key design notes

- The OpenRouter API is called with only `model` and `messages` — no temperature or other sampling parameters by default
- History is prepended with the system prompt on every call via `_build_messages()`, but the system prompt is not stored in `self.history`
- There is no persistence layer; conversation history lives only in the `ChatAgent` instance
