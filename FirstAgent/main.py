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
from rag import RAGStore, RAGRetriever, compare_strategies, rewrite_query, rerank_results

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
        async for event in rag_store.add_document_stream(
            request.text, source=request.source, strategy=strategy, format=fmt
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