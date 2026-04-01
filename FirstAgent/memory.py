import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

MEMORY_DIR = Path("memory")
WORKING_DIR = MEMORY_DIR / "working"
LONG_TERM_DIR = MEMORY_DIR / "long_term"

TASK_FILE = WORKING_DIR / "current_task.json"
PROFILE_FILE = LONG_TERM_DIR / "profile.json"
DECISIONS_FILE = LONG_TERM_DIR / "decisions.json"
KNOWLEDGE_FILE = LONG_TERM_DIR / "knowledge.json"

LongTermCategory = Literal["profile", "decisions", "knowledge"]

_CATEGORY_FILES: dict[LongTermCategory, Path] = {
    "profile": PROFILE_FILE,
    "decisions": DECISIONS_FILE,
    "knowledge": KNOWLEDGE_FILE,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path: Path, default: Any) -> Any:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class MemoryStore:
    """Three-level memory: short-term (history), working, long-term."""

    # ── Working memory ──────────────────────────────────────────────────

    def get_working(self) -> dict:
        return _load(TASK_FILE, {"task": None, "facts": [], "started_at": None})

    def set_task(self, description: str) -> None:
        data = {"task": description, "facts": [], "started_at": _now()}
        _save(TASK_FILE, data)

    def add_working_fact(self, key: str, value: str) -> None:
        data = self.get_working()
        data["facts"] = [f for f in data["facts"] if f["key"] != key]
        data["facts"].append({"key": key, "value": value, "saved_at": _now()})
        _save(TASK_FILE, data)

    def delete_working_fact(self, key: str) -> bool:
        data = self.get_working()
        before = len(data["facts"])
        data["facts"] = [f for f in data["facts"] if f["key"] != key]
        if len(data["facts"]) < before:
            _save(TASK_FILE, data)
            return True
        return False

    def clear_working(self) -> None:
        _save(TASK_FILE, {"task": None, "facts": [], "started_at": None})

    # ── Long-term memory ─────────────────────────────────────────────────

    def get_long_term(self, category: LongTermCategory) -> list[dict]:
        path = _CATEGORY_FILES[category]
        data = _load(path, {"entries": []})
        return data["entries"]

    def add_long_term(self, category: LongTermCategory, key: str, value: str) -> None:
        path = _CATEGORY_FILES[category]
        data = _load(path, {"entries": []})
        data["entries"] = [e for e in data["entries"] if e["key"] != key]
        data["entries"].append({"key": key, "value": value, "saved_at": _now()})
        _save(path, data)

    def delete_long_term(self, category: LongTermCategory, key: str) -> bool:
        path = _CATEGORY_FILES[category]
        data = _load(path, {"entries": []})
        before = len(data["entries"])
        data["entries"] = [e for e in data["entries"] if e["key"] != key]
        if len(data["entries"]) < before:
            _save(path, data)
            return True
        return False

    def clear_long_term(self, category: LongTermCategory) -> None:
        _save(_CATEGORY_FILES[category], {"entries": []})

    # ── Snapshot (all levels) ─────────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "working": self.get_working(),
            "long_term": {
                "profile": self.get_long_term("profile"),
                "decisions": self.get_long_term("decisions"),
                "knowledge": self.get_long_term("knowledge"),
            },
        }

    # ── Context builder (for _build_messages) ────────────────────────────

    def build_context_block(self) -> str:
        """Returns a formatted string to inject into the system context."""
        parts: list[str] = []

        w = self.get_working()
        if w["task"]:
            parts.append(f"[Working memory]\nCurrent task: {w['task']}")
            if w["facts"]:
                facts_text = "\n".join(f"  - {f['key']}: {f['value']}" for f in w["facts"])
                parts.append(f"Known facts:\n{facts_text}")

        for category, label in [("profile", "User profile"), ("decisions", "Past decisions"), ("knowledge", "Knowledge")]:
            entries = self.get_long_term(category)
            if entries:
                lines = "\n".join(f"  - {e['key']}: {e['value']}" for e in entries)
                parts.append(f"[{label}]\n{lines}")

        return "\n\n".join(parts)
