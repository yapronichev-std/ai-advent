"""
MCP-сервер для доступа к CRM-данным (пользователи и тикеты).

Пользователи берутся из реальных данных приложения: memory/users/<user_id>/.
Профили хранятся в long_term/profile.json (ключи: name, email, language, etc.).
Тикеты — демо-данные из data/tickets.json.

Транспорт: stdio.

Инструменты:
  - search_users:        поиск пользователей по имени, email или id
  - get_user:            получить профиль пользователя по id
  - get_user_tickets:    тикеты пользователя
  - get_ticket:          детали тикета
  - search_tickets:      поиск тикетов по тексту и статусу
  - get_user_context:    сводка по пользователю (профиль + тикеты)
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

app = Server("mcp-crm")

# ── Пути ───────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).parent.parent / "data"
_MEMORY_USERS_DIR = Path(__file__).parent.parent / "memory" / "users"


# ── Работа с пользователями (из memory/users/) ─────────────────────────────────


def _list_users() -> list[str]:
    """Список всех пользователей из memory/users/."""
    if not _MEMORY_USERS_DIR.exists():
        return []
    return sorted(
        p.name for p in _MEMORY_USERS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def _load_profile(user_id: str) -> dict:
    """Загрузить профиль пользователя из long_term/profile.json."""
    profile_file = _MEMORY_USERS_DIR / user_id / "long_term" / "profile.json"
    if not profile_file.exists():
        return {}
    try:
        with open(profile_file, encoding="utf-8") as f:
            data = json.load(f)
        # Формат: {"entries": [{"key": ..., "value": ..., "saved_at": ...}]}
        entries = data.get("entries", data) if isinstance(data, dict) else data
        if isinstance(entries, list):
            return {e["key"]: e["value"] for e in entries if "key" in e}
        return entries
    except Exception:
        return {}


def _load_user_history(user_id: str) -> list[dict]:
    """Загрузить историю чата пользователя (последние сообщения)."""
    history_file = _MEMORY_USERS_DIR / user_id / "history.json"
    if not history_file.exists():
        return []
    try:
        with open(history_file, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _build_user_object(user_id: str, profile: dict) -> dict:
    """Собрать объект пользователя из id и профиля."""
    name = profile.get("name", user_id)
    email = profile.get("email", f"{user_id}@unknown")

    # Пытаемся определить план/роль из тегов профиля
    plan = profile.get("plan", "unknown")
    role = profile.get("role", "customer")
    company = profile.get("company", "")
    tags = [t.strip() for t in profile.get("tags", "").split(",") if t.strip()]

    history = _load_user_history(user_id)
    last_message = history[-1] if history else None
    last_login = last_message.get("role", "") if last_message else None

    return {
        "id": user_id,
        "name": name,
        "email": email,
        "role": role,
        "company": company,
        "plan": plan,
        "created_at": profile.get("created_at", "—"),
        "last_login": profile.get("last_login", "—"),
        "status": profile.get("status", "active"),
        "tags": tags,
        "profile_keys": list(profile.keys()),
        "message_count": len(history),
    }


def _search_users(query: str) -> list[dict]:
    """Поиск пользователей по id, имени или email в профиле."""
    results = []
    q = query.strip().lower()
    for user_id in _list_users():
        profile = _load_profile(user_id)
        name = profile.get("name", "").lower()
        email = profile.get("email", "").lower()
        if q in user_id.lower() or q in name or q in email:
            results.append(_build_user_object(user_id, profile))
    return results


# ── Работа с тикетами (демо-данные) ────────────────────────────────────────────


def _load_tickets() -> list[dict]:
    """Загрузить тикеты из data/tickets.json."""
    path = _DATA_DIR / "tickets.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_tickets(tickets: list[dict]) -> None:
    """Сохранить тикеты в data/tickets.json."""
    path = _DATA_DIR / "tickets.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tickets, f, ensure_ascii=False, indent=2)


def _next_ticket_id(tickets: list[dict]) -> str:
    """Сгенерировать следующий ID тикета (tkt_XXX)."""
    max_num = 100
    for t in tickets:
        try:
            num = int(t["id"].replace("tkt_", ""))
            max_num = max(max_num, num)
        except (ValueError, KeyError):
            pass
    return f"tkt_{max_num + 1}"


# ── Описание инструментов ─────────────────────────────────────────────────────


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_users",
            description="Поиск пользователей по имени, email или id среди реальных пользователей приложения (memory/users/).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Имя, email или id пользователя для поиска."},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_user",
            description="Получить профиль пользователя (из memory/users/<id>/long_term/profile.json).",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "ID пользователя (например default, test-day31-2)."},
                },
                "required": ["user_id"],
            },
        ),
        types.Tool(
            name="get_user_tickets",
            description="Получить все тикеты пользователя из демо-данных.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "ID пользователя."},
                    "status": {
                        "type": "string",
                        "description": "Фильтр по статусу (open, in_progress, resolved, closed).",
                    },
                },
                "required": ["user_id"],
            },
        ),
        types.Tool(
            name="get_ticket",
            description="Получить полную информацию о тикете по его id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string", "description": "ID тикета (например tkt_101)."},
                },
                "required": ["ticket_id"],
            },
        ),
        types.Tool(
            name="search_tickets",
            description="Поиск тикетов по ключевым словам и статусу.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Поисковый запрос (subject, description, category)."},
                    "status": {"type": "string", "description": "Фильтр по статусу (необязательно)."},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_user_context",
            description="Получить сводку по пользователю: профиль (из memory/users/) + тикеты (демо).",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "ID пользователя."},
                },
                "required": ["user_id"],
            },
        ),
        types.Tool(
            name="create_ticket",
            description="Создать новый тикет для пользователя. Тикет сохраняется в data/tickets.json.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "ID пользователя."},
                    "subject": {"type": "string", "description": "Тема тикета."},
                    "description": {"type": "string", "description": "Описание проблемы."},
                    "priority": {
                        "type": "string",
                        "description": "Приоритет: low, medium, high, critical.",
                        "default": "medium",
                    },
                    "category": {
                        "type": "string",
                        "description": "Категория: auth, billing, bug, account, integration, other.",
                        "default": "other",
                    },
                },
                "required": ["user_id", "subject", "description"],
            },
        ),
        types.Tool(
            name="update_ticket",
            description="Обновить статус тикета или добавить сообщение в переписку.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string", "description": "ID тикета."},
                    "status": {"type": "string", "description": "Новый статус: open, in_progress, resolved, closed."},
                    "message": {"type": "string", "description": "Текст сообщения для добавления в тикет."},
                    "message_role": {
                        "type": "string",
                        "description": "Роль автора сообщения: user или support.",
                        "default": "support",
                    },
                },
                "required": ["ticket_id"],
            },
        ),
    ]


# ── Обработка вызовов ─────────────────────────────────────────────────────────


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    # ── search_users ───────────────────────────────────────────────────────
    if name == "search_users":
        query = arguments.get("query", "").strip()
        if query:
            results = _search_users(query)
        else:
            # Пустой запрос — вернуть всех пользователей
            results = [_build_user_object(uid, _load_profile(uid)) for uid in _list_users()]
        logger.info("search_users: query=%r → %d results", query, len(results))
        return _ok({"results": results, "count": len(results)})

    # ── get_user ───────────────────────────────────────────────────────────
    if name == "get_user":
        user_id = arguments.get("user_id", "").strip()
        if not user_id:
            return _err("Параметр 'user_id' обязателен.")
        if not (_MEMORY_USERS_DIR / user_id).is_dir():
            return _err(f"Пользователь с id={user_id} не найден.")
        profile = _load_profile(user_id)
        user = _build_user_object(user_id, profile)
        user["profile"] = profile  # полный набор ключей профиля
        return _ok({"user": user})

    # ── get_user_tickets ───────────────────────────────────────────────────
    if name == "get_user_tickets":
        user_id = arguments.get("user_id", "").strip()
        if not user_id:
            return _err("Параметр 'user_id' обязателен.")
        status_filter = arguments.get("status", "").strip().lower()
        tickets = _load_tickets()
        results = [t for t in tickets if t["user_id"] == user_id]
        if status_filter:
            results = [t for t in results if t["status"] == status_filter]
        logger.info("get_user_tickets: user_id=%s status=%r → %d tickets",
                     user_id, status_filter or "*", len(results))
        return _ok({"tickets": results, "count": len(results), "user_id": user_id})

    # ── get_ticket ─────────────────────────────────────────────────────────
    if name == "get_ticket":
        ticket_id = arguments.get("ticket_id", "").strip()
        if not ticket_id:
            return _err("Параметр 'ticket_id' обязателен.")
        tickets = _load_tickets()
        for t in tickets:
            if t["id"] == ticket_id:
                return _ok({"ticket": t})
        return _err(f"Тикет с id={ticket_id} не найден.")

    # ── search_tickets ─────────────────────────────────────────────────────
    if name == "search_tickets":
        query = arguments.get("query", "").strip().lower()
        if not query:
            return _err("Параметр 'query' обязателен.")
        status_filter = arguments.get("status", "").strip().lower()
        tickets = _load_tickets()
        results = []
        for t in tickets:
            searchable = " ".join([
                t.get("subject", ""),
                t.get("description", ""),
                t.get("category", ""),
            ]).lower()
            if query in searchable:
                if not status_filter or t["status"] == status_filter:
                    results.append(t)
        logger.info("search_tickets: query=%r status=%r → %d results",
                     query, status_filter or "*", len(results))
        return _ok({"results": results, "count": len(results)})

    # ── get_user_context ───────────────────────────────────────────────────
    if name == "get_user_context":
        user_id = arguments.get("user_id", "").strip()
        if not user_id:
            return _err("Параметр 'user_id' обязателен.")

        if not (_MEMORY_USERS_DIR / user_id).is_dir():
            return _err(f"Пользователь с id={user_id} не найден.")

        profile = _load_profile(user_id)
        user = _build_user_object(user_id, profile)

        tickets = _load_tickets()
        user_tickets = [t for t in tickets if t["user_id"] == user_id]
        open_tickets = [t for t in user_tickets if t["status"] in ("open", "in_progress")]
        closed_tickets = [t for t in user_tickets if t["status"] in ("resolved", "closed")]

        # Привязываем демо-тикеты к реальным пользователям:
        # если пользователь не usr_001..usr_005, показываем все открытые тикеты
        if not user_tickets:
            all_tickets = _load_tickets()
            open_tickets = [t for t in all_tickets if t["status"] in ("open", "in_progress")]
            closed_tickets = [t for t in all_tickets if t["status"] in ("resolved", "closed")]
            user_tickets = all_tickets

        context = {
            "user": user,
            "summary": {
                "total_tickets": len(user_tickets),
                "open_tickets": len(open_tickets),
                "closed_tickets": len(closed_tickets),
            },
            "active_tickets": [
                {
                    "id": t["id"],
                    "subject": t["subject"],
                    "status": t["status"],
                    "priority": t["priority"],
                    "category": t["category"],
                    "created_at": t["created_at"],
                    "last_message": t["messages"][-1] if t["messages"] else None,
                }
                for t in open_tickets
            ],
            "recent_tickets": [
                {
                    "id": t["id"],
                    "subject": t["subject"],
                    "status": t["status"],
                    "priority": t["priority"],
                    "category": t["category"],
                    "created_at": t["created_at"],
                }
                for t in sorted(user_tickets, key=lambda x: x["created_at"], reverse=True)[:10]
            ],
        }
        logger.info("get_user_context: user_id=%s profile_keys=%s open_tickets=%d",
                     user_id, list(profile.keys()), len(open_tickets))
        return _ok({"context": context})

    # ── create_ticket ───────────────────────────────────────────────────────
    if name == "create_ticket":
        user_id = arguments.get("user_id", "").strip()
        subject = arguments.get("subject", "").strip()
        description = arguments.get("description", "").strip()
        priority = arguments.get("priority", "medium").strip()
        category = arguments.get("category", "other").strip()

        if not user_id or not subject or not description:
            return _err("Параметры 'user_id', 'subject' и 'description' обязательны.")

        tickets = _load_tickets()
        new_ticket = {
            "id": _next_ticket_id(tickets),
            "user_id": user_id,
            "subject": subject,
            "status": "open",
            "priority": priority,
            "category": category,
            "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
            "description": description,
            "messages": [
                {
                    "role": "user",
                    "text": description,
                    "at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            ],
        }
        tickets.append(new_ticket)
        _save_tickets(tickets)
        logger.info("create_ticket: user_id=%s subject=%r → %s", user_id, subject, new_ticket["id"])
        return _ok({"ticket": new_ticket})

    # ── update_ticket ───────────────────────────────────────────────────────
    if name == "update_ticket":
        ticket_id = arguments.get("ticket_id", "").strip()
        if not ticket_id:
            return _err("Параметр 'ticket_id' обязателен.")

        tickets = _load_tickets()
        for t in tickets:
            if t["id"] == ticket_id:
                new_status = arguments.get("status", "").strip()
                message_text = arguments.get("message", "").strip()
                message_role = arguments.get("message_role", "support").strip()

                if new_status:
                    t["status"] = new_status
                    logger.info("update_ticket: %s status → %s", ticket_id, new_status)

                if message_text:
                    t.setdefault("messages", []).append({
                        "role": message_role,
                        "text": message_text,
                        "at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })

                _save_tickets(tickets)
                return _ok({"ticket": t})

        return _err(f"Тикет с id={ticket_id} не найден.")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _ok(data: dict) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]


def _err(msg: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps({"error": msg}, ensure_ascii=False))]


# ── Точка входа ────────────────────────────────────────────────────────────────


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
