import json
import time
import httpx
from pathlib import Path
from typing import Optional


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
HISTORY_FILE = Path("history.json")
TOKENS_FILE = Path("tokens.json")
SUMMARY_FILE = Path("summary.json")
DEFAULT_TOKEN_LIMIT = 1_000_000
MAX_HISTORY = 10


class ChatAgent:
    def __init__(self, api_key: str, model: str, system_prompt: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.history: list[dict] = self._load_history()
        self.token_stats: dict = self._load_tokens()
        self.summary: str = self._load_summary()

    async def send_message(self, user_message: str) -> tuple[str, dict]:
        self.history.append({"role": "user", "content": user_message})

        messages = self._build_messages()
        t0 = time.monotonic()
        response_text, usage = await self._call_api(messages)
        usage["response_time_ms"] = round((time.monotonic() - t0) * 1000)

        self.history.append({"role": "assistant", "content": response_text})

        if len(self.history) > MAX_HISTORY:
            await self._compress_history()

        self._save_history()
        self._accumulate_tokens(usage)
        return response_text, usage

    def get_history(self) -> list[dict]:
        return self.history

    def get_summary(self) -> str:
        return self.summary

    def clear_history(self) -> None:
        self.history = []
        self.summary = ""
        self._save_history()
        self._save_summary()

    def get_token_stats(self) -> dict:
        return self.token_stats

    def reset_tokens(self) -> None:
        limit = self.token_stats.get("limit", DEFAULT_TOKEN_LIMIT)
        self.token_stats = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "limit": limit}
        self._save_tokens()

    def _load_history(self) -> list[dict]:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return []

    def _save_history(self) -> None:
        HISTORY_FILE.write_text(json.dumps(self.history, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_summary(self) -> str:
        if SUMMARY_FILE.exists():
            return json.loads(SUMMARY_FILE.read_text(encoding="utf-8")).get("summary", "")
        return ""

    def _save_summary(self) -> None:
        SUMMARY_FILE.write_text(json.dumps({"summary": self.summary}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_tokens(self) -> dict:
        if TOKENS_FILE.exists():
            data = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
            data.setdefault("limit", DEFAULT_TOKEN_LIMIT)
            return data
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "limit": DEFAULT_TOKEN_LIMIT}

    def _save_tokens(self) -> None:
        TOKENS_FILE.write_text(json.dumps(self.token_stats, ensure_ascii=False, indent=2), encoding="utf-8")

    def _accumulate_tokens(self, usage: dict) -> None:
        self.token_stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.token_stats["completion_tokens"] += usage.get("completion_tokens", 0)
        self.token_stats["total_tokens"] += usage.get("total_tokens", 0)
        self._save_tokens()

    async def _compress_history(self) -> None:
        to_summarize = self.history[:-MAX_HISTORY]
        self.history = self.history[-MAX_HISTORY:]

        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in to_summarize
        )
        prompt = f"Summarize the following conversation fragment concisely, preserving key facts, decisions and context:\n\n{conversation_text}"
        summary_messages = [{"role": "user", "content": prompt}]
        new_summary, _ = await self._call_api(summary_messages)

        self.summary = f"{self.summary}\n\n{new_summary}".strip() if self.summary else new_summary
        self._save_summary()

    def _build_messages(self) -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if self.summary:
            messages.append({"role": "system", "content": f"Summary of earlier conversation:\n{self.summary}"})
        messages.extend(self.history)
        return messages

    async def _call_api(self, messages: list[dict]) -> tuple[str, dict]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = client.post(OPENROUTER_URL, headers=headers, json=payload)
            response = await response
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return content, usage
