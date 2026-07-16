"""
Activity event bus — глобальный синглтон для отслеживания действий агентов.

Использование:
    from activity import activity
    activity.set_current("Поиск в документации...", agent="chat")
    activity.emit("rag_retrieve", "Найдено 12 чанков", agent="chat")
    activity.clear_current()

Состояние отдаётся в UI через GET /activity?since=N (поллинг из app.js).
"""

from collections import deque
from datetime import datetime, timezone


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class ActivityStore:
    """In-memory лог последних событий + текущее действие.

    Однопоточный asyncio — блокировки не нужны. Все операции O(1)/O(maxlen).
    """

    def __init__(self, maxlen: int = 200):
        self.events: deque = deque(maxlen=maxlen)
        self.current_action: dict | None = None
        self._seq: int = 0

    def emit(self, kind: str, message: str, agent: str = "", detail: dict | None = None) -> dict:
        """Добавить событие в лог."""
        self._seq += 1
        event = {
            "id": self._seq,
            "ts": _now_iso(),
            "kind": kind,
            "message": message,
            "agent": agent,
            "detail": detail or {},
        }
        self.events.append(event)
        return event

    def set_current(self, message: str, agent: str = "") -> None:
        """Установить текущее действие (показывается в статус-баре)."""
        self.current_action = {
            "message": message,
            "agent": agent,
            "since": _now_iso(),
        }

    def clear_current(self) -> None:
        """Сбросить текущее действие (агент простаивает)."""
        self.current_action = None

    def get_state(self, since: int = 0) -> dict:
        """Состояние для поллинг-эндпоинта: события с id > since + текущее действие."""
        return {
            "current_action": self.current_action,
            "events": [e for e in self.events if e["id"] > since],
            "latest_id": self._seq,
        }


# Глобальный синглтон — импортируется всеми инструментированными модулями
activity = ActivityStore()
