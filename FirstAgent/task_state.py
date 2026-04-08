from __future__ import annotations
from datetime import datetime, timezone

TRANSITIONS: dict[str, set[str]] = {
    "planning":   {"execution"},
    "execution":  {"validation", "blocked", "planning"},
    "validation": {"done", "execution", "planning"},
    "blocked":    {"execution", "planning"},
    "done":       {"planning"},
}

STATE_DEFAULT_ACTION: dict[str, str] = {
    "planning":   "define_steps",
    "execution":  "execute_step",
    "validation": "validate",
    "blocked":    "user_input",
    "done":       "none",
}

# Commands that are valid in each state. Used both for hard enforcement
# (assert_command_allowed) and for LLM prompt injection.
ALLOWED_COMMANDS_BY_STATE: dict[str, list[str]] = {
    "planning":   ["/task-steps"],
    "execution":  ["/task-next", "/task-confirm", "/task-block", "/task-validate"],
    "validation": ["/task-done", "/task-replan"],
    "blocked":    ["/task-unblock"],
    "done":       ["/task"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskFSM:
    """Finite state machine for a single agent task."""

    def __init__(self, data: dict):
        self._data = data

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    def new(cls, description: str) -> "TaskFSM":
        now = _now()
        return cls({
            "description": description,
            "state": "planning",
            "step_current": 0,
            "step_total": 0,
            "step_description": "",
            "expected_action": "define_steps",
            "started_at": now,
            "updated_at": now,
            "history": [],
        })

    @classmethod
    def from_dict(cls, data: dict) -> "TaskFSM":
        return cls(data)

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._data["state"]

    @property
    def description(self) -> str:
        return self._data["description"]

    @property
    def step_current(self) -> int:
        return self._data.get("step_current", 0)

    @property
    def step_total(self) -> int:
        return self._data.get("step_total", 0)

    @property
    def step_description(self) -> str:
        return self._data.get("step_description", "")

    @property
    def expected_action(self) -> str:
        return self._data.get("expected_action", "none")

    # ── Transitions ───────────────────────────────────────────────────────

    def transition(self, to_state: str) -> None:
        allowed = TRANSITIONS.get(self.state, set())
        if to_state not in allowed:
            raise ValueError(
                f"Invalid transition: {self.state!r} -> {to_state!r}. "
                f"Allowed: {sorted(allowed) or 'none'}"
            )
        self._data["history"].append({"from": self.state, "to": to_state, "at": _now()})
        self._data["state"] = to_state
        self._data["expected_action"] = STATE_DEFAULT_ACTION[to_state]
        self._data["updated_at"] = _now()

    def assert_command_allowed(self, cmd: str) -> None:
        """Raise ValueError if cmd is not permitted in the current state."""
        allowed = ALLOWED_COMMANDS_BY_STATE.get(self.state, [])
        if cmd not in allowed:
            allowed_str = ", ".join(allowed) if allowed else "none"
            raise ValueError(
                f"Command {cmd!r} is not allowed in state {self.state!r}. "
                f"Allowed: {allowed_str}"
            )

    def allowed_commands(self) -> list[str]:
        return list(ALLOWED_COMMANDS_BY_STATE.get(self.state, []))

    # ── Step management ───────────────────────────────────────────────────

    def set_steps(self, total: int) -> None:
        if self.state != "planning":
            raise ValueError(
                f"set_steps requires state 'planning', current: {self.state!r}"
            )
        self._data["step_total"] = total
        self._data["step_current"] = 0
        self._data["step_description"] = ""
        self._data["updated_at"] = _now()

    def next_step(self, description: str = "") -> None:
        if self.state != "execution":
            raise ValueError(
                f"next_step requires state 'execution', current: {self.state!r}"
            )
        cap = self._data.get("step_total") or 999
        self._data["step_current"] = min(self._data.get("step_current", 0) + 1, cap)
        self._data["step_description"] = description
        self._data["expected_action"] = "confirm_step"
        self._data["updated_at"] = _now()

    def set_expected_action(self, action: str) -> None:
        self._data["expected_action"] = action
        self._data["updated_at"] = _now()

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return dict(self._data)

    # ── LLM context ───────────────────────────────────────────────────────

    def to_context_string(self) -> str:
        parts = [f"Phase: {self.state}"]
        if self.step_total > 0:
            step = f"Step: {self.step_current}/{self.step_total}"
            if self.step_description:
                step += f" — {self.step_description}"
            parts.append(step)
        if self.expected_action != "none":
            parts.append(f"Expected action: {self.expected_action}")
        allowed = self.allowed_commands()
        if allowed:
            parts.append(f"Allowed commands: {', '.join(allowed)}")
        return " | ".join(parts)