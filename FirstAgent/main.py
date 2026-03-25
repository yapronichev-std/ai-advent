import os
from contextlib import asynccontextmanager

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
