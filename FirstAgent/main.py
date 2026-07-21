import asyncio
import json
import logging
import os
import platform
import subprocess
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

from activity import activity
from agent import ChatAgent
from code_review import CodeReviewAgent
from config import load_system_prompt, save_system_prompt
from diagram_pipeline import DiagramPipeline
from invariants import InvariantStore
from mcp_crm_client import MCPCRMClient
from mcp_drawio_client import MCPDrawioClient
from mcp_git_client import MCPGitClient
from mcp_multi import MultiMCPClient
from mcp_search_client import MCPSearchClient
from mcp_telegram_client import MCPTelegramClient
from mcp_weather import MCPWeatherClient
from profiles import UserProfileManager
from rag import RAGStore, RAGRetriever, compare_strategies, rewrite_query, rerank_results
from file_assistant import FileAssistant
from support_agent import SupportAgent

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
git_client: MCPGitClient | None = None
search_client: MCPSearchClient | None = None
telegram_client: MCPTelegramClient | None = None
telegram_chat_id: str = ""
diagram_pipeline: DiagramPipeline | None = None
rag_store: RAGStore | None = None
review_agent: CodeReviewAgent | None = None
crm_client: MCPCRMClient | None = None
support_agent: SupportAgent | None = None
file_assistant: FileAssistant | None = None
control_questions: list[dict] = []

# ── RAG indexing status (отдаётся в UI через GET /rag/index-status) ──────────
rag_index_status: dict = {
    "state": "idle",   # idle | indexing | done | error
    "total": 0,        # файлов к индексации
    "done": 0,         # файлов проиндексировано
    "current": "",     # текущий файл
    "error": "",
    "hint": "",        # подсказка пользователю (например, как запустить Ollama)
}

OLLAMA_START_HINT = (
    "Запустите Ollama и скачайте модель эмбеддингов:\n"
    "  ollama serve\n"
    "  ollama pull nomic-embed-text\n"
    "Затем перезапустите приложение или переключите проект для повторной индексации."
)


async def _check_ollama() -> str:
    """Проверить доступность Ollama. Возвращает пустую строку если OK, иначе сообщение об ошибке."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 11434), timeout=3.0
        )
        writer.close()
        await writer.wait_closed()
        return ""
    except Exception as e:
        return f"Ollama недоступна (localhost:11434): {e}"


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


async def _index_project_docs(rag_store: RAGStore) -> None:
    """Auto-index project docs into RAG + activity-события для панели активности."""
    activity.set_current("Индексация документации проекта...", agent="system")
    try:
        await _index_project_docs_inner(rag_store)
    finally:
        activity.clear_current()


async def _index_project_docs_inner(rag_store: RAGStore) -> None:
    """Auto-index README.md, CLAUDE.md and all text files from docs/ into RAG.

    Uses the active project path from rag_store.
    Skips sources that are already indexed to avoid duplicates across restarts.
    """
    rag_index_status.update(state="indexing", total=0, done=0, current="", error="", hint="")

    # ── Quick health check: убедимся, что Ollama доступна ───────────────────
    err = await _check_ollama()
    if err:
        print(f"  RAG indexing ABORTED: {err}")
        rag_index_status.update(state="error", error=err, current="", hint=OLLAMA_START_HINT)
        activity.emit("rag_index", "Индексация прервана: Ollama недоступна", agent="system")
        return

    project_root = Path(rag_store.project_path).resolve()
    docs_to_index: list[tuple[str, str, str]] = []  # (filepath, source_label, strategy)

    # README.md
    readme = project_root / "README.md"
    if readme.exists():
        docs_to_index.append((str(readme), "README.md", "structural"))

    # CLAUDE.md
    claude_md = project_root / "CLAUDE.md"
    if claude_md.exists():
        docs_to_index.append((str(claude_md), "CLAUDE.md", "structural"))

    # Files from docs/ directory (recursively, text files only)
    docs_dir = project_root / "docs"
    if docs_dir.exists():
        text_extensions = {".txt", ".md", ".rst", ".py", ".json", ".yaml", ".yml", ".xml", ".html", ".css", ".js"}
        for fpath in docs_dir.rglob("*"):
            if fpath.is_file() and fpath.suffix.lower() in text_extensions:
                rel = fpath.relative_to(project_root)
                docs_to_index.append((str(fpath), str(rel), "fixed"))

    if not docs_to_index:
        print("No project documentation files found to index into RAG")
        rag_index_status.update(state="done", current="")
        return

    # ── Determine which sources are already indexed ─────────────────────────
    try:
        existing = rag_store._collection.get(include=["metadatas"])
        indexed_sources: set[str] = set()
        if existing and existing["metadatas"]:
            for meta in existing["metadatas"]:
                src = meta.get("source", "")
                if src:
                    indexed_sources.add(src)
    except Exception:
        indexed_sources = set()

    new_docs = [
        (fp, src, strat) for fp, src, strat in docs_to_index
        if src not in indexed_sources
    ]

    if not new_docs:
        print(f"Project docs already indexed ({len(docs_to_index)} sources up to date)")
        rag_index_status.update(state="done", current="")
        return

    print(f"Indexing {len(new_docs)} new project documentation file(s) into RAG...")
    rag_index_status.update(total=len(new_docs))
    activity.emit("rag_index", f"Индексация {len(new_docs)} файлов документации...", agent="system",
                  detail={"total": len(new_docs)})
    indexed = 0
    embedding_failures = 0
    for filepath, source, strategy in new_docs:
        rag_index_status.update(current=source)
        activity.set_current(f"Индексация: {source}...", agent="system")
        try:
            text = Path(filepath).read_text(encoding="utf-8")
            # Skip very large files (> 1MB) to avoid overwhelming RAG
            if len(text) > 1_000_000:
                print(f"  SKIP (too large, {len(text)} bytes): {source}")
                activity.emit("rag_index", f"Пропущен (слишком большой): {source}", agent="system",
                              detail={"source": source, "size": len(text)})
                rag_index_status["done"] += 1
                continue
            result = await rag_store.add_document(text=text, source=source, strategy=strategy)
            print(f"  OK  {source} → {result.get('chunks', 0)} chunks [{result.get('strategy', strategy)}]")
            activity.emit("rag_index", f"Проиндексирован: {source} ({result.get('chunks', 0)} чанков)",
                          agent="system",
                          detail={"source": source, "chunks": result.get("chunks", 0)})
            indexed += 1
        except Exception as e:
            print(f"  FAIL  {source}: {e}")
            activity.emit("rag_index", f"Ошибка индексации: {source}", agent="system",
                          detail={"source": source, "error": str(e)})
            embedding_failures += 1
            if embedding_failures >= 2:
                msg = f"Два сбоя эмбеддинга подряд — вероятно Ollama недоступна: {e}"
                print(f"  RAG indexing ABORTED — {msg}")
                rag_index_status.update(state="error", error=msg, current="", hint=OLLAMA_START_HINT)
                activity.emit("rag_index", "Индексация прервана: сбои эмбеддинга", agent="system")
                return
        else:
            embedding_failures = 0  # сброс при успехе
        rag_index_status["done"] += 1

    rag_index_status.update(state="done", current="")
    activity.emit("rag_index", f"Проиндексировано {indexed}/{len(new_docs)} файлов", agent="system",
                  detail={"indexed": indexed, "total": len(new_docs)})
    print(f"Project docs indexed: {indexed}/{len(new_docs)} new")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global api_key, deepseek_api_key, mcp_client, git_client, search_client, telegram_client, telegram_chat_id, diagram_pipeline, rag_store, crm_client, support_agent, file_assistant
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")

    # ── Создаём все MCP-клиенты ───────────────────────────────────────────────
    _drawio = MCPDrawioClient()
    _git = MCPGitClient()
    _crm = MCPCRMClient()
    # _search = MCPSearchClient()  # disabled

    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    _telegram: MCPTelegramClient | None = None
    if os.getenv("TELEGRAM_BOT_TOKEN") and telegram_chat_id:
        _telegram = MCPTelegramClient()
    else:
        print("INFO: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — Telegram notifications disabled")

    all_clients = [_drawio, _git, _crm] + ([_telegram] if _telegram else [])

    # Store the git client globally so we can reconnect it on project switch
    git_client = _git
    crm_client = _crm

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
        default_project = Path(os.getenv("PROJECT_ROOT", Path.cwd())).resolve()
        rag_store = RAGStore(project_path=str(default_project))
        print(f"RAGStore ready (Ollama nomic-embed-text, ChromaDB, per-project collections)")
    except Exception as e:
        print(f"WARNING: RAGStore unavailable: {e}")
        rag_store = None

    # ── Auto-index project documentation into RAG (в фоне, чтобы не блокировать старт) ──
    index_task: asyncio.Task | None = None
    if rag_store:
        async def _index_in_background(store: RAGStore) -> None:
            try:
                await _index_project_docs(store)
            except Exception as e:
                hint = OLLAMA_START_HINT if "ollama" in str(e).lower() or "connect" in str(e).lower() else ""
                rag_index_status.update(state="error", error=str(e), current="", hint=hint)
                print(f"WARNING: background RAG indexing failed: {e}")

        index_task = asyncio.create_task(_index_in_background(rag_store))
        print("RAG indexing started in background (server is available immediately)")

    # ── Code Review Agent ──────────────────────────────────────────────────────
    global review_agent
    try:
        review_agent = CodeReviewAgent(
            api_key=api_key,
            deepseek_api_key=deepseek_api_key,
            model=DEFAULT_MODEL,
            rag_store=rag_store,
            mcp_client=mcp_client,
        )
        print("CodeReviewAgent ready")
    except Exception as e:
        print(f"WARNING: CodeReviewAgent unavailable: {e}")
        review_agent = None

    # ── Support Agent ─────────────────────────────────────────────────────────
    try:
        support_agent = SupportAgent(
            api_key=api_key,
            deepseek_api_key=deepseek_api_key,
            model=DEFAULT_MODEL,
            rag_store=rag_store,
            crm_client=crm_client if crm_client and mcp_client else None,
        )
        print("SupportAgent ready")
    except Exception as e:
        print(f"WARNING: SupportAgent unavailable: {e}")
        support_agent = None

    # ── File Assistant Agent ────────────────────────────────────────────────────
    try:
        file_assistant = FileAssistant(
            api_key=api_key,
            deepseek_api_key=deepseek_api_key,
            model=DEFAULT_MODEL,
            mcp_client=mcp_client,
        )
        print("FileAssistant ready")
    except Exception as e:
        print(f"WARNING: FileAssistant unavailable: {e}")
        file_assistant = None

    # ── Control questions ───────────────────────────────────────────────────
    global control_questions
    control_questions = _parse_control_questions("docs/горчев/контрольные вопросы.txt")
    print(f"Control questions loaded: {len(control_questions)}")

    activity.emit("system", "Приложение запущено", agent="system")

    yield

    # ── Shutdown cleanup ─────────────────────────────────────────────────────
    # Отменяем фоновую индексацию, если ещё идёт
    if index_task and not index_task.done():
        index_task.cancel()
        try:
            await index_task
        except (asyncio.CancelledError, Exception):
            pass

    # MCP disconnect: anyio cancel scopes внутри MCP-клиентов ломаются при
    # отмене lifespan-таска uvicorn'ом. Отключаем их тихо — соединения
    # всё равно закроются по TCP timeout при выходе процесса.
    if mcp_client:
        import logging as _logging
        _mcp_logger = _logging.getLogger("mcp_multi")
        _prev_level = _mcp_logger.level
        _mcp_logger.setLevel(_logging.ERROR)
        try:
            await mcp_client.disconnect()
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            _mcp_logger.setLevel(_prev_level)


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


class PRReviewRequest(BaseModel):
    pr_title: str = ""
    pr_description: str = ""
    base_branch: str = "main"
    head_branch: str = ""
    diff_text: str
    changed_files: list[str] = []
    user_id: str = "review"


class PRReviewResponse(BaseModel):
    result: dict
    summary: dict
    rag_sources: list[dict] = []
    error: str | None = None
    elapsed_ms: int = 0


class LocalReviewRequest(BaseModel):
    base_branch: str = "main"
    user_id: str = "review"


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


# ── Project switching ───────────────────────────────────────────────────────────

@app.get("/rag/index-status")
async def get_rag_index_status():
    """Return the current state of background RAG documentation indexing."""
    return {
        **rag_index_status,
        "rag_chunks": rag_store.count() if rag_store else 0,
    }


@app.get("/activity")
async def get_activity(since: int = Query(default=0)):
    """Return recent activity events and current agent action (for the bottom panel)."""
    return activity.get_state(since=since)


@app.get("/project")
async def get_project_info():
    """Return current project root, branch, and indexed doc count."""
    info = {
        "project_root": str(Path(os.getenv("PROJECT_ROOT", Path.cwd())).resolve()),
        "rag_doc_count": rag_store.count() if rag_store else 0,
    }
    # Try to get git branch
    if mcp_client:
        try:
            branch_json = await mcp_client.call_tool("get_git_branch", {})
            branch_data = json.loads(branch_json)
            info["git_branch"] = branch_data.get("current_branch", "?")
            info["all_branches"] = branch_data.get("all_branches", [])
            lc = branch_data.get("last_commit")
            if lc:
                info["last_commit"] = f"{lc.get('message', '')[:80]} ({lc.get('author', '?')})"
        except Exception:
            info["git_branch"] = "unknown"
    return info


@app.post("/project")
async def switch_project(request: dict):
    """Switch to a different project directory.

    Expects: {"project_root": "/absolute/path/to/project"}
    Reconnects the git MCP client and re-indexes docs from the new project.
    """
    global mcp_client, git_client, rag_store

    new_root = request.get("project_root", "").strip()
    if not new_root:
        raise HTTPException(status_code=400, detail="project_root is required")

    new_path = Path(new_root).resolve()
    if not new_path.exists():
        raise HTTPException(status_code=400, detail=f"Directory not found: {new_path}")
    if not new_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {new_path}")

    # ── Update git MCP project root ──────────────────────────────────────
    if mcp_client:
        try:
            await mcp_client.call_tool("set_project_root", {"path": str(new_path)})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to set project root: {e}")

    # ── Update PROJECT_ROOT for future RAG indexing ───────────────────────
    os.environ["PROJECT_ROOT"] = str(new_path)

    # ── Switch RAG to the new project's collection ─────────────────────────
    reindex_result = {"indexed": 0, "skipped": False}
    if rag_store:
        rag_store.set_project(str(new_path))
        if rag_store.count() == 0:
            # First time — index docs
            await _index_project_docs(rag_store)
            reindex_result["indexed"] = rag_store.count()
        else:
            reindex_result["indexed"] = rag_store.count()
            reindex_result["skipped"] = True

    # ── Get git branch for response ──────────────────────────────────────
    branch_info = {}
    if mcp_client:
        try:
            branch_json = await mcp_client.call_tool("get_git_branch", {})
            branch_data = json.loads(branch_json)
            branch_info["branch"] = branch_data.get("current_branch", "?")
        except Exception:
            branch_info["branch"] = "?"

    # ── Remember this project ────────────────────────────────────────────
    _add_recent_project(str(new_path), branch_info.get("branch", ""))

    return {
        "status": "ok",
        "project_root": str(new_path),
        "git_branch": branch_info.get("branch", "?"),
        "rag_chunks": reindex_result["indexed"],
        "rag_skipped": reindex_result.get("skipped", False),
        "mcp_tools": len(mcp_client.tools) if mcp_client else 0,
    }


@app.post("/project/stream")
async def switch_project_stream(request: dict):
    """SSE-streamed project switch with progress events.

    Events: {type: "progress", stage: "git"|"rag"|"done",
             message: str, current: int, total: int}
    """
    global mcp_client, git_client, rag_store

    new_root = request.get("project_root", "").strip()
    if not new_root:
        raise HTTPException(status_code=400, detail="project_root is required")

    new_path = Path(new_root).resolve()
    if not new_path.exists():
        raise HTTPException(status_code=400, detail=f"Directory not found: {new_path}")
    if not new_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {new_path}")

    async def event_stream():
        activity.set_current(f"Переключение проекта: {new_path.name}...", agent="system")
        activity.emit("project_switch", f"Переключение на {new_path.name}", agent="system",
                      detail={"path": str(new_path)})
        try:
            async for chunk in _switch_project_events(new_path):
                yield chunk
        finally:
            activity.clear_current()

    async def _switch_project_events(new_path):
        # ── Stage 1: Git reconnect ────────────────────────────────────────
        yield _sse({"type": "progress", "stage": "git", "message": "Reconnecting git...",
                      "current": 0, "total": 1})

        if mcp_client:
            try:
                await mcp_client.call_tool("set_project_root", {"path": str(new_path)})
                yield _sse({"type": "progress", "stage": "git", "message": "Git connected",
                              "current": 1, "total": 1})
            except Exception as e:
                yield _sse({"type": "error", "message": f"Failed to set project root: {e}"})
                return

        # ── Stage 2: RAG re-index ──────────────────────────────────────────
        os.environ["PROJECT_ROOT"] = str(new_path)

        if rag_store:
            rag_store.set_project(str(new_path))
            if rag_store.count() == 0:
                # ── Health check: Ollama должна быть доступна ──────────────
                ollama_err = await _check_ollama()
                if ollama_err:
                    rag_index_status.update(state="error", error=ollama_err, current="", hint=OLLAMA_START_HINT)
                    yield _sse({"type": "error", "message": ollama_err})
                    return

                # Collect and index — inline for progress events
                project_root = new_path
                docs_to_index: list[tuple[str, str, str]] = []
                for md_name in ["README.md", "CLAUDE.md"]:
                    f = project_root / md_name
                    if f.exists():
                        docs_to_index.append((str(f), md_name, "structural"))

                docs_dir = project_root / "docs"
                if docs_dir.exists():
                    text_exts = {".txt", ".md", ".rst", ".py", ".json", ".yaml", ".yml", ".xml", ".html", ".css", ".js"}
                    for fpath in docs_dir.rglob("*"):
                        if fpath.is_file() and fpath.suffix.lower() in text_exts:
                            docs_to_index.append((str(fpath), str(fpath.relative_to(project_root)), "fixed"))

                total = len(docs_to_index)
                rag_index_status.update(state="indexing", total=total, done=0, current="", error="", hint="")
                yield _sse({"type": "progress", "stage": "rag", "message": f"Indexing {total} docs...",
                              "current": 0, "total": total})

                embedding_failures = 0
                for i, (filepath, source, strategy) in enumerate(docs_to_index):
                    rag_index_status.update(current=source)
                    activity.set_current(f"Индексация: {source}...", agent="system")
                    try:
                        text = Path(filepath).read_text(encoding="utf-8")
                        if len(text) > 1_000_000:
                            activity.emit("rag_index", f"Пропущен (слишком большой): {source}", agent="system",
                                          detail={"source": source, "size": len(text)})
                            rag_index_status["done"] += 1
                            continue
                        result = await rag_store.add_document(text=text, source=source, strategy=strategy)
                        activity.emit("rag_index",
                                      f"Проиндексирован: {source} ({result.get('chunks', 0)} чанков)",
                                      agent="system",
                                      detail={"source": source, "chunks": result.get("chunks", 0)})
                        yield _sse({"type": "progress", "stage": "rag",
                                      "message": f"Indexed: {source}",
                                      "current": i + 1, "total": total})
                        embedding_failures = 0
                    except Exception as e:
                        activity.emit("rag_index", f"Ошибка индексации: {source}", agent="system",
                                      detail={"source": source, "error": str(e)})
                        embedding_failures += 1
                        if embedding_failures >= 2:
                            msg = f"Два сбоя эмбеддинга подряд — Ollama недоступна: {e}"
                            rag_index_status.update(state="error", error=msg, current="", hint=OLLAMA_START_HINT)
                            yield _sse({"type": "error", "message": msg})
                            return
                    rag_index_status["done"] += 1
                rag_index_status.update(state="done", current="")
                activity.emit("rag_index", f"Проиндексировано {total} файлов документации", agent="system",
                              detail={"total": total})
            else:
                rag_index_status.update(state="done", current="")
                yield _sse({"type": "progress", "stage": "rag",
                              "message": f"Already indexed ({rag_store.count()} chunks) — skipping",
                              "current": 1, "total": 1})

        # ── Stage 3: Done ──────────────────────────────────────────────────
        branch_info = {}
        if mcp_client:
            try:
                branch_json = await mcp_client.call_tool("get_git_branch", {})
                branch_data = json.loads(branch_json)
                branch_info["branch"] = branch_data.get("current_branch", "?")
            except Exception:
                branch_info["branch"] = "?"

        _add_recent_project(str(new_path), branch_info.get("branch", ""))
        chunk_count = rag_store.count() if rag_store else 0

        yield _sse({"type": "done",
                      "project_root": str(new_path),
                      "git_branch": branch_info.get("branch", "?"),
                      "rag_chunks": chunk_count,
                      "mcp_tools": len(mcp_client.tools) if mcp_client else 0})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/pick-folder")
async def pick_folder():
    """Open the native OS folder picker and return the absolute path.

    macOS — Finder via osascript
    Linux — Zenity / KDialog
    Windows — PowerShell FolderBrowserDialog
    """
    system = platform.system()

    if system == "Darwin":
        script = (
            'tell application "Finder"\n'
            '    activate\n'
            '    set folderPath to choose folder '
            'with prompt "Select project folder"\n'
            '    return POSIX path of folderPath\n'
            'end tell'
        )
        cmd = ["osascript", "-e", script]

    elif system == "Linux":
        if subprocess.run(["which", "zenity"], capture_output=True).returncode == 0:
            cmd = ["zenity", "--file-selection", "--directory",
                   "--title=Select project folder"]
        elif subprocess.run(["which", "kdialog"], capture_output=True).returncode == 0:
            cmd = ["kdialog", "--getexistingdirectory", os.path.expanduser("~")]
        else:
            raise HTTPException(status_code=400, detail="Install zenity: sudo apt install zenity")

    elif system == "Windows":
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$f.Description = 'Select project folder'; "
            "if ($f.ShowDialog() -eq 'OK') { $f.SelectedPath }"
        )
        cmd = ["powershell", "-Command", ps_script]

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {system}")

    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Dialog timed out")

    selected = result.stdout.strip()
    err = result.stderr.strip()

    # User cancelled
    if result.returncode != 0 or not selected:
        return {"path": None, "cancelled": True}

    p = Path(selected)
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {selected}")

    return {"path": str(p), "cancelled": False}


# ── Recent projects ─────────────────────────────────────────────────────────────

RECENT_PROJECTS_FILE = Path("memory/recent_projects.json")
MAX_RECENT_PROJECTS = 20


def _load_recent_projects() -> list[dict]:
    """Return list of recent projects: [{path, name, branch, last_used}, ...]."""
    try:
        if RECENT_PROJECTS_FILE.exists():
            data = json.loads(RECENT_PROJECTS_FILE.read_text())
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_recent_projects(projects: list[dict]) -> None:
    RECENT_PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECENT_PROJECTS_FILE.write_text(json.dumps(projects, ensure_ascii=False, indent=2))


def _add_recent_project(project_path: str, branch: str = "") -> None:
    projects = _load_recent_projects()
    # Remove if already exists
    projects = [p for p in projects if p.get("path") != project_path]
    # Add to front
    projects.insert(0, {
        "path": project_path,
        "name": Path(project_path).name,
        "branch": branch,
        "last_used": time.strftime("%Y-%m-%d %H:%M"),
    })
    # Limit
    projects = projects[:MAX_RECENT_PROJECTS]
    _save_recent_projects(projects)


@app.get("/projects/recent")
async def get_recent_projects():
    """Return the list of recently used project directories."""
    return {"projects": _load_recent_projects()}


@app.delete("/projects/recent")
async def remove_recent_project(path: str = Query(default="")):
    """Remove a project from the recent list and delete its RAG collection."""
    if not path:
        raise HTTPException(status_code=400, detail="path parameter is required")
    projects = _load_recent_projects()
    projects = [p for p in projects if p.get("path") != path]
    _save_recent_projects(projects)

    # Delete RAG collection for this project
    deleted_chunks = 0
    if rag_store:
        deleted_chunks = rag_store.delete_project(path)
        # If we deleted the current project, switch to home
        if rag_store.project_path == str(Path.home()):
            os.environ["PROJECT_ROOT"] = str(Path.home())

    return {"status": "ok", "projects": projects, "rag_deleted": deleted_chunks}


# ── Local Chat (Ollama + llama.cpp) ────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434"
LLAMACPP_SERVER_URL = "http://localhost:8080"
LLAMACPP_MODELS_DIR = Path("/Users/yaroslav/develop/ai-assist/llama.cpp/models")
DEFAULT_LOCAL_MODEL = "ollama:llama3.2:3b"

# user_id → list of messages
local_chat_history: dict[str, list[dict]] = {}
# user_id → model_id (e.g. "ollama:llama3.2:3b" or "llamacpp:qwen2.5-1.5b-instruct-q4_k_m")
user_local_models: dict[str, str] = {}

# ── Default local params ────────────────────────────────────────────────
DEFAULT_LOCAL_PARAMS = {
    "temperature": 0.8,
    "max_tokens": 2048,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "num_ctx": 4096,
}

# user_id → dict of params
user_local_params: dict[str, dict] = {}

# ── Prompt Templates ────────────────────────────────────────────────────
PROMPT_TEMPLATES = {
    "rag_assistant": {
        "label": "RAG-ассистент",
        "description": "По умолчанию: полезный ассистент с поддержкой контекста документов",
        "prompt": (
            "Ты — полезный AI-ассистент. Отвечай на вопросы пользователя, опираясь на "
            "предоставленный контекст, если он есть. Будь ясным, кратким и указывай источники, "
            "когда используешь найденную информацию. Если не знаешь ответа — скажи честно."
        ),
    },
    "code_review": {
        "label": "Код-ревью",
        "description": "Экспертная проверка кода: баги, производительность, безопасность",
        "prompt": (
            "Ты — эксперт по код-ревью. Анализируй код на наличие багов, проблем с производительностью, "
            "уязвимостей безопасности и стилистических ошибок. Предлагай конкретные улучшения. "
            "Будь тщательным, но конструктивным в своих замечаниях."
        ),
    },
    "creative_writing": {
        "label": "Креативное письмо",
        "description": "Выразительный и образный стиль, помощь с историями и текстами",
        "prompt": (
            "Ты — ассистент по креативному письму. Помогай с рассказами, стихами, диалогами "
            "и другим творческим контентом. Будь изобретательным и описательным. Используй "
            "богатый язык и разнообразные структуры предложений."
        ),
    },
    "concise": {
        "label": "Лаконичный",
        "description": "Краткие, прямые ответы без лишних слов",
        "prompt": (
            "Ты — лаконичный ассистент. Отвечай максимально кратко, но по делу. "
            "Используй маркированные списки, когда это уместно. Избегай воды и лишних пояснений."
        ),
    },
    "custom": {
        "label": "Свой шаблон",
        "description": "Пользователь пишет системный промпт самостоятельно",
        "prompt": "",
    },
}

# user_id → template key (e.g. "rag_assistant")
user_local_prompt_template: dict[str, str] = {}
# user_id → custom system prompt text (used when template is "custom")
user_local_system_prompt: dict[str, str] = {}


class LocalChatResponse(BaseModel):
    response: str
    history: list[dict]
    model: str
    model_label: str
    elapsed_ms: int
    rag_sources: list[dict] = []
    rag_no_context: bool = False


class LocalModelSelectRequest(BaseModel):
    model_id: str


class LocalParamsRequest(BaseModel):
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    repeat_penalty: float | None = None
    num_ctx: int | None = None


class LocalPromptTemplateRequest(BaseModel):
    template_key: str
    custom_prompt: str = ""


# ── Quantization helpers ──────────────────────────────────────────────

import re as _re

_QUANT_PATTERN = _re.compile(
    r'(q[2-8]_[0-9a-z_]+|f16|fp16|bf16)',
    _re.IGNORECASE,
)


def _parse_quantization(filename: str) -> str | None:
    """Extract quantization level from a GGUF filename (e.g. 'q4_k_m' from 'model-q4_k_m.gguf')."""
    match = _QUANT_PATTERN.search(filename.lower())
    return match.group(0).upper() if match else None


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
        base_name = (
            name.removesuffix(".gguf").rsplit("-", 1)[0]
            if "-" in name.removesuffix(".gguf")
            else name.removesuffix(".gguf")
        )
        models.append({
            "id": f"llamacpp:{name}",
            "label": f"{label} (llama.cpp)",
            "provider": "llamacpp",
            "model_name": name,
            "file_path": str(f),
            "quantization": _parse_quantization(name),
            "base_name": base_name,
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


# ── Local params ─────────────────────────────────────────────────────

@app.get("/chat/local/params")
async def get_local_params(user_id: str = Query(default="default")):
    params = user_local_params.get(user_id, dict(DEFAULT_LOCAL_PARAMS))
    return {"params": params, "user_id": user_id}


@app.post("/chat/local/params")
async def set_local_params(request: LocalParamsRequest, user_id: str = Query(default="default")):
    current = user_local_params.get(user_id, dict(DEFAULT_LOCAL_PARAMS))
    for field in ("temperature", "max_tokens", "top_p", "top_k", "repeat_penalty", "num_ctx"):
        val = getattr(request, field, None)
        if val is not None:
            current[field] = val
    user_local_params[user_id] = current
    return {"params": current, "user_id": user_id}


# ── Local prompt templates ───────────────────────────────────────────

@app.get("/chat/local/templates")
async def list_local_templates():
    """Return available prompt template presets."""
    templates = {
        key: {"label": t["label"], "description": t["description"], "prompt": t["prompt"]}
        for key, t in PROMPT_TEMPLATES.items()
    }
    return {"templates": templates, "default": "rag_assistant"}


@app.get("/chat/local/prompt-template")
async def get_local_prompt_template(user_id: str = Query(default="default")):
    template_key = user_local_prompt_template.get(user_id, "rag_assistant")
    custom_prompt = user_local_system_prompt.get(user_id, "")
    template_def = PROMPT_TEMPLATES.get(template_key, PROMPT_TEMPLATES["rag_assistant"])
    return {
        "template_key": template_key,
        "prompt": template_def["prompt"] if template_key != "custom" else custom_prompt,
        "custom_prompt": custom_prompt,
        "user_id": user_id,
    }


@app.post("/chat/local/prompt-template")
async def set_local_prompt_template(request: LocalPromptTemplateRequest, user_id: str = Query(default="default")):
    if request.template_key not in PROMPT_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Unknown template: {request.template_key}")
    user_local_prompt_template[user_id] = request.template_key
    if request.template_key == "custom":
        user_local_system_prompt[user_id] = request.custom_prompt
    return {"template_key": request.template_key, "user_id": user_id}


# ── Model detail (quantization info) ──────────────────────────────────

# Simple cache for Ollama model details (model_name → detail dict, 60s TTL)
_model_detail_cache: dict[str, tuple[dict, float]] = {}


@app.get("/chat/local/model-detail")
async def get_local_model_detail(model_id: str = Query(...)):
    """Return detailed info about a local model, including quantization level."""
    import time as _time
    if model_id.startswith("ollama:"):
        name = model_id[len("ollama:"):]
        # Check cache
        cached = _model_detail_cache.get(name)
        if cached and _time.monotonic() - cached[1] < 60:
            return cached[0]
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(f"{OLLAMA_URL}/api/show", json={"name": name})
                if resp.status_code == 200:
                    data = resp.json()
                    details = data.get("details", {})
                    result = {
                        "provider": "ollama",
                        "model_name": name,
                        "quantization": details.get("quantization_level") or None,
                        "parameter_size": details.get("parameter_size", ""),
                        "family": details.get("family", ""),
                    }
                    _model_detail_cache[name] = (result, _time.monotonic())
                    return result
        except Exception:
            pass
        return {"provider": "ollama", "model_name": name, "quantization": None}
    elif model_id.startswith("llamacpp:"):
        name = model_id[len("llamacpp:"):]
        quant = _parse_quantization(name)
        return {
            "provider": "llamacpp",
            "model_name": name,
            "quantization": quant or None,
            "parameter_size": "",
            "family": "",
        }
    raise HTTPException(status_code=400, detail=f"Unknown model: {model_id}")


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

    # ── RAG retrieval (same pipeline as ChatAgent) ──────────────────────────
    rag_sources: list[dict] = []
    rag_no_context = False
    if rag_store:
        try:
            search_query = rewrite_query(request.text, strategy="none")
            raw_results = await rag_store.retrieve(search_query, top_k=35)

            # Keyword supplement for quoted phrases
            import re as _re
            kw_terms: list[str] = []
            for m in _re.finditer(r'[«"]([^»"]+)[»"]', request.text):
                phrase = m.group(1).strip()
                if len(phrase) >= 3:
                    kw_terms.append(phrase)
            if kw_terms:
                kw_results = rag_store.retrieve_by_keywords(kw_terms, top_k=10)
                if kw_results:
                    extra_chunks: list[dict] = []
                    for kr in kw_results:
                        doc_id = kr.get("doc_id", "")
                        ci = kr.get("chunk_index", -1)
                        if doc_id and ci >= 0:
                            for offset in (1, 2, 3, -1):
                                neighbor = rag_store.get_chunk_by_doc_index(doc_id, ci + offset)
                                if neighbor:
                                    neighbor["score"] = kr["score"] - 0.02 * abs(offset)
                                    extra_chunks.append(neighbor)
                    seen = {r.get("chunk_id", "") for r in raw_results}
                    pinned_kw: list[dict] = []
                    for kr in kw_results + extra_chunks:
                        cid = kr.get("chunk_id", "")
                        if cid and cid not in seen:
                            kr["_pinned"] = True
                            pinned_kw.append(kr)
                            seen.add(cid)
                    raw_results = pinned_kw + raw_results
                    raw_results.sort(key=lambda r: r["score"], reverse=True)

            rerank = rerank_results(
                raw_results, pre_k=30, post_k=10, threshold=0.25,
                query=request.text,
            )
            final_results = rerank["results"]
            pinned_ids = {r.get("chunk_id") for r in final_results}
            for r in raw_results:
                if r.get("_pinned") and r.get("chunk_id") not in pinned_ids:
                    final_results.append(r)
            rag_sources = final_results
            if not rag_sources and rerank["before_count"] > 0:
                rag_no_context = True
        except Exception as exc:
            logging.getLogger(__name__).warning("[local-rag] RAG retrieval failed: %s", exc)

    # ── Build messages: system prompt → RAG context → history ──────────
    messages: list[dict] = []

    # 1. User's system prompt (from template or custom)
    template_key = user_local_prompt_template.get(request.user_id, "rag_assistant")
    template_def = PROMPT_TEMPLATES.get(template_key, PROMPT_TEMPLATES["rag_assistant"])
    user_system_prompt = template_def["prompt"]
    if template_key == "custom":
        user_system_prompt = user_local_system_prompt.get(request.user_id, "")
    if user_system_prompt:
        messages.append({"role": "system", "content": user_system_prompt})

    # 2. RAG context
    if rag_no_context and rag_store:
        messages.append({"role": "system", "content": rag_store.build_no_context_instructions()})
    elif rag_sources and rag_store:
        rag_block = rag_store.build_context_block(rag_sources)
        if rag_block:
            messages.append({"role": "system", "content": rag_block})
            # Simpler instruction for local models (they may struggle with complex formats)
            messages.append({"role": "system", "content": (
                "[RAG INSTRUCTIONS]\n"
                "Answer the user's question using the retrieved context above. "
                "Cite specific sources when possible. "
                "If the context does not contain enough information, say so honestly."
            )})

    # 3. History
    messages.extend(history)

    # ── Apply user-specified params ──────────────────────────────────────
    params = user_local_params.get(request.user_id, dict(DEFAULT_LOCAL_PARAMS))

    if provider == "ollama":
        reply = await _chat_ollama(messages, model_name, params)
    elif provider == "llamacpp":
        reply = await _chat_llamacpp(messages, model_name, params)
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
        rag_sources=rag_sources,
        rag_no_context=rag_no_context,
    )


async def _chat_ollama(messages: list[dict], model_name: str, params: dict | None = None) -> str:
    """Send messages to Ollama chat API with optional generation parameters."""
    payload_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    body: dict = {
        "model": model_name,
        "messages": payload_messages,
        "stream": False,
    }
    if params:
        options: dict = {}
        if params.get("temperature") is not None:
            options["temperature"] = params["temperature"]
        if params.get("max_tokens") is not None:
            options["num_predict"] = params["max_tokens"]
        if params.get("top_p") is not None:
            options["top_p"] = params["top_p"]
        if params.get("top_k") is not None:
            options["top_k"] = params["top_k"]
        if params.get("repeat_penalty") is not None:
            options["repeat_penalty"] = params["repeat_penalty"]
        if params.get("num_ctx") is not None:
            options["num_ctx"] = params["num_ctx"]
        if options:
            body["options"] = options

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(3):
            try:
                resp = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json=body,
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


async def _chat_llamacpp(messages: list[dict], model_name: str, params: dict | None = None) -> str:
    """Send messages to llama.cpp server via OpenAI-compatible API with optional parameters."""
    payload_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    body: dict = {
        "model": model_name,
        "messages": payload_messages,
    }
    if params:
        if params.get("temperature") is not None:
            body["temperature"] = params["temperature"]
        if params.get("max_tokens") is not None:
            body["max_tokens"] = params["max_tokens"]
        if params.get("top_p") is not None:
            body["top_p"] = params["top_p"]
        # top_k is not in the standard OpenAI-compatible API — skip
        if params.get("repeat_penalty") is not None:
            # Map repeat_penalty (1.0=none to 2.0=max) to frequency_penalty/presence_penalty
            rp = params["repeat_penalty"]
            body["frequency_penalty"] = max(0.0, min(2.0, (rp - 1.0) * 2.0))
            body["presence_penalty"] = max(0.0, min(2.0, (rp - 1.0) * 1.0))
        # num_ctx cannot be set via API for llama.cpp — skip

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(3):
            try:
                resp = await client.post(
                    f"{LLAMACPP_SERVER_URL}/v1/chat/completions",
                    json=body,
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


# ── Remote Chat (llama.cpp server) ──────────────────────────────────────────

REMOTE_LLAMACPP_URL = "http://195.58.153.66:8080"

# user_id → list of messages
remote_chat_history: dict[str, list[dict]] = {}


class RemoteChatResponse(BaseModel):
    response: str
    history: list[dict]
    model: str
    elapsed_ms: int
    server_available: bool
    error: str = ""


@app.get("/chat/remote/health")
async def remote_health():
    """Check if remote llama.cpp server is reachable and return diagnostics."""
    result = {
        "url": REMOTE_LLAMACPP_URL,
        "available": False,
        "models": [],
        "error": "",
        "latency_ms": 0,
    }
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{REMOTE_LLAMACPP_URL}/v1/models")
            resp.raise_for_status()
            data = resp.json()
            result["latency_ms"] = round((time.monotonic() - t0) * 1000)
            result["available"] = True
            result["models"] = [
                {
                    "id": m.get("id", ""),
                    "parameter_size": m.get("meta", {}).get("n_params", 0),
                    "context_size": m.get("meta", {}).get("n_ctx", 0),
                }
                for m in data.get("data", [])
            ]
    except Exception as e:
        result["error"] = str(e)
    return result


@app.get("/chat/remote/models")
async def remote_models():
    """List models available on the remote server."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{REMOTE_LLAMACPP_URL}/v1/models")
        resp.raise_for_status()
        return resp.json()


@app.post("/chat/remote")
async def chat_remote(request: MessageRequest):
    """SSE-streamed chat with remote llama.cpp server."""
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    t0 = time.monotonic()
    user_id = request.user_id

    if user_id not in remote_chat_history:
        remote_chat_history[user_id] = []

    history = remote_chat_history[user_id]
    history.append({"role": "user", "content": request.text})

    # Build messages payload
    messages = [{"role": m["role"], "content": m["content"]} for m in history]

    # Fetch model name once before streaming
    model_name = "remote-llamacpp"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{REMOTE_LLAMACPP_URL}/v1/models")
            data = resp.json()
            model_name = data.get("data", [{}])[0].get("id", "remote-llamacpp")
    except Exception:
        pass

    async def event_gen():
        full_reply = ""
        server_available = True
        error_msg = ""

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
                async with client.stream(
                    "POST",
                    f"{REMOTE_LLAMACPP_URL}/v1/chat/completions",
                    json={
                        "messages": messages,
                        "max_tokens": 1024,
                        "temperature": 0.7,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]  # strip "data: " prefix
                        if payload == "[DONE]":
                            break

                        try:
                            chunk = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue

                        delta = choices[0].get("delta", {})
                        finish = choices[0].get("finish_reason")

                        if finish:
                            break  # end of stream

                        # Qwen3 reasoning models use reasoning_content, not content
                        token = delta.get("content") or delta.get("reasoning_content") or ""
                        if token:
                            full_reply += token
                            event = {"token": token, "done": False}
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        except Exception as e:
            server_available = False
            error_msg = str(e)
            full_reply = f"[ERROR] Remote server unavailable: {e}"
            event = {"token": full_reply, "done": True, "server_available": False, "error": error_msg}
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            return

        # Save full reply to history
        if full_reply:
            history.append({"role": "assistant", "content": full_reply})

        elapsed_ms = round((time.monotonic() - t0) * 1000)
        event = {
            "token": "",
            "done": True,
            "model": model_name,
            "elapsed_ms": elapsed_ms,
            "server_available": server_available,
        }
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/chat/remote/history")
async def get_remote_history(user_id: str = Query(default="default")):
    return {"history": remote_chat_history.get(user_id, []), "user_id": user_id}


@app.delete("/chat/remote/history")
async def clear_remote_history(user_id: str = Query(default="default")):
    remote_chat_history.pop(user_id, None)
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


# ── Code Review ────────────────────────────────────────────────────────────────

@app.get("/review/status")
async def review_status():
    """Проверить доступность сервиса ревью кода."""
    if not review_agent:
        return {"available": False, "error": "CodeReviewAgent not initialized"}
    git_available = mcp_client is not None
    rag_available = rag_store is not None and rag_store.count() > 0

    # Get current branch name and all branches
    current_branch = None
    all_branches = []
    if mcp_client:
        try:
            branch_json = await mcp_client.call_tool("get_git_branch", {})
            branch_data = json.loads(branch_json)
            current_branch = branch_data.get("current_branch")
            all_branches = branch_data.get("all_branches", [])
        except Exception:
            pass

    return {
        "available": True,
        "git_available": git_available,
        "rag_available": rag_available,
        "rag_chunks": rag_store.count() if rag_store else 0,
        "model": review_agent.model,
        "current_branch": current_branch,
        "all_branches": all_branches,
    }


@app.post("/review/pr", response_model=PRReviewResponse)
async def review_pr(request: PRReviewRequest):
    """Ревью PR по переданному diff с использованием RAG-контекста."""
    if not review_agent:
        raise HTTPException(status_code=503, detail="Code review agent unavailable")
    if not request.diff_text.strip():
        raise HTTPException(status_code=400, detail="diff_text is required")

    t0 = time.monotonic()
    try:
        result = await review_agent.review_pr(
            pr_title=request.pr_title,
            pr_description=request.pr_description,
            base_branch=request.base_branch,
            head_branch=request.head_branch,
            diff_text=request.diff_text,
            changed_files=request.changed_files,
            user_id=request.user_id,
        )
    except Exception as e:
        logger.exception("Code review failed")
        raise HTTPException(status_code=500, detail=str(e))

    elapsed_ms = round((time.monotonic() - t0) * 1000)

    return PRReviewResponse(
        result=result.to_dict(),
        summary=result.summary,
        rag_sources=result.rag_sources,
        error=result.error,
        elapsed_ms=result.elapsed_ms,
    )


@app.post("/review/local", response_model=PRReviewResponse)
async def review_local(request: LocalReviewRequest):
    """Ревью текущего рабочего дерева через MCP-инструменты git."""
    if not review_agent:
        raise HTTPException(status_code=503, detail="Code review agent unavailable")

    t0 = time.monotonic()
    try:
        result = await review_agent.review_current_branch(
            base_branch=request.base_branch,
            user_id=request.user_id,
        )
    except Exception as e:
        logger.exception("Local code review failed")
        raise HTTPException(status_code=500, detail=str(e))

    return PRReviewResponse(
        result=result.to_dict(),
        summary=result.summary,
        rag_sources=result.rag_sources,
        error=result.error,
        elapsed_ms=result.elapsed_ms,
    )


# ── File Assistant Agent ───────────────────────────────────────────────────────


class FileQueryRequest(BaseModel):
    task: str
    session_id: str = "default"


class FileQueryResponse(BaseModel):
    answer: str = ""
    files_affected: list[str] = []
    usage: dict = {}
    elapsed_ms: int = 0
    error: str = ""


# ── File Assistant Agent ───────────────────────────────────────────────────────


@app.get("/file/status")
async def file_status():
    """Check FileAssistant availability and MCP tool readiness."""
    if not file_assistant:
        return {"available": False, "error": "FileAssistant not initialized"}
    mcp_ok = file_assistant.mcp_client is not None
    tool_count = len(file_assistant.mcp_client.tools) if mcp_ok else 0
    return {
        "available": True,
        "mcp_available": mcp_ok,
        "tool_count": tool_count,
        "model": file_assistant.model,
    }


@app.post("/file/query", response_model=FileQueryResponse)
async def file_query(request: FileQueryRequest):
    """Execute a file-related task using the File Assistant agent.

    The agent will proactively use tools like search_content, read_file,
    and write_file to complete the task. It may touch multiple files.
    """
    if not file_assistant:
        raise HTTPException(status_code=503, detail="FileAssistant unavailable")
    if not request.task.strip():
        raise HTTPException(status_code=400, detail="task is required")

    try:
        result = await file_assistant.execute(
            task=request.task,
            session_id=request.session_id,
        )
    except Exception as e:
        logger.exception("FileAssistant failed")
        raise HTTPException(status_code=500, detail=str(e))

    return FileQueryResponse(
        answer=result["answer"],
        files_affected=result.get("files_affected", []),
        usage=result.get("usage", {}),
        elapsed_ms=result.get("elapsed_ms", 0),
        error=result.get("error", ""),
    )


@app.post("/file/query/stream")
async def file_query_stream(request: FileQueryRequest):
    """SSE-streamed file task — tokens arrive as the LLM generates them."""
    if not file_assistant:
        raise HTTPException(status_code=503, detail="FileAssistant unavailable")
    if not request.task.strip():
        raise HTTPException(status_code=400, detail="task is required")

    async def event_gen():
        async for event in file_assistant.execute_stream(
            task=request.task,
            session_id=request.session_id,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ── Support Agent ──────────────────────────────────────────────────────────────


class SupportQuestionRequest(BaseModel):
    question: str
    user_identifier: str = ""  # имя, email или id пользователя
    ticket_id: str = ""        # конкретный тикет
    session_id: str = "default"  # id сессии для истории диалога


class SupportQuestionResponse(BaseModel):
    answer: str
    user_context: dict | None = None
    ticket: dict | None = None
    rag_sources: list[dict] = []
    rag_no_context: bool = False
    usage: dict = {}
    elapsed_ms: int = 0
    error: str = ""
    ticket_closed: bool = False


@app.post("/support/chat", response_model=SupportQuestionResponse)
async def support_chat(request: SupportQuestionRequest):
    """Задать вопрос ассистенту поддержки с учётом CRM и FAQ."""
    if not support_agent:
        raise HTTPException(status_code=503, detail="Support agent unavailable")
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        result = await support_agent.answer_question(
            question=request.question,
            user_identifier=request.user_identifier,
            ticket_id=request.ticket_id,
            session_id=request.session_id,
        )
    except Exception as e:
        logger.exception("Support agent failed")
        raise HTTPException(status_code=500, detail=str(e))

    return SupportQuestionResponse(
        answer=result["answer"],
        user_context=result.get("user_context"),
        ticket=result.get("ticket"),
        rag_sources=result.get("rag_sources", []),
        rag_no_context=result.get("rag_no_context", False),
        usage=result.get("usage", {}),
        elapsed_ms=result.get("elapsed_ms", 0),
        ticket_closed=result.get("ticket_closed", False),
    )


@app.get("/support/status")
async def support_status():
    """Проверить состояние support-ассистента: CRM, RAG, FAQ."""
    crm_available = crm_client is not None and crm_client._session is not None
    rag_available = rag_store is not None and rag_store.count() > 0

    # Подсчитать FAQ-документы в docs/support/
    support_docs = []
    support_dir = Path("docs/support")
    if support_dir.exists():
        for f in support_dir.rglob("*"):
            if f.is_file() and f.suffix in (".md", ".txt"):
                support_docs.append(str(f))

    return {
        "available": support_agent is not None,
        "crm_available": crm_available,
        "rag_available": rag_available,
        "rag_chunks": rag_store.count() if rag_store else 0,
        "faq_documents": len(support_docs),
        "faq_files": support_docs,
    }


class SupportSearchUsersRequest(BaseModel):
    query: str


@app.post("/support/users/search")
async def support_search_users(request: SupportSearchUsersRequest):
    """Поиск пользователей в CRM."""
    if not crm_client:
        raise HTTPException(status_code=503, detail="CRM client unavailable")
    try:
        result_json = await crm_client.call_tool("search_users", {"query": request.query.strip()})
        result = json.loads(result_json)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/support/users/{user_id}")
async def support_get_user(user_id: str):
    """Получить профиль пользователя из CRM."""
    if not crm_client:
        raise HTTPException(status_code=503, detail="CRM client unavailable")
    try:
        result_json = await crm_client.call_tool("get_user", {"user_id": user_id})
        return json.loads(result_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/support/users/{user_id}/tickets")
async def support_get_user_tickets(user_id: str, status: str = Query(default="")):
    """Получить тикеты пользователя из CRM."""
    if not crm_client:
        raise HTTPException(status_code=503, detail="CRM client unavailable")
    try:
        args = {"user_id": user_id}
        if status:
            args["status"] = status
        result_json = await crm_client.call_tool("get_user_tickets", args)
        return json.loads(result_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/support/tickets/{ticket_id}")
async def support_get_ticket(ticket_id: str):
    """Получить тикет по id из CRM."""
    if not crm_client:
        raise HTTPException(status_code=503, detail="CRM client unavailable")
    try:
        result_json = await crm_client.call_tool("get_ticket", {"ticket_id": ticket_id})
        return json.loads(result_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UpdateTicketRequest(BaseModel):
    status: str = ""       # новый статус
    message: str = ""      # сообщение в тикет
    message_role: str = "support"


@app.patch("/support/tickets/{ticket_id}")
async def support_update_ticket(ticket_id: str, request: UpdateTicketRequest):
    """Обновить статус тикета или добавить сообщение."""
    if not crm_client:
        raise HTTPException(status_code=503, detail="CRM client unavailable")
    try:
        args = {"ticket_id": ticket_id}
        if request.status:
            args["status"] = request.status
        if request.message:
            args["message"] = request.message
            args["message_role"] = request.message_role
        result_json = await crm_client.call_tool("update_ticket", args)
        return json.loads(result_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CreateTicketRequest(BaseModel):
    user_id: str
    subject: str
    description: str
    priority: str = "medium"
    category: str = "other"


@app.post("/support/tickets", status_code=201)
async def support_create_ticket(request: CreateTicketRequest):
    """Создать новый тикет в CRM."""
    if not crm_client:
        raise HTTPException(status_code=503, detail="CRM client unavailable")
    if not request.subject.strip() or not request.description.strip():
        raise HTTPException(status_code=400, detail="subject and description are required")
    try:
        result_json = await crm_client.call_tool("create_ticket", {
            "user_id": request.user_id,
            "subject": request.subject,
            "description": request.description,
            "priority": request.priority,
            "category": request.category,
        })
        return json.loads(result_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/support/tickets")
async def support_list_tickets(status: str = Query(default="")):
    """Список всех тикетов (с фильтром по статусу)."""
    if not crm_client:
        raise HTTPException(status_code=503, detail="CRM client unavailable")
    try:
        # Use search with empty query to get all, then filter by status
        result_json = await crm_client.call_tool("search_tickets", {"query": "", "status": status} if status else {"query": ""})
        return json.loads(result_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── RAG ───────────────────────────────────────────────────────────────────────

class RAGDocumentRequest(BaseModel):
    text: str
    source: str = ""
    strategy: str = "fixed"
    format: str = "auto"  # "auto" | "text" | "html" | "mhtml"


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
    fmt = request.format if request.format in ("auto", "text", "html", "mhtml") else "auto"

    async def event_gen():
        src = request.source or "документ"
        activity.set_current(f"Индексация: {src}...", agent="system")
        try:
            async for event in rag_store.add_document_stream(
                request.text, source=request.source, strategy=strategy, format=fmt
            ):
                if event.get("type") == "done":
                    activity.emit("rag_index",
                                  f"Проиндексирован: {event.get('source') or src} ({event.get('chunks', 0)} чанков)",
                                  agent="system",
                                  detail={"source": event.get("source") or src,
                                          "chunks": event.get("chunks", 0)})
                elif event.get("type") == "error":
                    activity.emit("rag_index", f"Ошибка индексации: {src}", agent="system",
                                  detail={"source": src, "error": event.get("message", "")})
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            activity.clear_current()

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/rag/documents", status_code=201)
async def add_rag_document(request: RAGDocumentRequest):
    if not rag_store:
        raise HTTPException(status_code=503, detail="RAG store unavailable (Ollama not running?)")
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Document text cannot be empty")
    strategy = request.strategy if request.strategy in ("fixed", "structural") else "fixed"
    fmt = request.format if request.format in ("auto", "text", "html", "mhtml") else "auto"
    result = await rag_store.add_document(request.text, source=request.source,
                                          strategy=strategy, format=fmt)
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