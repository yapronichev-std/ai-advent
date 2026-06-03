import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from agent import ChatAgent
from config import load_system_prompt, save_system_prompt
from diagram_pipeline import DiagramPipeline
from invariants import InvariantStore
from mcp_drawio_client import MCPDrawioClient
from mcp_multi import MultiMCPClient
from mcp_search_client import MCPSearchClient
from mcp_telegram_client import MCPTelegramClient
from mcp_weather import MCPWeatherClient
from profiles import UserProfileManager
from rag import RAGStore, RAGRetriever, compare_strategies

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

DEEPSEEK_API = "https://api.deepseek.com/v1/chat/completions"

AVAILABLE_MODELS = [
    {"id": "nvidia/nemotron-3-super-120b-a12b:free", "label": "Nemotron (OpenRouter, free)", "provider": "openrouter"},
    {"id": "deepseek/deepseek-chat", "label": "DeepSeek (OpenRouter)", "provider": "openrouter"},
    {"id": "deepseek-direct/deepseek-chat", "label": "DeepSeek (Direct API)", "provider": "deepseek", "api_key_env": "DEEPSEEK_API_KEY"},
]

DEFAULT_MODEL = "deepseek-direct/deepseek-chat"

api_key: str
deepseek_api_key: str = ""
agents: dict[str, ChatAgent] = {}
user_models: dict[str, str] = {}  # user_id → model_id
local_chat_history: dict[str, list[dict]] = {}  # user_id → messages for local Ollama chat
profile_manager = UserProfileManager()
invariant_store = InvariantStore()
mcp_client: MultiMCPClient | None = None
search_client: MCPSearchClient | None = None
telegram_client: MCPTelegramClient | None = None
telegram_chat_id: str = ""
diagram_pipeline: DiagramPipeline | None = None
rag_store: RAGStore | None = None
control_questions: list[dict] = []


def _parse_control_questions(filepath: str) -> list[dict]:
    """Parse контрольные вопросы.txt into a list of {id, question, expected_answer} dicts."""
    import re
    path = Path(filepath)
    if not path.exists():
        print(f"WARNING: Control questions file not found: {filepath}")
        return []

    text = path.read_text(encoding="utf-8")
    questions = []
    # Pattern: number. question text ... Ожидаемый ответ: answer text
    # Questions start with a digit followed by a period
    pattern = re.compile(
        r'(?:^|\n)(\d+)\.\s+(.*?)\nОжидаемый ответ:\s*(.*?)(?=\n\d+\.\s|\n*\Z)',
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        num = match.group(1)
        question = match.group(2).strip().replace('\n', ' ')
        expected = match.group(3).strip().replace('\n', ' ')
        questions.append({
            "id": int(num),
            "question": question,
            "expected_answer": expected,
        })
    return questions


def get_agent(user_id: str) -> ChatAgent:
    if user_id not in agents:
        model_id = user_models.get(user_id, DEFAULT_MODEL)
        agents[user_id] = ChatAgent(
            api_key=api_key,
            model=model_id,
            user_id=user_id,
            deepseek_api_key=deepseek_api_key,
            mcp_client=mcp_client,
            telegram_client=telegram_client,
            telegram_chat_id=telegram_chat_id,
            diagram_pipeline=diagram_pipeline,
            rag_store=rag_store,
        )
    return agents[user_id]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global api_key, deepseek_api_key, mcp_client, search_client, telegram_client, telegram_chat_id, diagram_pipeline, rag_store
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")

    # ── Создаём все MCP-клиенты ───────────────────────────────────────────────
    _drawio = MCPDrawioClient()
    # _search = MCPSearchClient()  # disabled

    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    _telegram: MCPTelegramClient | None = None
    if os.getenv("TELEGRAM_BOT_TOKEN") and telegram_chat_id:
        _telegram = MCPTelegramClient()
    else:
        print("INFO: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — Telegram notifications disabled")

    all_clients = [_drawio] + ([_telegram] if _telegram else [])

    # ── Подключаем все через MultiMCPClient ───────────────────────────────────
    mcp_client = MultiMCPClient(all_clients)
    try:
        await mcp_client.connect()
        print(f"MCP tools loaded ({len(mcp_client.tools)}): {[t['function']['name'] for t in mcp_client.tools]}")
    except Exception as e:
        print(f"WARNING: MCP clients unavailable: {e}")
        mcp_client = None

    # ── Отдельные ссылки для DiagramPipeline и Telegram-хуков ────────────────
    search_client = None  # mcp_search_server disabled
    telegram_client = _telegram if (_telegram and _telegram._session) else None

    if telegram_client:
        try:
            interval = int(os.getenv("TELEGRAM_SUMMARY_INTERVAL", "60"))
            result = await telegram_client.call_tool(
                "start_periodic_summary",
                {"chat_id": telegram_chat_id, "interval_seconds": interval},
            )
            print(f"Telegram MCP client connected. Periodic summary started: {result}")
        except Exception as e:
            print(f"WARNING: Telegram periodic summary failed: {e}")

    # ── Diagram pipeline ──────────────────────────────────────────────────────
    fallback_model = os.getenv("DRAWIO_FALLBACK_MODEL", "openai/gpt-4o")
    diagram_pipeline = DiagramPipeline(
        api_key=api_key,
        model=DEFAULT_MODEL,
        search_client=search_client,
        drawio_client=mcp_client,
        telegram_client=telegram_client,
        telegram_chat_id=telegram_chat_id,
        fallback_model=fallback_model,
    )
    print(
        f"DiagramPipeline ready  "
        f"search={'on' if search_client else 'off'}  "
        f"drawio={'on' if mcp_client else 'off'}  "
        f"telegram={'on' if telegram_client else 'off'}"
    )

    # ── RAG store ─────────────────────────────────────────────────────────────
    try:
        rag_store = RAGStore()
        print(f"RAGStore ready (Ollama nomic-embed-text, ChromaDB persistent)")
    except Exception as e:
        print(f"WARNING: RAGStore unavailable: {e}")
        rag_store = None

    # ── Control questions ───────────────────────────────────────────────────
    global control_questions
    control_questions = _parse_control_questions("docs/горчев/контрольные вопросы.txt")
    print(f"Control questions loaded: {len(control_questions)}")

    yield

    if mcp_client:
        await mcp_client.disconnect()


app = FastAPI(title="Chat Agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

Path("diagrams").mkdir(exist_ok=True)
app.mount("/diagrams", StaticFiles(directory="diagrams"), name="diagrams")


# ── Request / Response models ────────────────────────────────────────────────

class MessageRequest(BaseModel):
    text: str
    user_id: str = "default"


class MessageResponse(BaseModel):
    response: str
    history: list[dict]
    usage: dict
    user_id: str
    diagram_urls: list[str] = []
    rag_sources: list[dict] = []
    rag_no_context: bool = False


class FactRequest(BaseModel):
    key: str
    value: str


class LongTermRequest(BaseModel):
    key: str
    value: str


class SystemPromptRequest(BaseModel):
    prompt: str


class DemoRequest(BaseModel):
    topic: str = "Telegram bot"
    user_id: str = "default"


class InvariantRequest(BaseModel):
    text: str


class InvariantPatchRequest(BaseModel):
    active: bool


class TaskRequest(BaseModel):
    description: str


class TaskTransitionRequest(BaseModel):
    to_state: str


class TaskNextStepRequest(BaseModel):
    description: str = ""


LongTermCategory = Literal["profile", "decisions", "knowledge"]


# ── Frontend ─────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ── Demo ─────────────────────────────────────────────────────────────────────

@app.post("/demo", response_model=MessageResponse)
async def run_demo(request: DemoRequest):
    """
    Длинный флоу взаимодействия с несколькими MCP-серверами:
    погода → поиск → диаграмма → Telegram.
    """
    agent = get_agent(request.user_id)
    chat_id = telegram_chat_id or "не задан"
    prompt = (
        f"Выполни следующие шаги по порядку для темы «{request.topic}»:\n"
        f"1. Найди актуальную информацию через search-инструмент: возможности, "
        f"архитектура, best practices.\n"
        f"2. Построй компонентную диаграмму, отражающую архитектуру и ключевые "
        f"компоненты Telegram-бота (клиент, сервер, MCP-серверы, хранилище).\n"
        f"3. Отправь итоговый отчёт с диаграммой в Telegram. "
        f"Используй chat_id={chat_id}. Не спрашивай его у пользователя.\n"
        f"После завершения всех шагов кратко опиши результат."
    )
    response_text, usage, diagram_urls = await agent.send_message(prompt)
    return MessageResponse(
        response=response_text,
        history=agent.get_history(),
        usage=usage,
        user_id=request.user_id,
        diagram_urls=diagram_urls,
        rag_sources=agent.last_rag_sources,
        rag_no_context=agent.last_rag_no_context,
    )


# ── Chat ─────────────────────────────────────────────────────────────────────

@app.post("/chat", response_model=MessageResponse)
async def chat(request: MessageRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    agent = get_agent(request.user_id)
    response_text, usage, diagram_urls = await agent.send_message(request.text)
    return MessageResponse(
        response=response_text,
        history=agent.get_history(),
        usage=usage,
        user_id=request.user_id,
        diagram_urls=diagram_urls,
        rag_sources=agent.last_rag_sources,
        rag_no_context=agent.last_rag_no_context,
    )


@app.get("/history")
async def get_history(user_id: str = Query(default="default")):
    return {"history": get_agent(user_id).get_history(), "user_id": user_id}


@app.delete("/history")
async def clear_history(user_id: str = Query(default="default")):
    get_agent(user_id).clear_history()
    return {"status": "ok", "user_id": user_id}


# ── Local Chat (Ollama + llama.cpp) ────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434"
LLAMACPP_SERVER_URL = "http://localhost:8080"
LLAMACPP_MODELS_DIR = Path("/Users/yaroslav/develop/ai-assist/llama.cpp/models")
DEFAULT_LOCAL_MODEL = "ollama:llama3.2:3b"

# user_id → list of messages
local_chat_history: dict[str, list[dict]] = {}
# user_id → model_id (e.g. "ollama:llama3.2:3b" or "llamacpp:qwen2.5-1.5b-instruct-q4_k_m")
user_local_models: dict[str, str] = {}


class LocalChatResponse(BaseModel):
    response: str
    history: list[dict]
    model: str
    model_label: str
    elapsed_ms: int


class LocalModelSelectRequest(BaseModel):
    model_id: str


async def _discover_ollama_models() -> list[dict]:
    """Query Ollama for installed models. Returns [] if Ollama is not running."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        # Exclude embedding-only models (they can't chat)
        _non_chat = {"nomic-embed-text", "nomic-embed-text:latest", "all-minilm", "mxbai-embed"}
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            if name and name.split(":")[0] not in _non_chat and name not in _non_chat:
                models.append({
                    "id": f"ollama:{name}",
                    "label": f"{name} (Ollama)",
                    "provider": "ollama",
                    "model_name": name,
                })
        return models
    except Exception:
        return []


async def _discover_llamacpp_models() -> list[dict]:
    """Scan llama.cpp models directory for .gguf files (excluding vocab files)."""
    models = []
    if not LLAMACPP_MODELS_DIR.exists():
        return models
    for f in sorted(LLAMACPP_MODELS_DIR.iterdir()):
        if not f.is_file():
            continue
        name = f.name
        if not name.endswith(".gguf"):
            continue
        if name.startswith("ggml-vocab-"):
            continue
        # Derive a short label from the filename
        label = name.removesuffix(".gguf")
        models.append({
            "id": f"llamacpp:{name}",
            "label": f"{label} (llama.cpp)",
            "provider": "llamacpp",
            "model_name": name,
            "file_path": str(f),
        })
    return models


@app.get("/chat/local/models")
async def list_local_models():
    """Return available local models from Ollama and llama.cpp."""
    ollama_models, llamacpp_models = await asyncio.gather(
        _discover_ollama_models(),
        _discover_llamacpp_models(),
    )
    # Check if llama.cpp server is reachable
    llamacpp_available = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{LLAMACPP_SERVER_URL}/v1/models")
            llamacpp_available = resp.status_code == 200
    except Exception:
        pass

    all_models = ollama_models + llamacpp_models
    # Mark availability
    for m in all_models:
        if m["provider"] == "ollama":
            m["available"] = True  # we already know Ollama responded
        elif m["provider"] == "llamacpp":
            m["available"] = llamacpp_available

    return {
        "models": all_models,
        "default": DEFAULT_LOCAL_MODEL,
        "ollama_running": len(ollama_models) > 0,
        "llamacpp_running": llamacpp_available,
    }


@app.get("/chat/local/model")
async def get_local_model(user_id: str = Query(default="default")):
    model_id = user_local_models.get(user_id, DEFAULT_LOCAL_MODEL)
    return {"model": model_id, "user_id": user_id}


@app.post("/chat/local/model")
async def set_local_model(request: LocalModelSelectRequest, user_id: str = Query(default="default")):
    user_local_models[user_id] = request.model_id
    return {"model": request.model_id, "user_id": user_id}


def _resolve_local_model(user_id: str) -> tuple[str, str, str]:
    """Return (provider, model_name, file_path_or_empty) for the user's selected model."""
    model_id = user_local_models.get(user_id, DEFAULT_LOCAL_MODEL)
    if model_id.startswith("ollama:"):
        return "ollama", model_id[len("ollama:"):], ""
    elif model_id.startswith("llamacpp:"):
        name = model_id[len("llamacpp:"):]
        file_path = str(LLAMACPP_MODELS_DIR / name)
        return "llamacpp", name, file_path
    # Fallback
    return "ollama", "llama3.2:3b", ""


@app.post("/chat/local", response_model=LocalChatResponse)
async def chat_local(request: MessageRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    t0 = time.monotonic()

    provider, model_name, file_path = _resolve_local_model(request.user_id)
    model_id = user_local_models.get(request.user_id, DEFAULT_LOCAL_MODEL)

    user_id = request.user_id
    if user_id not in local_chat_history:
        local_chat_history[user_id] = []

    history = local_chat_history[user_id]
    history.append({"role": "user", "content": request.text})

    if provider == "ollama":
        reply = await _chat_ollama(history, model_name)
    elif provider == "llamacpp":
        reply = await _chat_llamacpp(history, model_name)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    history.append({"role": "assistant", "content": reply})

    elapsed_ms = round((time.monotonic() - t0) * 1000)

    # Derive a human-readable label for the model badge
    model_label = model_name.removesuffix(".gguf") if provider == "llamacpp" else model_name

    return LocalChatResponse(
        response=reply,
        history=history,
        model=model_id,
        model_label=model_label,
        elapsed_ms=elapsed_ms,
    )


async def _chat_ollama(history: list[dict], model_name: str) -> str:
    """Send messages to Ollama chat API."""
    messages = [{"role": m["role"], "content": m["content"]} for m in history]

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(3):
            try:
                resp = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": model_name,
                        "messages": messages,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["message"]["content"]
            except httpx.HTTPStatusError:
                raise
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(1)
    raise RuntimeError("Ollama: max retries exceeded")


async def _chat_llamacpp(history: list[dict], model_name: str) -> str:
    """Send messages to llama.cpp server via OpenAI-compatible API."""
    messages = [{"role": m["role"], "content": m["content"]} for m in history]

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(3):
            try:
                resp = await client.post(
                    f"{LLAMACPP_SERVER_URL}/v1/chat/completions",
                    json={
                        "model": model_name,
                        "messages": messages,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError:
                raise
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(1)
    raise RuntimeError("llama.cpp: max retries exceeded")


@app.get("/chat/local/history")
async def get_local_history(user_id: str = Query(default="default")):
    return {"history": local_chat_history.get(user_id, []), "user_id": user_id}


@app.delete("/chat/local/history")
async def clear_local_history(user_id: str = Query(default="default")):
    local_chat_history.pop(user_id, None)
    return {"status": "ok", "user_id": user_id}


# ── Tokens ───────────────────────────────────────────────────────────────────

@app.get("/tokens")
async def get_tokens(user_id: str = Query(default="default")):
    return get_agent(user_id).get_token_stats()


@app.delete("/tokens")
async def reset_tokens(user_id: str = Query(default="default")):
    get_agent(user_id).reset_tokens()
    return {"status": "ok", "user_id": user_id}


# ── Summary / short-term ─────────────────────────────────────────────────────

@app.get("/summary")
async def get_summary(user_id: str = Query(default="default")):
    return {"summary": get_agent(user_id).get_summary(), "user_id": user_id}


@app.get("/memory/short-term")
async def get_short_term_memory(user_id: str = Query(default="default")):
    agent = get_agent(user_id)
    history = agent.get_history()
    return {
        "message_count": len(history),
        "max_history": 10,
        "summary": agent.get_summary(),
        "user_id": user_id,
    }


# ── Memory endpoints ─────────────────────────────────────────────────────────

@app.get("/memory")
async def get_memory(user_id: str = Query(default="default")):
    return get_agent(user_id).memory.snapshot()


@app.get("/memory/working")
async def get_working_memory(user_id: str = Query(default="default")):
    return get_agent(user_id).memory.get_working()


@app.post("/memory/working/task")
async def set_task(request: TaskRequest, user_id: str = Query(default="default")):
    get_agent(user_id).memory.set_task(request.description)
    return {"status": "ok", "task": request.description, "user_id": user_id}


@app.post("/memory/working/fact")
async def add_working_fact(request: FactRequest, user_id: str = Query(default="default")):
    get_agent(user_id).memory.add_working_fact(request.key, request.value)
    return {"status": "ok", "key": request.key, "user_id": user_id}


@app.delete("/memory/working/fact/{key}")
async def delete_working_fact(key: str, user_id: str = Query(default="default")):
    deleted = get_agent(user_id).memory.delete_working_fact(key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Fact '{key}' not found")
    return {"status": "ok", "key": key, "user_id": user_id}


@app.delete("/memory/working")
async def clear_working_memory(user_id: str = Query(default="default")):
    get_agent(user_id).memory.clear_working()
    return {"status": "ok", "user_id": user_id}


@app.get("/memory/long-term/{category}")
async def get_long_term(category: LongTermCategory, user_id: str = Query(default="default")):
    return {"category": category, "entries": get_agent(user_id).memory.get_long_term(category), "user_id": user_id}


@app.post("/memory/long-term/{category}")
async def add_long_term(category: LongTermCategory, request: LongTermRequest, user_id: str = Query(default="default")):
    get_agent(user_id).memory.add_long_term(category, request.key, request.value)
    return {"status": "ok", "category": category, "key": request.key, "user_id": user_id}


@app.delete("/memory/long-term/{category}/{key}")
async def delete_long_term(category: LongTermCategory, key: str, user_id: str = Query(default="default")):
    deleted = get_agent(user_id).memory.delete_long_term(category, key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found in {category}")
    return {"status": "ok", "category": category, "key": key, "user_id": user_id}


# ── User profile management ──────────────────────────────────────────────────

@app.get("/users")
async def list_users():
    return {"users": profile_manager.list_users()}


@app.get("/users/{user_id}/profile")
async def get_user_profile(user_id: str):
    return {"user_id": user_id, "profile": profile_manager.get_profile(user_id)}


@app.delete("/users/{user_id}")
async def delete_user(user_id: str):
    if user_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete the default user")
    agents.pop(user_id, None)
    deleted = profile_manager.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
    return {"status": "ok", "user_id": user_id}


# ── Task FSM ─────────────────────────────────────────────────────────────────

@app.get("/task/state")
async def get_task_state(user_id: str = Query(default="default")):
    fsm = get_agent(user_id).memory.get_task_state()
    if not fsm:
        raise HTTPException(status_code=404, detail="No active task")
    return fsm.to_dict()


@app.post("/task/transition")
async def transition_task(request: TaskTransitionRequest, user_id: str = Query(default="default")):
    agent = get_agent(user_id)
    fsm = agent.memory.get_task_state()
    if not fsm:
        raise HTTPException(status_code=404, detail="No active task")
    try:
        fsm.transition(request.to_state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    agent.memory.save_task_state(fsm)
    return fsm.to_dict()


@app.post("/task/next-step")
async def next_task_step(request: TaskNextStepRequest, user_id: str = Query(default="default")):
    agent = get_agent(user_id)
    fsm = agent.memory.get_task_state()
    if not fsm:
        raise HTTPException(status_code=404, detail="No active task")
    fsm.next_step(request.description)
    agent.memory.save_task_state(fsm)
    return fsm.to_dict()


# ── System prompt ────────────────────────────────────────────────────────────

@app.get("/system-prompt")
async def get_system_prompt():
    return {"prompt": load_system_prompt()}


@app.put("/system-prompt")
async def update_system_prompt(request: SystemPromptRequest):
    save_system_prompt(request.prompt)
    return {"status": "ok", "prompt": request.prompt}


# ── Model selection ────────────────────────────────────────────────────────────

class ModelSelectRequest(BaseModel):
    model_id: str


@app.get("/models")
async def list_models():
    """Return available models, marking which ones are usable (API key present)."""
    models_out = []
    for m in AVAILABLE_MODELS:
        entry = dict(m)
        if m["provider"] == "deepseek":
            entry["available"] = bool(deepseek_api_key)
        else:
            entry["available"] = bool(api_key)
        models_out.append(entry)
    return {"models": models_out, "default": DEFAULT_MODEL}


@app.get("/model")
async def get_user_model(user_id: str = Query(default="default")):
    return {"model": user_models.get(user_id, DEFAULT_MODEL), "user_id": user_id}


@app.post("/model")
async def set_user_model(request: ModelSelectRequest, user_id: str = Query(default="default")):
    valid_ids = {m["id"] for m in AVAILABLE_MODELS}
    if request.model_id not in valid_ids:
        raise HTTPException(status_code=400, detail=f"Unknown model. Available: {', '.join(valid_ids)}")
    # Check API key availability
    model_def = next(m for m in AVAILABLE_MODELS if m["id"] == request.model_id)
    if model_def["provider"] == "deepseek" and not deepseek_api_key:
        raise HTTPException(status_code=400, detail="DEEPSEEK_API_KEY is not set")
    user_models[user_id] = request.model_id
    # Update existing agent if any
    if user_id in agents:
        agents[user_id].set_model(request.model_id)
    return {"model": request.model_id, "user_id": user_id}


# ── Invariants ────────────────────────────────────────────────────────────────

@app.get("/invariants")
async def list_invariants():
    return {"invariants": invariant_store.list_all()}


@app.post("/invariants", status_code=201)
async def add_invariant(request: InvariantRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Invariant text cannot be empty")
    return invariant_store.add(request.text)


@app.delete("/invariants/{inv_id}")
async def delete_invariant(inv_id: str):
    if not invariant_store.delete(inv_id):
        raise HTTPException(status_code=404, detail=f"Invariant '{inv_id}' not found")
    return {"status": "ok", "id": inv_id}


@app.patch("/invariants/{inv_id}")
async def patch_invariant(inv_id: str, request: InvariantPatchRequest):
    item = invariant_store.set_active(inv_id, request.active)
    if not item:
        raise HTTPException(status_code=404, detail=f"Invariant '{inv_id}' not found")
    return item


# ── RAG ───────────────────────────────────────────────────────────────────────

class RAGDocumentRequest(BaseModel):
    text: str
    source: str = ""
    strategy: str = "fixed"


class RAGCompareRequest(BaseModel):
    text: str
    source: str = ""


@app.post("/rag/documents/stream")
async def add_rag_document_stream(request: RAGDocumentRequest):
    """SSE stream: emits progress events while embedding each chunk."""
    if not rag_store:
        raise HTTPException(status_code=503, detail="RAG store unavailable (Ollama not running?)")
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Document text cannot be empty")
    strategy = request.strategy if request.strategy in ("fixed", "structural") else "fixed"

    async def event_gen():
        async for event in rag_store.add_document_stream(
            request.text, source=request.source, strategy=strategy
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/rag/documents", status_code=201)
async def add_rag_document(request: RAGDocumentRequest):
    if not rag_store:
        raise HTTPException(status_code=503, detail="RAG store unavailable (Ollama not running?)")
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Document text cannot be empty")
    strategy = request.strategy if request.strategy in ("fixed", "structural") else "fixed"
    result = await rag_store.add_document(request.text, source=request.source, strategy=strategy)
    return result


@app.get("/rag/documents")
async def list_rag_documents():
    if not rag_store:
        raise HTTPException(status_code=503, detail="RAG store unavailable")
    return {"documents": rag_store.list_documents()}


@app.delete("/rag/documents/{doc_id}")
async def delete_rag_document(doc_id: str):
    if not rag_store:
        raise HTTPException(status_code=503, detail="RAG store unavailable")
    if not rag_store.delete_document(doc_id):
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")
    return {"status": "ok", "doc_id": doc_id}


@app.post("/rag/compare")
async def compare_rag_strategies(request: RAGCompareRequest):
    """Compare fixed vs structural chunking side-by-side without storing embeddings."""
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Document text cannot be empty")
    return compare_strategies(request.text, source=request.source)


@app.get("/rag/search")
async def search_rag(
    q: str = Query(..., description="Search query"),
    top_k: int = Query(default=5, ge=1, le=20),
    pre_k: int = Query(default=10, ge=1, le=50, description="Chunks to fetch before reranking"),
    threshold: float = Query(default=0.0, ge=0.0, le=1.0, description="Min similarity score (0-1)"),
    rewrite: str = Query(default="none", pattern="^(none|keywords|expand)$"),
    use_mmr: bool = Query(default=True),
):
    if not rag_store:
        raise HTTPException(status_code=503, detail="RAG store unavailable")
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    retriever = RAGRetriever(rag_store)
    return await retriever.retrieve(
        q, pre_k=pre_k, post_k=top_k, threshold=threshold,
        rewrite=rewrite, use_mmr=use_mmr,
    )


@app.get("/rag/control-questions")
async def get_control_questions():
    """Return parsed control questions with expected answers."""
    return {"questions": control_questions, "count": len(control_questions)}


class RAGQueryCompareRequest(BaseModel):
    question: str
    user_id: str = "default"
    top_k: int = 5
    expected_answer: str = ""


@app.post("/rag/query-compare")
async def rag_query_compare(request: RAGQueryCompareRequest):
    """Ask the same question twice — with and without RAG context — and return both answers."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    agent = get_agent(request.user_id)
    result = await agent.compare_rag(request.question, top_k=request.top_k)
    if request.expected_answer:
        result["expected_answer"] = request.expected_answer
    return result


class RAGCompareAllRequest(BaseModel):
    question: str
    user_id: str = "default"
    pre_k: int = 10
    post_k: int = 5
    threshold: float = 0.3
    rewrite: str = "keywords"
    use_mmr: bool = True
    expected_answer: str = ""


@app.post("/rag/compare-all")
async def rag_compare_all(request: RAGCompareAllRequest):
    """Compare LLM answers across all RAG modes:
    no-rag, rag-basic, rag+rewrite, rag+rerank, rag+rewrite+rerank
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    agent = get_agent(request.user_id)
    result = await agent.compare_all_rag(
        question=request.question,
        pre_k=request.pre_k,
        post_k=request.post_k,
        threshold=request.threshold,
        rewrite=request.rewrite,
        use_mmr=request.use_mmr,
    )
    if request.expected_answer:
        result["expected_answer"] = request.expected_answer
    return result