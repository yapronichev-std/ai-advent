"""
MCP-сервер для отправки сообщений в Telegram через Bot API.

Транспорт: stdio (стандарт для MCP-клиентов).

Инструменты:
  - send_telegram_message: отправить текстовое сообщение в указанный чат.
"""

import asyncio
import json
import logging
import os
import sys

import httpx
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

app = Server("mcp-telegram")


def _get_token() -> str | None:
    """Вернуть токен из переменной окружения."""
    return os.environ.get("TELEGRAM_BOT_TOKEN")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="send_telegram_message",
            description=(
                "Отправить текстовое сообщение в Telegram-чат через Bot API. "
                "Требует наличия переменной окружения TELEGRAM_BOT_TOKEN."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "ID чата или username (например, '123456789' или '@mychannel').",
                    },
                    "text": {
                        "type": "string",
                        "description": "Текст отправляемого сообщения.",
                    },
                },
                "required": ["chat_id", "text"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "send_telegram_message":
        return [types.TextContent(type="text", text=json.dumps({"error": f"Unknown tool: '{name}'"}))]

    chat_id = arguments.get("chat_id", "").strip()
    text = arguments.get("text", "").strip()

    if not chat_id or not text:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "Параметры 'chat_id' и 'text' обязательны и не должны быть пустыми."}),
        )]

    token = _get_token()
    if not token:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "Переменная окружения TELEGRAM_BOT_TOKEN не задана."}),
        )]

    url = TELEGRAM_API_BASE.format(token=token)
    payload = {"chat_id": chat_id, "text": text}

    logger.info("send_telegram_message → chat_id=%s text_len=%d", chat_id, len(text))

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            data = response.json()
    except httpx.TimeoutException:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": "Таймаут при обращении к Telegram API."}),
        )]
    except httpx.RequestError as exc:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"Сетевая ошибка: {exc}"}),
        )]

    if not data.get("ok"):
        error_code = data.get("error_code")
        description = data.get("description", "Неизвестная ошибка")
        logger.warning("Telegram API error %s: %s", error_code, description)
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"Telegram API [{error_code}]: {description}"}),
        )]

    message_id = data["result"]["message_id"]
    logger.info("Сообщение доставлено, message_id=%s", message_id)
    return [types.TextContent(
        type="text",
        text=json.dumps({"ok": True, "message_id": message_id}),
    )]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())