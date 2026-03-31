import json
import time
import httpx
from pathlib import Path
from typing import Optional

from memory import MemoryStore


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
        self.memory = MemoryStore()

    async def send_message(self, user_message: str) -> tuple[str, dict]:
        command_response = self._handle_command(user_message)
        if command_response is not None:
            self.history.append({"role": "user", "content": user_message})
            self.history.append({"role": "assistant", "content": command_response})
            self._save_history()
            return command_response, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "response_time_ms": 0}

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
        memory_context = self.memory.build_context_block()
        if memory_context:
            messages.append({"role": "system", "content": memory_context})
        if self.summary:
            messages.append({"role": "system", "content": f"Summary of earlier conversation:\n{self.summary}"})
        messages.extend(self.history)
        return messages

    def _handle_command(self, message: str) -> Optional[str]:
        """Parse a /command message. Returns response text or None if not a command."""
        stripped = message.strip()
        if not stripped.startswith("/"):
            return None

        parts = stripped.split(None, 1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/memory":
            return self._format_memory_snapshot()

        if cmd == "/task":
            if not args:
                return "Usage: /task <description>"
            self.memory.set_task(args)
            return f"Task started: {args}"

        if cmd == "/task-done":
            w = self.memory.get_working()
            task = w.get("task") or "(no active task)"
            self.memory.clear_working()
            return f"Task completed and cleared: {task}"

        if cmd == "/fact":
            if ": " not in args:
                return "Usage: /fact <key>: <value>"
            key, _, value = args.partition(": ")
            self.memory.add_working_fact(key.strip(), value.strip())
            return f"Working memory: saved fact [{key.strip()}]"

        if cmd == "/remember":
            if ": " not in args:
                return "Usage: /remember <key>: <value>"
            key, _, value = args.partition(": ")
            self.memory.add_long_term("knowledge", key.strip(), value.strip())
            return f"Long-term knowledge: saved [{key.strip()}]"

        if cmd == "/profile":
            if ": " not in args:
                return "Usage: /profile <key>: <value>"
            key, _, value = args.partition(": ")
            self.memory.add_long_term("profile", key.strip(), value.strip())
            return f"Profile: saved [{key.strip()}]"

        if cmd == "/decide":
            if ": " not in args:
                return "Usage: /decide <key>: <value>"
            key, _, value = args.partition(": ")
            self.memory.add_long_term("decisions", key.strip(), value.strip())
            return f"Decisions: saved [{key.strip()}]"

        if cmd == "/forget":
            forget_parts = args.split(None, 1)
            if len(forget_parts) < 2:
                return "Usage: /forget <knowledge|profile|decisions> <key>"
            category, key = forget_parts[0].lower(), forget_parts[1].strip()
            if category not in ("knowledge", "profile", "decisions"):
                return f"Unknown category '{category}'. Use: knowledge, profile, decisions"
            deleted = self.memory.delete_long_term(category, key)  # type: ignore[arg-type]
            return f"Deleted [{key}] from {category}." if deleted else f"Key [{key}] not found in {category}."

        if cmd == "/help":
            return (
                "Memory commands:\n"
                "  /task <desc>              — start a working task\n"
                "  /task-done                — complete and clear current task\n"
                "  /fact <key>: <value>      — add fact to working memory\n"
                "  /remember <key>: <value>  — save to long-term knowledge\n"
                "  /profile <key>: <value>   — save to user profile\n"
                "  /decide <key>: <value>    — save to decisions\n"
                "  /forget <cat> <key>       — delete from long-term memory\n"
                "  /memory                   — show all memory levels"
            )

        return None  # unknown command — let the LLM handle it

    def _format_memory_snapshot(self) -> str:
        snap = self.memory.snapshot()
        lines = ["=== Memory snapshot ===\n"]

        w = snap["working"]
        lines.append("[ Working memory ]")
        if w["task"]:
            lines.append(f"  Task: {w['task']}  (started: {w['started_at']})")
            for f in w["facts"]:
                lines.append(f"  • {f['key']}: {f['value']}")
        else:
            lines.append("  (empty)")

        for category, label in [("profile", "Profile"), ("decisions", "Decisions"), ("knowledge", "Knowledge")]:
            entries = snap["long_term"][category]
            lines.append(f"\n[ {label} ]")
            if entries:
                for e in entries:
                    lines.append(f"  • {e['key']}: {e['value']}")
            else:
                lines.append("  (empty)")

        return "\n".join(lines)

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
