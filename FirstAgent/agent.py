import json
import time
import httpx
from pathlib import Path
from typing import Optional

from config import load_system_prompt
from invariants import InvariantStore
from memory import MemoryStore
from task_state import TaskFSM


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TOKEN_LIMIT = 1_000_000
MAX_HISTORY = 10

# Profile keys that directly shape the system prompt behaviour
_BEHAVIOUR_KEYS = {"name", "language", "response_style"}


class ChatAgent:
    def __init__(self, api_key: str, model: str, user_id: str = "default"):
        self.api_key = api_key
        self.model = model
        self.user_id = user_id

        user_dir = Path("memory") / "users" / user_id
        self._history_file = user_dir / "history.json"
        self._tokens_file = user_dir / "tokens.json"
        self._summary_file = user_dir / "summary.json"

        self.history: list[dict] = self._load_history()
        self.token_stats: dict = self._load_tokens()
        self.summary: str = self._load_summary()
        self.memory = MemoryStore(user_id=user_id)
        self.invariants = InvariantStore()

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

    # ── Персонализация ────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        """Читает глобальный промпт из файла и дополняет поведенческими инструкциями из профиля."""
        base = load_system_prompt()

        profile = {e["key"]: e["value"] for e in self.memory.get_long_term("profile")}
        if not profile:
            return base

        additions: list[str] = []
        if name := profile.get("name"):
            additions.append(f"Address the user as {name}.")
        if lang := profile.get("language"):
            additions.append(f"Always respond in {lang}.")
        if style := profile.get("response_style"):
            additions.append(f"Response style: {style}.")

        if additions:
            return base + "\n\n" + " ".join(additions)
        return base

    # ── Построение сообщений ──────────────────────────────────────────────

    def _build_messages(self) -> list[dict]:
        messages = []
        system_prompt = self._build_system_prompt()
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        invariants_block = self.invariants.build_prompt_block()
        if invariants_block:
            messages.append({"role": "system", "content": invariants_block})
        memory_context = self.memory.build_context_block()
        if memory_context:
            messages.append({"role": "system", "content": memory_context})
        if self.summary:
            messages.append({"role": "system", "content": f"Summary of earlier conversation:\n{self.summary}"})
        messages.extend(self.history)
        return messages

    # ── Файловые операции ─────────────────────────────────────────────────

    def _load_history(self) -> list[dict]:
        if self._history_file.exists():
            return json.loads(self._history_file.read_text(encoding="utf-8"))
        return []

    def _save_history(self) -> None:
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        self._history_file.write_text(json.dumps(self.history, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_summary(self) -> str:
        if self._summary_file.exists():
            return json.loads(self._summary_file.read_text(encoding="utf-8")).get("summary", "")
        return ""

    def _save_summary(self) -> None:
        self._summary_file.parent.mkdir(parents=True, exist_ok=True)
        self._summary_file.write_text(json.dumps({"summary": self.summary}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_tokens(self) -> dict:
        if self._tokens_file.exists():
            data = json.loads(self._tokens_file.read_text(encoding="utf-8"))
            data.setdefault("limit", DEFAULT_TOKEN_LIMIT)
            return data
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "limit": DEFAULT_TOKEN_LIMIT}

    def _save_tokens(self) -> None:
        self._tokens_file.parent.mkdir(parents=True, exist_ok=True)
        self._tokens_file.write_text(json.dumps(self.token_stats, ensure_ascii=False, indent=2), encoding="utf-8")

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
        new_summary, _ = await self._call_api([{"role": "user", "content": prompt}])

        self.summary = f"{self.summary}\n\n{new_summary}".strip() if self.summary else new_summary
        self._save_summary()

    # ── Команды ───────────────────────────────────────────────────────────

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
            fsm = TaskFSM.new(args)
            self.memory.save_task_state(fsm)
            return f"Task started: {args}\nState: planning | Expected: define_steps"

        if cmd == "/task-steps":
            if not args:
                return "Usage: /task-steps <N>"
            try:
                total = int(args.strip())
            except ValueError:
                return "Usage: /task-steps <N>  (N must be an integer)"
            fsm = self.memory.get_task_state()
            if not fsm:
                return "No active task. Use /task <description> first."
            try:
                fsm.set_steps(total)
                fsm.transition("execution")
            except ValueError as e:
                return str(e)
            self.memory.save_task_state(fsm)
            return f"Steps set to {total}. State: execution | Expected: execute_step"

        if cmd == "/task-next":
            fsm = self.memory.get_task_state()
            if not fsm:
                return "No active task."
            fsm.next_step(args)
            self.memory.save_task_state(fsm)
            total_label = str(fsm.step_total) if fsm.step_total else "?"
            suffix = f" — {args}" if args else ""
            return f"Step {fsm.step_current}/{total_label}{suffix} | Expected: confirm_step"

        if cmd == "/task-block":
            fsm = self.memory.get_task_state()
            if not fsm:
                return "No active task."
            try:
                fsm.transition("blocked")
            except ValueError as e:
                return str(e)
            if args:
                self.memory.add_working_fact("block_reason", args)
            self.memory.save_task_state(fsm)
            return "Task blocked. Expected: user_input"

        if cmd == "/task-unblock":
            fsm = self.memory.get_task_state()
            if not fsm:
                return "No active task."
            try:
                fsm.transition("execution")
            except ValueError as e:
                return str(e)
            self.memory.save_task_state(fsm)
            return "Task unblocked. State: execution | Expected: execute_step"

        if cmd == "/task-validate":
            fsm = self.memory.get_task_state()
            if not fsm:
                return "No active task."
            try:
                fsm.transition("validation")
            except ValueError as e:
                return str(e)
            self.memory.save_task_state(fsm)
            return "Task in validation. Expected: validate"

        if cmd == "/task-replan":
            fsm = self.memory.get_task_state()
            if not fsm:
                return "No active task."
            try:
                fsm.transition("planning")
            except ValueError as e:
                return str(e)
            self.memory.save_task_state(fsm)
            return "Task back in planning. Expected: define_steps"

        if cmd == "/task-status":
            fsm = self.memory.get_task_state()
            if not fsm:
                w = self.memory.get_working()
                return f"Task: {w.get('task') or '(none)'}\nNo FSM state active."
            d = fsm.to_dict()
            lines = [f"Task: {d['description']}", f"State: {d['state']}"]
            if d["step_total"] > 0:
                lines.append(f"Step: {d['step_current']}/{d['step_total']}")
                if d["step_description"]:
                    lines.append(f"  └ {d['step_description']}")
            lines.append(f"Expected: {d['expected_action']}")
            if d["history"]:
                lines.append("History:")
                for h in d["history"]:
                    lines.append(f"  {h['from']} → {h['to']}  ({h['at']})")
            return "\n".join(lines)

        if cmd == "/task-done":
            fsm = self.memory.get_task_state()
            w = self.memory.get_working()
            task = (fsm.description if fsm else None) or w.get("task") or "(no active task)"
            if fsm:
                fsm.force_complete()
                self.memory.save_task_state(fsm)
            self.memory.clear_working()
            return f"Task completed: {task}"

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

        if cmd == "/invariant":
            if not args:
                return "Usage: /invariant <rule text>"
            item = self.invariants.add(args)
            items = self.invariants.list_all()
            n = next(i + 1 for i, x in enumerate(items) if x["id"] == item["id"])
            return f"Invariant #{n} added: {item['text']}"

        if cmd == "/invariants":
            items = self.invariants.list_all()
            if not items:
                return "No invariants defined."
            lines = ["Invariants:"]
            for i, inv in enumerate(items, 1):
                status = "on" if inv.get("active", True) else "off"
                lines.append(f"  {i}. [{status}] {inv['text']}  ({inv['id']})")
            return "\n".join(lines)

        if cmd == "/invariant-del":
            if not args:
                return "Usage: /invariant-del <number>"
            inv_id = self._resolve_invariant_id(args.strip())
            if not inv_id:
                return f"Invariant '{args.strip()}' not found."
            self.invariants.delete(inv_id)
            return f"Invariant deleted."

        if cmd == "/invariant-off":
            if not args:
                return "Usage: /invariant-off <number>"
            inv_id = self._resolve_invariant_id(args.strip())
            if not inv_id:
                return f"Invariant '{args.strip()}' not found."
            self.invariants.set_active(inv_id, False)
            return "Invariant disabled."

        if cmd == "/invariant-on":
            if not args:
                return "Usage: /invariant-on <number>"
            inv_id = self._resolve_invariant_id(args.strip())
            if not inv_id:
                return f"Invariant '{args.strip()}' not found."
            self.invariants.set_active(inv_id, True)
            return "Invariant enabled."

        if cmd == "/help":
            return (
                "Task FSM commands:\n"
                "  /task <desc>              — start a task (state: planning)\n"
                "  /task-steps <N>           — set N steps, move to execution\n"
                "  /task-next [desc]         — advance to next step\n"
                "  /task-block [reason]      — block task (waiting for input)\n"
                "  /task-unblock             — resume blocked task\n"
                "  /task-validate            — move to validation phase\n"
                "  /task-replan              — return to planning\n"
                "  /task-done                — complete and clear task\n"
                "  /task-status              — show full FSM state\n"
                "\nMemory commands:\n"
                "  /fact <key>: <value>      — add fact to working memory\n"
                "  /remember <key>: <value>  — save to long-term knowledge\n"
                "  /profile <key>: <value>   — save to user profile\n"
                "  /decide <key>: <value>    — save to decisions\n"
                "  /forget <cat> <key>       — delete from long-term memory\n"
                "  /memory                   — show all memory levels\n"
                "\nInvariant commands:\n"
                "  /invariant <rule>         — add an invariant\n"
                "  /invariants               — list all invariants\n"
                "  /invariant-del <n>        — delete invariant by number\n"
                "  /invariant-off <n>        — temporarily disable invariant\n"
                "  /invariant-on <n>         — re-enable invariant"
            )

        return None  # unknown command — let the LLM handle it

    def _resolve_invariant_id(self, arg: str) -> Optional[str]:
        """Resolve a 1-based position number or inv_XXXXXXXX id to an id string."""
        items = self.invariants.list_all()
        if arg.startswith("inv_"):
            return arg if any(i["id"] == arg for i in items) else None
        try:
            n = int(arg)
            if 1 <= n <= len(items):
                return items[n - 1]["id"]
        except ValueError:
            pass
        return None

    def _format_memory_snapshot(self) -> str:
        snap = self.memory.snapshot()
        lines = [f"=== Memory snapshot (user: {self.user_id}) ===\n"]

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