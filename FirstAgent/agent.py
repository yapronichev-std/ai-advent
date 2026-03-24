import httpx
from typing import Optional


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class ChatAgent:
    def __init__(self, api_key: str, model: str, system_prompt: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.history: list[dict] = []

    async def send_message(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})

        messages = self._build_messages()
        response_text = await self._call_api(messages)

        self.history.append({"role": "assistant", "content": response_text})
        return response_text

    def get_history(self) -> list[dict]:
        return self.history

    def clear_history(self) -> None:
        self.history = []

    def _build_messages(self) -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self.history)
        return messages

    async def _call_api(self, messages: list[dict]) -> str:
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
            return data["choices"][0]["message"]["content"]
