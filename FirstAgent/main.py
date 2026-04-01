import os
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent import ChatAgent
from profiles import UserProfileManager

load_dotenv()

MODEL = "arcee-ai/trinity-large-preview:free"
SYSTEM_PROMPT = "You are a helpful assistant. Answer clearly and concisely."

api_key: str
agents: dict[str, ChatAgent] = {}
profile_manager = UserProfileManager()


def get_agent(user_id: str) -> ChatAgent:
    if user_id not in agents:
        agents[user_id] = ChatAgent(api_key=api_key, model=MODEL, system_prompt=SYSTEM_PROMPT, user_id=user_id)
    return agents[user_id]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global api_key
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")
    yield


app = FastAPI(title="Chat Agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Request / Response models ────────────────────────────────────────────────

class MessageRequest(BaseModel):
    text: str
    user_id: str = "default"


class MessageResponse(BaseModel):
    response: str
    history: list[dict]
    usage: dict
    user_id: str


class FactRequest(BaseModel):
    key: str
    value: str


class LongTermRequest(BaseModel):
    key: str
    value: str


class TaskRequest(BaseModel):
    description: str


LongTermCategory = Literal["profile", "decisions", "knowledge"]


# ── Frontend ─────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ── Chat ─────────────────────────────────────────────────────────────────────

@app.post("/chat", response_model=MessageResponse)
async def chat(request: MessageRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    agent = get_agent(request.user_id)
    response_text, usage = await agent.send_message(request.text)
    return MessageResponse(
        response=response_text,
        history=agent.get_history(),
        usage=usage,
        user_id=request.user_id,
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
    # Выгружаем агента из кеша если он был загружен
    agents.pop(user_id, None)
    deleted = profile_manager.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
    return {"status": "ok", "user_id": user_id}