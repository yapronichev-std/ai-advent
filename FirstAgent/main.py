import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent import ChatAgent, ContextStrategy

load_dotenv()

MODEL = "arcee-ai/trinity-mini:free"
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


# ── Request / Response models ──────────────────────────────────────────────


class MessageRequest(BaseModel):
    text: str


class MessageResponse(BaseModel):
    response: str
    history: list[dict]
    usage: dict


class StrategyRequest(BaseModel):
    strategy: str
    window_size: Optional[int] = None


class SwitchBranchRequest(BaseModel):
    branch_id: str


# ── Core routes ────────────────────────────────────────────────────────────


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.post("/chat", response_model=MessageResponse)
async def chat(request: MessageRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    response_text, usage = await agent.send_message(request.text)
    return MessageResponse(
        response=response_text, history=agent.get_history(), usage=usage
    )


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


# ── Strategy routes ────────────────────────────────────────────────────────


@app.get("/strategy")
async def get_strategy():
    return agent.get_strategy_info()


@app.post("/strategy")
async def set_strategy(request: StrategyRequest):
    try:
        strategy = ContextStrategy(request.strategy)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {request.strategy}")
    agent.set_strategy(strategy, request.window_size)
    return agent.get_strategy_info()


# ── Sticky Facts routes ────────────────────────────────────────────────────


@app.get("/facts")
async def get_facts():
    return {"facts": agent.get_facts()}


# ── Branching routes ───────────────────────────────────────────────────────


@app.get("/branches")
async def get_branches():
    return {"branches": agent.get_branches()}


@app.post("/checkpoint")
async def create_checkpoint():
    branch_a_id, branch_b_id = agent.create_checkpoint()
    return {
        "branch_a": branch_a_id,
        "branch_b": branch_b_id,
        "branches": agent.get_branches(),
    }


@app.post("/branch/switch")
async def switch_branch(request: SwitchBranchRequest):
    try:
        agent.switch_branch(request.branch_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "active_branch": request.branch_id,
        "history": agent.get_history(),
    }
