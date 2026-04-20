"""
Скрипт для ручного тестирования telegram_mcp_server.

Использование (из корня проекта):
    TELEGRAM_BOT_TOKEN=<токен> python mcp_telegram_server/test_telegram_mcp.py <chat_id> <текст>

Пример:
    TELEGRAM_BOT_TOKEN=123:ABC python mcp_telegram_server/test_telegram_mcp.py 987654321 "Привет из MCP!"
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path, чтобы найти mcp_telegram_client
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_telegram_client import MCPTelegramClient


async def main() -> None:
    if len(sys.argv) < 3:
        print("Использование: python mcp_telegram_server/test_telegram_mcp.py <chat_id> <текст сообщения>")
        sys.exit(1)

    chat_id = sys.argv[1]
    text = " ".join(sys.argv[2:])

    client = MCPTelegramClient()
    print("Подключаюсь к MCP-серверу...")
    await client.connect()

    print(f"Доступные инструменты: {[t['function']['name'] for t in client.tools]}")
    print(f"Отправляю сообщение в chat_id={chat_id}: {text!r}")

    result = await client.call_tool("send_telegram_message", {"chat_id": chat_id, "text": text})
    print(f"Результат: {result}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())