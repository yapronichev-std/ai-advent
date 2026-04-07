import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

INVARIANTS_FILE = Path("memory") / "invariants.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class InvariantStore:
    """Global invariants — rules the assistant must never violate."""

    def __init__(self, path: Path = INVARIANTS_FILE):
        self._path = path

    def _load(self) -> list[dict]:
        if self._path.exists():
            return json.loads(self._path.read_text(encoding="utf-8")).get("invariants", [])
        return []

    def _save(self, items: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"invariants": items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_all(self) -> list[dict]:
        return self._load()

    def list_active(self) -> list[dict]:
        return [i for i in self._load() if i.get("active", True)]

    def add(self, text: str) -> dict:
        items = self._load()
        item = {
            "id": f"inv_{uuid.uuid4().hex[:8]}",
            "text": text.strip(),
            "active": True,
            "created_at": _now(),
        }
        items.append(item)
        self._save(items)
        return item

    def delete(self, inv_id: str) -> bool:
        items = self._load()
        new_items = [i for i in items if i["id"] != inv_id]
        if len(new_items) == len(items):
            return False
        self._save(new_items)
        return True

    def set_active(self, inv_id: str, active: bool) -> Optional[dict]:
        items = self._load()
        for item in items:
            if item["id"] == inv_id:
                item["active"] = active
                self._save(items)
                return item
        return None

    def build_prompt_block(self) -> str:
        """Returns a system prompt block listing all active invariants."""
        active = self.list_active()
        if not active:
            return ""
        lines = [
            "[INVARIANTS — rules you MUST NOT violate]",
            "Before every response, reason through each invariant below.",
            "If your proposed answer would violate any invariant — refuse and explicitly state which invariant is violated.",
            "",
        ]
        for i, inv in enumerate(active, 1):
            lines.append(f"{i}. {inv['text']}")
        return "\n".join(lines)