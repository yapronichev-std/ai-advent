"""
MCP-сервер для веб-поиска и анализа через OpenRouter.

Транспорт: stdio (стандарт MCP).

Вместо внешнего поискового API используется OpenRouter с параметром
`plugins: [{"id": "web"}]`, который добавляет веб-поиск к любой совместимой
модели. Альтернативно можно указать онлайн-модель (например,
`perplexity/sonar-pro` или `openai/gpt-4o:online`).

Переменные окружения:
  OPENROUTER_API_KEY  — ключ OpenRouter (обязателен, уже должен быть в .env)
  SEARCH_MODEL        — модель для поиска и анализа
                        По умолчанию: perplexity/sonar-pro
                        Можно использовать любую онлайн-модель OpenRouter, например:
                          perplexity/sonar-pro
                          openai/gpt-4o:online
                          anthropic/claude-3.5-sonnet:online
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

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_SEARCH_MODEL = "perplexity/sonar-pro"

app = Server("mcp-search")


async def _search_and_analyze(query: str, instruction: str, num_results: int) -> str:
    """
    Выполняет поиск и анализ через OpenRouter.

    Использует параметр `plugins: [{"id": "web"}]` для добавления веб-поиска
    к модели. Если модель уже онлайн (например, perplexity/sonar-pro),
    плагин игнорируется без ошибок.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY не задан")

    model = os.environ.get("SEARCH_MODEL") or _DEFAULT_SEARCH_MODEL

    prompt = (
        f"Выполни веб-поиск по запросу: «{query}»\n"
        f"Используй не менее {num_results} актуальных источников.\n\n"
        f"Затем выполни следующую задачу анализа:\n{instruction}"
    )

    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "plugins": [{"id": "web"}],
    }

    logger.info("[search] model=%s  query=%r", model, query[:80])

    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"]


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_and_analyze",
            description=(
                "Ищет актуальную информацию в интернете через OpenRouter (web-плагин) "
                "и анализирует результаты по заданной инструкции. "
                "Не требует отдельного API-ключа поискового сервиса."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос",
                    },
                    "analysis_instruction": {
                        "type": "string",
                        "description": "Инструкция: что именно извлечь из найденных материалов",
                    },
                    "num_results": {
                        "type": "integer",
                        "default": 5,
                        "description": "Желаемое количество источников (подсказка для модели)",
                    },
                },
                "required": ["query", "analysis_instruction"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "search_and_analyze":
        raise ValueError(f"Неизвестный инструмент: '{name}'")

    query: str = arguments["query"]
    instruction: str = arguments["analysis_instruction"]
    num_results: int = int(arguments.get("num_results", 5))

    try:
        analysis = await _search_and_analyze(query, instruction, num_results)
        payload = {"analysis": analysis, "results_count": num_results, "query": query}
    except Exception as exc:
        logger.error("[search] ошибка: %s", exc)
        payload = {
            "analysis": f"Поиск недоступен: {exc}. Используй только базовые знания модели.",
            "results_count": 0,
            "query": query,
        }

    return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())