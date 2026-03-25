import json
import httpx
from pathlib import Path
from typing import Optional


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
HISTORY_FILE = Path("history.json")


class ChatAgent:
    def __init__(self, api_key: str, model: str, system_prompt: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.history: list[dict] = self._load_history()

    async def send_message(self, user_message: str) -> tuple[str, dict]:
        self.history.append({"role": "user", "content": user_message})

        messages = self._build_messages()
        response_text, usage = await self._call_api(messages)

        self.history.append({"role": "assistant", "content": response_text})
        self._save_history()
        return response_text, usage

    def get_history(self) -> list[dict]:
        return self.history

    def clear_history(self) -> None:
        self.history = []
        self._save_history()

    def _load_history(self) -> list[dict]:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return []

    def _save_history(self) -> None:
        HISTORY_FILE.write_text(json.dumps(self.history, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_messages(self) -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
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
