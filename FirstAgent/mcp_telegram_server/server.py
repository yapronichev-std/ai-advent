"""
MCP-сервер для отправки сообщений в Telegram через Bot API.

Транспорт: stdio (стандарт для MCP-клиентов).

Инструменты:
  - send_telegram_message:      отправить разовое сообщение в чат.
  - start_periodic_summary:     запустить фоновую отправку summary раз в N секунд.
  - update_summary:             обновить текст summary (агент вызывает после каждого ответа).
  - stop_periodic_summary:      остановить фоновую отправку.
"""

import asyncio
import json
import logging
import os
import sys

import httpx
import mcp.types as types
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_API_DOCUMENT = "https://api.telegram.org/bot{token}/sendDocument"

app = Server("mcp-telegram")

# ── Состояние периодической отправки ─────────────────────────────────────────

_periodic: dict = {
    "chat_id": "",
    "summary": "",
    "interval": 60,
    "task": None,       # asyncio.Task | None
}


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _get_token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN")


async def _send(chat_id: str, text: str) -> dict:
    """Отправить сообщение через Bot API. Возвращает dict с результатом."""
    token = _get_token()
    if not token:
        return {"error": "Переменная окружения TELEGRAM_BOT_TOKEN не задана."}

    url = TELEGRAM_API_BASE.format(token=token)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
            data = response.json()
    except httpx.TimeoutException:
        return {"error": "Таймаут при обращении к Telegram API."}
    except httpx.RequestError as exc:
        return {"error": f"Сетевая ошибка: {exc}"}

    if not data.get("ok"):
        error_code = data.get("error_code")
        description = data.get("description", "Неизвестная ошибка")
        return {"error": f"Telegram API [{error_code}]: {description}"}

    return {"ok": True, "message_id": data["result"]["message_id"]}


async def _send_document(chat_id: str, file_path: str, caption: str = "") -> dict:
    """Отправить файл через Bot API (sendDocument). Возвращает dict с результатом."""
    token = _get_token()
    if not token:
        return {"error": "Переменная окружения TELEGRAM_BOT_TOKEN не задана."}

    from pathlib import Path
    path = Path(file_path)
    if not path.exists():
        return {"error": f"Файл не найден: {file_path}"}

    url = TELEGRAM_API_DOCUMENT.format(token=token)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            with path.open("rb") as f:
                response = await client.post(
                    url,
                    data={"chat_id": chat_id, "caption": caption},
                    files={"document": (path.name, f, "application/octet-stream")},
                )
            data = response.json()
    except httpx.TimeoutException:
        return {"error": "Таймаут при отправке файла в Telegram."}
    except httpx.RequestError as exc:
        return {"error": f"Сетевая ошибка: {exc}"}

    if not data.get("ok"):
        error_code = data.get("error_code")
        description = data.get("description", "Неизвестная ошибка")
        return {"error": f"Telegram API [{error_code}]: {description}"}

    return {"ok": True, "message_id": data["result"]["message_id"]}


async def _periodic_loop() -> None:
    """Фоновая задача: отправлять summary в Telegram каждые _periodic['interval'] секунд."""
    logger.info(
        "[periodic] задача запущена: chat_id=%s interval=%ds",
        _periodic["chat_id"],
        _periodic["interval"],
    )
    while True:
        await asyncio.sleep(_periodic["interval"])

        chat_id = _periodic["chat_id"]
        summary = _periodic["summary"]

        if not chat_id or not summary:
            logger.debug("[periodic] пропуск — chat_id или summary пусты")
            continue

        logger.info(
            "[periodic] отправка summary → chat_id=%s summary_len=%d",
            chat_id,
            len(summary),
        )
        result = await _send(chat_id, f"⏱ Periodic summary:\n\n{summary}")
        if "error" in result:
            logger.warning("[periodic] ошибка отправки: %s", result["error"])
        else:
            logger.info("[periodic] доставлено, message_id=%s", result.get("message_id"))


def _start_task() -> None:
    """Создать asyncio-задачу периодической отправки (отменяет предыдущую)."""
    _stop_task()
    _periodic["task"] = asyncio.get_event_loop().create_task(_periodic_loop())
    logger.info("[periodic] asyncio task создана")


def _stop_task() -> None:
    task = _periodic["task"]
    if task and not task.done():
        task.cancel()
        logger.info("[periodic] asyncio task отменена")
    _periodic["task"] = None


# ── Описание инструментов ─────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="send_telegram_message",
            description=(
                "Отправить разовое текстовое сообщение в Telegram-чат через Bot API."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "ID чата или @username."},
                    "text":    {"type": "string", "description": "Текст сообщения."},
                },
                "required": ["chat_id", "text"],
            },
        ),
        types.Tool(
            name="send_telegram_document",
            description=(
                "Отправить файл (документ) в Telegram-чат через Bot API (sendDocument). "
                "Принимает абсолютный путь к файлу на диске."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id":   {"type": "string", "description": "ID чата или @username."},
                    "file_path": {"type": "string", "description": "Абсолютный путь к файлу."},
                    "caption":   {"type": "string", "description": "Подпись к файлу (необязательно)."},
                },
                "required": ["chat_id", "file_path"],
            },
        ),
        types.Tool(
            name="start_periodic_summary",
            description=(
                "Запустить фоновую отправку summary в Telegram с заданным интервалом. "
                "Каждые interval_seconds секунд сервер сам отправляет последний summary."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id":          {"type": "string", "description": "ID чата."},
                    "interval_seconds": {"type": "integer", "description": "Интервал в секундах (по умолчанию 60).", "default": 60},
                },
                "required": ["chat_id"],
            },
        ),
        types.Tool(
            name="update_summary",
            description=(
                "Обновить текст summary, который будет отправлен при следующей периодической отправке. "
                "Агент вызывает этот инструмент после каждого ответа пользователю."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Актуальный текст summary."},
                },
                "required": ["text"],
            },
        ),
        types.Tool(
            name="stop_periodic_summary",
            description="Остановить фоновую периодическую отправку summary.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ── Обработка вызовов ─────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    # ── send_telegram_message ──────────────────────────────────────────────
    if name == "send_telegram_message":
        chat_id = arguments.get("chat_id", "").strip()
        text    = arguments.get("text", "").strip()
        if not chat_id or not text:
            return _err("Параметры 'chat_id' и 'text' обязательны.")
        logger.info("send_telegram_message → chat_id=%s text_len=%d", chat_id, len(text))
        result = await _send(chat_id, text)
        if "error" in result:
            logger.warning("send failed: %s", result["error"])
        else:
            logger.info("send ok, message_id=%s", result.get("message_id"))
        return _ok(result)

    # ── send_telegram_document ────────────────────────────────────────────
    if name == "send_telegram_document":
        chat_id   = arguments.get("chat_id", "").strip()
        file_path = arguments.get("file_path", "").strip()
        caption   = arguments.get("caption", "")
        if not chat_id or not file_path:
            return _err("Параметры 'chat_id' и 'file_path' обязательны.")
        logger.info("send_telegram_document → chat_id=%s file=%s", chat_id, file_path)
        result = await _send_document(chat_id, file_path, caption)
        if "error" in result:
            logger.warning("send_document failed: %s", result["error"])
        else:
            logger.info("send_document ok, message_id=%s", result.get("message_id"))
        return _ok(result)

    # ── start_periodic_summary ─────────────────────────────────────────────
    if name == "start_periodic_summary":
        chat_id  = arguments.get("chat_id", "").strip()
        interval = int(arguments.get("interval_seconds", 60))
        if not chat_id:
            return _err("Параметр 'chat_id' обязателен.")
        _periodic["chat_id"]  = chat_id
        _periodic["interval"] = max(interval, 10)   # минимум 10 секунд
        _start_task()
        logger.info(
            "start_periodic_summary: chat_id=%s interval=%ds",
            chat_id, _periodic["interval"],
        )
        return _ok({"ok": True, "chat_id": chat_id, "interval_seconds": _periodic["interval"]})

    # ── update_summary ─────────────────────────────────────────────────────
    if name == "update_summary":
        text = arguments.get("text", "").strip()
        if not text:
            return _err("Параметр 'text' обязателен.")
        _periodic["summary"] = text
        logger.debug("update_summary: summary_len=%d", len(text))
        return _ok({"ok": True, "summary_len": len(text)})

    # ── stop_periodic_summary ──────────────────────────────────────────────
    if name == "stop_periodic_summary":
        _stop_task()
        _periodic["summary"] = ""
        logger.info("stop_periodic_summary: задача остановлена")
        return _ok({"ok": True})

    return _err(f"Unknown tool: '{name}'")


def _ok(data: dict) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]


def _err(msg: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps({"error": msg}, ensure_ascii=False))]


# ── Точка входа ───────────────────────────────────────────────────────────────

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())