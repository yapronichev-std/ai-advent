import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
from rag import RAGStore

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

#MODEL = "arcee-ai/trinity-large-preview:free"
MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

api_key: str
agents: dict[str, ChatAgent] = {}
profile_manager = UserProfileManager()
invariant_store = InvariantStore()
mcp_client: MultiMCPClient | None = None
search_client: MCPSearchClient | None = None
telegram_client: MCPTelegramClient | None = None
telegram_chat_id: str = ""
diagram_pipeline: DiagramPipeline | None = None
rag_store: RAGStore | None = None


def get_agent(user_id: str) -> ChatAgent:
    if user_id not in agents:
        agents[user_id] = ChatAgent(
            api_key=api_key,
            model=MODEL,
            user_id=user_id,
            mcp_client=mcp_client,
            telegram_client=telegram_client,
            telegram_chat_id=telegram_chat_id,
            diagram_pipeline=diagram_pipeline,
            rag_store=rag_store,
        )
    return agents[user_id]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global api_key, mcp_client, search_client, telegram_client, telegram_chat_id, diagram_pipeline, rag_store
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")

    # ── Создаём все MCP-клиенты ───────────────────────────────────────────────
    _drawio = MCPDrawioClient()
    _search = MCPSearchClient()

    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    _telegram: MCPTelegramClient | None = None
    if os.getenv("TELEGRAM_BOT_TOKEN") and telegram_chat_id:
        _telegram = MCPTelegramClient()
    else:
        print("INFO: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — Telegram notifications disabled")

    all_clients = [_drawio, _search] + ([_telegram] if _telegram else [])

    # ── Подключаем все через MultiMCPClient ───────────────────────────────────
    mcp_client = MultiMCPClient(all_clients)
    try:
        await mcp_client.connect()
        print(f"MCP tools loaded ({len(mcp_client.tools)}): {[t['function']['name'] for t in mcp_client.tools]}")
    except Exception as e:
        print(f"WARNING: MCP clients unavailable: {e}")
        mcp_client = None

    # ── Отдельные ссылки для DiagramPipeline и Telegram-хуков ────────────────
    search_client = _search if _search._session else None
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
        model=MODEL,
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
    )


@app.get("/history")
async def get_history(user_id: str = Query(default="default")):
    return {"history": get_agent(user_id).get_history(), "user_id": user_id}


@app.delete("/history")
async def clear_history(user_id: str = Query(default="default")):
    get_agent(user_id).clear_history()
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


@app.post("/rag/documents", status_code=201)
async def add_rag_document(request: RAGDocumentRequest):
    if not rag_store:
        raise HTTPException(status_code=503, detail="RAG store unavailable (Ollama not running?)")
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Document text cannot be empty")
    result = await rag_store.add_document(request.text, source=request.source)
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


@app.get("/rag/search")
async def search_rag(q: str = Query(..., description="Search query"), top_k: int = Query(default=5, ge=1, le=20)):
    if not rag_store:
        raise HTTPException(status_code=503, detail="RAG store unavailable")
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    results = await rag_store.retrieve(q, top_k=top_k)
    return {"query": q, "results": results}