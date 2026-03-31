import os
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent import ChatAgent

load_dotenv()

MODEL = "arcee-ai/trinity-large-preview:free"
SYSTEM_PROMPT = "You are a helpful assistant. Answer clearly and concisely."

agent: ChatAgent


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")
    agent = ChatAgent(api_key=api_key, model=MODEL, system_prompt=SYSTEM_PROMPT)
    yield


app = FastAPI(title="Chat Agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


class MessageRequest(BaseModel):
    text: str


class MessageResponse(BaseModel):
    response: str
    history: list[dict]
    usage: dict


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.post("/chat", response_model=MessageResponse)
async def chat(request: MessageRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    response_text, usage = await agent.send_message(request.text)
    return MessageResponse(response=response_text, history=agent.get_history(), usage=usage)


@app.get("/history")
async def get_history():
    return {"history": agent.get_history()}


@app.delete("/history")
async def clear_history():
    agent.clear_history()
    return {"status": "ok"}


@app.get("/tokens")
async def get_tokens():
    return agent.get_token_stats()


@app.delete("/tokens")
async def reset_tokens():
    agent.reset_tokens()
    return {"status": "ok"}


@app.get("/summary")
async def get_summary():
    return {"summary": agent.get_summary()}


@app.get("/memory/short-term")
async def get_short_term_memory():
    history = agent.get_history()
    return {
        "message_count": len(history),
        "max_history": 10,
        "summary": agent.get_summary(),
    }


# ── Memory endpoints ────────────────────────────────────────────────────────

LongTermCategory = Literal["profile", "decisions", "knowledge"]


class TaskRequest(BaseModel):
    description: str


class FactRequest(BaseModel):
    key: str
    value: str


class LongTermRequest(BaseModel):
    key: str
    value: str


@app.get("/memory")
async def get_memory():
    return agent.memory.snapshot()


@app.get("/memory/working")
async def get_working_memory():
    return agent.memory.get_working()


@app.post("/memory/working/task")
async def set_task(request: TaskRequest):
    agent.memory.set_task(request.description)
    return {"status": "ok", "task": request.description}


@app.post("/memory/working/fact")
async def add_working_fact(request: FactRequest):
    agent.memory.add_working_fact(request.key, request.value)
    return {"status": "ok", "key": request.key}


@app.delete("/memory/working/fact/{key}")
async def delete_working_fact(key: str):
    deleted = agent.memory.delete_working_fact(key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Fact '{key}' not found")
    return {"status": "ok", "key": key}


@app.delete("/memory/working")
async def clear_working_memory():
    agent.memory.clear_working()
    return {"status": "ok"}


@app.get("/memory/long-term/{category}")
async def get_long_term(category: LongTermCategory):
    return {"category": category, "entries": agent.memory.get_long_term(category)}


@app.post("/memory/long-term/{category}")
async def add_long_term(category: LongTermCategory, request: LongTermRequest):
    agent.memory.add_long_term(category, request.key, request.value)
    return {"status": "ok", "category": category, "key": request.key}


@app.delete("/memory/long-term/{category}/{key}")
async def delete_long_term(category: LongTermCategory, key: str):
    deleted = agent.memory.delete_long_term(category, key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found in {category}")
    return {"status": "ok", "category": category, "key": key}
