import json
import re
import time
import uuid
import httpx
from enum import Enum
from pathlib import Path
from typing import Optional


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
STATE_FILE = Path("state.json")
TOKENS_FILE = Path("tokens.json")
DEFAULT_TOKEN_LIMIT = 1_000_000
DEFAULT_WINDOW_SIZE = 10


class ContextStrategy(str, Enum):
    SLIDING_WINDOW = "sliding_window"
    STICKY_FACTS = "sticky_facts"
    BRANCHING = "branching"


class ChatAgent:
    def __init__(self, api_key: str, model: str, system_prompt: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.token_stats: dict = self._load_tokens()
        self._load_state()

    # ── public API ─────────────────────────────────────────────────────────

    async def send_message(self, user_message: str) -> tuple[str, dict]:
        history = self._current_history()
        history.append({"role": "user", "content": user_message})

        if self.strategy == ContextStrategy.STICKY_FACTS:
            await self._update_facts()

        messages = self._build_messages()
        t0 = time.monotonic()
        response_text, usage = await self._call_api(messages)
        usage["response_time_ms"] = round((time.monotonic() - t0) * 1000)

        history.append({"role": "assistant", "content": response_text})
        self._save_state()
        self._accumulate_tokens(usage)
        return response_text, usage

    def get_history(self) -> list[dict]:
        return self._current_history()

    def clear_history(self) -> None:
        if self.strategy == ContextStrategy.BRANCHING:
            self.branches[self.current_branch_id]["history"] = []
        else:
            self.histories[self.strategy.value] = []
            if self.strategy == ContextStrategy.STICKY_FACTS:
                self.facts = {}
        self._save_state()

    def get_token_stats(self) -> dict:
        return self.token_stats

    def reset_tokens(self) -> None:
        limit = self.token_stats.get("limit", DEFAULT_TOKEN_LIMIT)
        self.token_stats = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "limit": limit,
        }
        self._save_tokens()

    def set_strategy(self, strategy: ContextStrategy, window_size: Optional[int] = None) -> None:
        self.strategy = strategy
        if window_size is not None:
            self.window_size = max(1, window_size)
        self._save_state()

    def get_strategy_info(self) -> dict:
        return {"strategy": self.strategy.value, "window_size": self.window_size}

    def get_facts(self) -> dict:
        return self.facts

    # ── branching ──────────────────────────────────────────────────────────

    def create_checkpoint(self) -> tuple[str, str]:
        """Fork current branch into two new branches. Returns (branch_a_id, branch_b_id)."""
        checkpoint = list(self._current_history())
        n = len(self.branches)
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        name_a = f"Branch {letters[n % 26]}"
        name_b = f"Branch {letters[(n + 1) % 26]}"
        branch_a_id = f"branch_{uuid.uuid4().hex[:8]}"
        branch_b_id = f"branch_{uuid.uuid4().hex[:8]}"
        self.branches[branch_a_id] = {
            "id": branch_a_id,
            "name": name_a,
            "history": list(checkpoint),
        }
        self.branches[branch_b_id] = {
            "id": branch_b_id,
            "name": name_b,
            "history": list(checkpoint),
        }
        self.current_branch_id = branch_a_id
        self._save_state()
        return branch_a_id, branch_b_id

    def switch_branch(self, branch_id: str) -> None:
        if branch_id not in self.branches:
            raise ValueError(f"Branch '{branch_id}' not found")
        self.current_branch_id = branch_id
        self._save_state()

    def get_branches(self) -> list[dict]:
        return [
            {
                "id": bid,
                "name": b["name"],
                "message_count": len(b["history"]),
                "active": bid == self.current_branch_id,
            }
            for bid, b in self.branches.items()
        ]

    # ── internal ───────────────────────────────────────────────────────────

    def _current_history(self) -> list[dict]:
        if self.strategy == ContextStrategy.BRANCHING:
            branch = self.branches.get(self.current_branch_id)
            if branch is None:
                self.current_branch_id = next(iter(self.branches))
                branch = self.branches[self.current_branch_id]
            return branch["history"]
        return self.histories[self.strategy.value]

    def _build_messages(self) -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        history = self._current_history()

        if self.strategy == ContextStrategy.SLIDING_WINDOW:
            messages.extend(history[-self.window_size :])

        elif self.strategy == ContextStrategy.STICKY_FACTS:
            if self.facts:
                facts_text = "\n".join(f"- {k}: {v}" for k, v in self.facts.items())
                messages.append(
                    {"role": "system", "content": f"Key facts from the conversation:\n{facts_text}"}
                )
            messages.extend(history[-self.window_size :])

        elif self.strategy == ContextStrategy.BRANCHING:
            messages.extend(history)

        return messages

    async def _update_facts(self) -> None:
        history = self._current_history()
        if not history:
            return
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in history[-10:]
        )
        current_facts_text = (
            json.dumps(self.facts, ensure_ascii=False) if self.facts else "{}"
        )
        prompt = (
            "Extract important facts from this conversation to remember long-term "
            "(goals, preferences, decisions, constraints, agreements, names).\n"
            f"Existing facts (JSON): {current_facts_text}\n"
            f"Conversation:\n{history_text}\n\n"
            "Return ONLY a valid JSON object with string key-value pairs. "
            "Merge and update existing facts. "
            'Example: {"goal": "build a web app", "language": "Python", "user_name": "Alice"}'
        )
        try:
            result, _ = await self._call_api([{"role": "user", "content": prompt}])
            result = result.strip()
            # strip optional markdown code fence
            result = re.sub(r"^```(?:json)?\s*", "", result)
            result = re.sub(r"\s*```\s*$", "", result)
            m = re.search(r"\{.*\}", result, re.DOTALL)
            if m:
                new_facts = json.loads(m.group())
                if isinstance(new_facts, dict):
                    self.facts.update(
                        {str(k): str(v) for k, v in new_facts.items()}
                    )
        except Exception:
            pass  # facts update is best-effort

    async def _call_api(self, messages: list[dict]) -> tuple[str, dict]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "messages": messages}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return content, usage

    # ── persistence ────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        else:
            # migrate from legacy history.json if present
            old_history: list[dict] = []
            old_file = Path("history.json")
            if old_file.exists():
                try:
                    old_history = json.loads(old_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            data = {"history": old_history}

        try:
            self.strategy = ContextStrategy(data.get("strategy", ContextStrategy.SLIDING_WINDOW))
        except ValueError:
            self.strategy = ContextStrategy.SLIDING_WINDOW

        self.window_size = int(data.get("window_size", DEFAULT_WINDOW_SIZE))
        self.histories = {
            ContextStrategy.SLIDING_WINDOW.value: data.get("history_sliding_window", data.get("history", [])),
            ContextStrategy.STICKY_FACTS.value: data.get("history_sticky_facts", []),
        }
        self.facts = data.get("facts", {})
        self.branches = data.get(
            "branches",
            {"main": {"id": "main", "name": "Main", "history": []}},
        )
        self.current_branch_id = data.get("current_branch_id", "main")
        if self.current_branch_id not in self.branches:
            self.current_branch_id = next(iter(self.branches))

    def _save_state(self) -> None:
        data = {
            "strategy": self.strategy.value,
            "window_size": self.window_size,
            "history_sliding_window": self.histories[ContextStrategy.SLIDING_WINDOW.value],
            "history_sticky_facts": self.histories[ContextStrategy.STICKY_FACTS.value],
            "facts": self.facts,
            "branches": self.branches,
            "current_branch_id": self.current_branch_id,
        }
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_tokens(self) -> dict:
        if TOKENS_FILE.exists():
            data = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
            data.setdefault("limit", DEFAULT_TOKEN_LIMIT)
            return data
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "limit": DEFAULT_TOKEN_LIMIT,
        }

    def _save_tokens(self) -> None:
        TOKENS_FILE.write_text(
            json.dumps(self.token_stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _accumulate_tokens(self, usage: dict) -> None:
        self.token_stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.token_stats["completion_tokens"] += usage.get("completion_tokens", 0)
        self.token_stats["total_tokens"] += usage.get("total_tokens", 0)
        self._save_tokens()
