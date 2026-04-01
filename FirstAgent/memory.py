import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

MEMORY_DIR = Path("memory")

LongTermCategory = Literal["profile", "decisions", "knowledge"]


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

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        user_dir = MEMORY_DIR / "users" / user_id
        working_dir = user_dir / "working"
        long_term_dir = user_dir / "long_term"

        self._task_file = working_dir / "current_task.json"
        self._category_files: dict[LongTermCategory, Path] = {
            "profile": long_term_dir / "profile.json",
            "decisions": long_term_dir / "decisions.json",
            "knowledge": long_term_dir / "knowledge.json",
        }

    # ── Working memory ──────────────────────────────────────────────────

    def get_working(self) -> dict:
        return _load(self._task_file, {"task": None, "facts": [], "started_at": None})

    def set_task(self, description: str) -> None:
        _save(self._task_file, {"task": description, "facts": [], "started_at": _now()})

    def add_working_fact(self, key: str, value: str) -> None:
        data = self.get_working()
        data["facts"] = [f for f in data["facts"] if f["key"] != key]
        data["facts"].append({"key": key, "value": value, "saved_at": _now()})
        _save(self._task_file, data)

    def delete_working_fact(self, key: str) -> bool:
        data = self.get_working()
        before = len(data["facts"])
        data["facts"] = [f for f in data["facts"] if f["key"] != key]
        if len(data["facts"]) < before:
            _save(self._task_file, data)
            return True
        return False

    def clear_working(self) -> None:
        _save(self._task_file, {"task": None, "facts": [], "started_at": None})

    # ── Long-term memory ─────────────────────────────────────────────────

    def get_long_term(self, category: LongTermCategory) -> list[dict]:
        data = _load(self._category_files[category], {"entries": []})
        return data["entries"]

    def add_long_term(self, category: LongTermCategory, key: str, value: str) -> None:
        path = self._category_files[category]
        data = _load(path, {"entries": []})
        data["entries"] = [e for e in data["entries"] if e["key"] != key]
        data["entries"].append({"key": key, "value": value, "saved_at": _now()})
        _save(path, data)

    def delete_long_term(self, category: LongTermCategory, key: str) -> bool:
        path = self._category_files[category]
        data = _load(path, {"entries": []})
        before = len(data["entries"])
        data["entries"] = [e for e in data["entries"] if e["key"] != key]
        if len(data["entries"]) < before:
            _save(path, data)
            return True
        return False

    def clear_long_term(self, category: LongTermCategory) -> None:
        _save(self._category_files[category], {"entries": []})

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