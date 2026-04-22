"""
Пайплайн построения UML-диаграмм:
  Пользовательский запрос → mcp-search → OpenRouter → mcp-drawio → mcp-telegram

Используется из ChatAgent для запросов, классифицированных как «диаграммные».
"""

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Инструкция для анализа через mcp-search
_SEARCH_INSTRUCTION = (
    "Извлеки из найденных материалов:\n"
    "1. Перечень объектов (акторов, сущностей, систем, компонентов)\n"
    "2. Основные шаги процесса и их последовательность\n"
    "3. Альтернативные потоки и возможные исключения\n"
    "4. Связи и зависимости между объектами\n"
    "5. Современные нотации UML (если применимо)\n\n"
    "Представь результат в виде структурированного текста, "
    "пригодного для построения UML-диаграммы."
)

# Системный промпт для генерации аргументов drawio
_DRAWIO_SYSTEM_PROMPT = """\
Ты — эксперт по UML и инструменту draw.io.
Твоя задача: на основе пользовательского запроса и аналитических данных составить \
аргументы для вызова одного из инструментов генерации диаграммы.

Доступные инструменты:
1. generate_class_diagram      — классы, атрибуты, методы, связи (inheritance, association, dependency, realization, aggregation, composition)
2. generate_component_diagram  — компоненты и зависимости (dependency, association, usage, realization)
3. generate_use_case_diagram   — актёры, варианты использования, связи (association, include, extend, generalization)

Ответ верни СТРОГО в формате JSON (без markdown, без пояснений):
{
  "tool": "<название инструмента>",
  "arguments": { <аргументы согласно схеме инструмента> },
  "summary": "<одно предложение: что построено>"
}

Для generate_class_diagram:
  "classes": [{"name": "...", "attributes": [...], "methods": [...]}]
  "relations": [{"from": "...", "to": "...", "type": "..."}]

Для generate_component_diagram:
  "components": [{"name": "..."}]
  "relations": [{"from": "...", "to": "...", "type": "dependency", "label": "..."}]

Для generate_use_case_diagram:
  "actors": [{"name": "..."}]
  "use_cases": [{"name": "..."}]
  "relations": [{"from": "...", "to": "...", "type": "association"}]

Будь максимально конкретным — чем детальнее описание, тем лучше результат.
"""


class DiagramPipeline:
    """Оркестрирует пайплайн: поиск → LLM → drawio → Telegram."""

    def __init__(
        self,
        api_key: str,
        model: str,
        search_client=None,      # MCPSearchClient | None
        drawio_client=None,      # MultiMCPClient | MCPDrawioClient | None
        telegram_client=None,    # MCPTelegramClient | None
        telegram_chat_id: str = "",
        fallback_model: str = "openai/gpt-4o",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.fallback_model = fallback_model
        self.search_client = search_client
        self.drawio_client = drawio_client
        self.telegram_client = telegram_client
        self.telegram_chat_id = telegram_chat_id

    # ── Публичный метод ───────────────────────────────────────────────────────

    async def execute(self, user_query: str) -> tuple[str, list[str]]:
        """
        Выполняет полный пайплайн для запроса на диаграмму.

        Returns:
            (response_text, diagram_urls)
        """
        t_start = time.monotonic()
        logger.info("[pipeline] START  query=%r", user_query[:80])

        # Шаг 1: поиск и анализ
        analysis = await self._step_search(user_query)

        # Шаг 2: генерация аргументов для drawio через OpenRouter
        drawio_args, tool_name, summary = await self._step_refine(
            user_query, analysis, model=self.model
        )

        # Шаг 3: построение диаграммы
        diagram_result = await self._step_drawio(tool_name, drawio_args)
        if diagram_result is None:
            # fallback: другая модель
            logger.warning("[pipeline] drawio failed, retry with fallback model")
            drawio_args2, tool_name2, summary2 = await self._step_refine(
                user_query, analysis, model=self.fallback_model
            )
            diagram_result = await self._step_drawio(tool_name2, drawio_args2)
            if diagram_result is not None:
                tool_name, summary = tool_name2, summary2

        diagram_urls: list[str] = []
        if diagram_result:
            if url := diagram_result.get("diagram_url"):
                diagram_urls.append(url)

        # Шаг 4: отправка в Telegram
        tg_status = await self._step_telegram(user_query, diagram_result, summary)

        elapsed = round((time.monotonic() - t_start) * 1000)
        logger.info("[pipeline] DONE  elapsed=%dms  urls=%s", elapsed, diagram_urls)

        if diagram_result:
            response = (
                f"Диаграмма готова и отправлена в Telegram-бот. {tg_status}\n"
                f"Тип: **{tool_name}**\n"
                f"{summary}"
            )
        else:
            response = (
                "Не удалось построить диаграмму (ошибка mcp-drawio). "
                "Попробуйте уточнить запрос."
            )

        return response, diagram_urls

    # ── Шаги пайплайна ────────────────────────────────────────────────────────

    async def _step_search(self, user_query: str) -> str:
        """Шаг 1: поиск и анализ через mcp-search. Таймаут 45 сек (15 поиск + 30 анализ)."""
        if not self.search_client:
            logger.info("[pipeline] search_client отсутствует, пропускаем поиск")
            return "Поиск не выполнен (search-клиент не подключён)."

        search_query = user_query + " best practices UML 2024 2025"
        logger.info("[pipeline] step1: search  query=%r", search_query[:80])
        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self.search_client.call_tool(
                    "search_and_analyze",
                    {
                        "query": search_query,
                        "analysis_instruction": _SEARCH_INSTRUCTION,
                        "num_results": 5,
                    },
                ),
                timeout=45.0,
            )
            elapsed = round((time.monotonic() - t0) * 1000)
            logger.info("[pipeline] step1 done  elapsed=%dms  len=%d", elapsed, len(raw))

            data = json.loads(raw)
            analysis = data.get("analysis", raw)
            results_count = data.get("results_count", 0)
            if results_count == 0:
                logger.warning("[pipeline] поиск не вернул результатов — строим без доп. анализа")
            return analysis

        except asyncio.TimeoutError:
            logger.warning("[pipeline] step1 timeout (45s)")
            return "Поиск не дал результатов (таймаут). Используй только исходный запрос."
        except Exception as exc:
            logger.warning("[pipeline] step1 error: %s", exc)
            return f"Поиск не дал результатов ({exc}). Используй только исходный запрос."

    async def _step_refine(
        self, user_query: str, analysis: str, model: str
    ) -> tuple[dict, str, str]:
        """
        Шаг 2: генерация структурированных аргументов для drawio через OpenRouter.
        Таймаут 30 сек.

        Returns:
            (arguments_dict, tool_name, summary)
        """
        logger.info("[pipeline] step2: refine  model=%s", model)
        t0 = time.monotonic()

        user_prompt = (
            f"Пользовательский запрос:\n\"{user_query}\"\n\n"
            f"Аналитические данные из поиска:\n{analysis}"
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": _DRAWIO_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            content = data["choices"][0]["message"]["content"].strip()
            elapsed = round((time.monotonic() - t0) * 1000)
            logger.info("[pipeline] step2 done  elapsed=%dms", elapsed)

            parsed = self._extract_json(content)
            tool_name = parsed.get("tool", "generate_component_diagram")
            arguments = parsed.get("arguments", {})
            summary = parsed.get("summary", "UML-диаграмма построена.")
            return arguments, tool_name, summary

        except Exception as exc:
            logger.error("[pipeline] step2 error: %s", exc)
            return self._fallback_component_args(user_query), "generate_component_diagram", "Диаграмма (fallback)."

    async def _step_drawio(self, tool_name: str, arguments: dict) -> Optional[dict]:
        """Шаг 3: вызов mcp-drawio. Таймаут 60 сек."""
        if not self.drawio_client:
            logger.warning("[pipeline] drawio_client отсутствует")
            return None

        logger.info("[pipeline] step3: drawio  tool=%s", tool_name)
        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self.drawio_client.call_tool(tool_name, arguments),
                timeout=60.0,
            )
            elapsed = round((time.monotonic() - t0) * 1000)
            logger.info("[pipeline] step3 done  elapsed=%dms", elapsed)

            result = json.loads(raw)
            if "error" in result:
                logger.error("[pipeline] drawio error: %s", result["error"])
                return None
            return result

        except asyncio.TimeoutError:
            logger.error("[pipeline] step3 timeout (60s)")
            return None
        except Exception as exc:
            logger.error("[pipeline] step3 exception: %s", exc)
            return None

    async def _step_telegram(
        self, user_query: str, diagram_result: Optional[dict], summary: str
    ) -> str:
        """Шаг 4: отправка файла диаграммы в Telegram. Таймаут 30 сек."""
        if not self.telegram_client or not self.telegram_chat_id:
            logger.info("[pipeline] Telegram не настроен, пропускаем")
            return "(Telegram не настроен)"

        logger.info("[pipeline] step4: telegram  chat_id=%s", self.telegram_chat_id)
        t0 = time.monotonic()

        if not diagram_result:
            # Диаграмма не построена — шлём текстовое уведомление
            text = f"По запросу «{user_query[:100]}» диаграмма не была построена (ошибка mcp-drawio)."
            try:
                await asyncio.wait_for(
                    self.telegram_client.call_tool(
                        "send_telegram_message",
                        {"chat_id": self.telegram_chat_id, "text": text},
                    ),
                    timeout=30.0,
                )
            except Exception as exc:
                logger.warning("[pipeline] step4 text send error: %s", exc)
            return ""

        saved_path = diagram_result.get("saved_path", "")
        filename = diagram_result.get("filename", "diagram.drawio")
        caption = (
            f"UML-диаграмма по запросу:\n«{user_query[:200]}»\n\n{summary}"
        )

        try:
            raw = await asyncio.wait_for(
                self.telegram_client.call_tool(
                    "send_telegram_document",
                    {
                        "chat_id": self.telegram_chat_id,
                        "file_path": saved_path,
                        "caption": caption,
                    },
                ),
                timeout=30.0,
            )
            elapsed = round((time.monotonic() - t0) * 1000)

            result = json.loads(raw)
            if "error" in result:
                logger.warning("[pipeline] step4 send_document error: %s", result["error"])
                return f"(Telegram: {result['error']} — файл сохранён локально: {filename})"

            logger.info("[pipeline] step4 done  elapsed=%dms  message_id=%s", elapsed, result.get("message_id"))
            return ""

        except asyncio.TimeoutError:
            logger.warning("[pipeline] step4 telegram timeout (30s)")
            return f"(Telegram: таймаут — файл сохранён локально: {filename})"
        except Exception as exc:
            logger.warning("[pipeline] step4 telegram error: %s", exc)
            return f"(Telegram: ошибка отправки — файл сохранён локально: {filename})"

    # ── Вспомогательные методы ────────────────────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Извлекает первый JSON-объект из строки (LLM может добавить markdown)."""
        # Убираем markdown-блоки ```json ... ```
        if "```" in text:
            start = text.find("{", text.find("```"))
        else:
            start = text.find("{")
        end = text.rfind("}") + 1

        if start == -1 or end == 0:
            raise ValueError(f"JSON не найден в ответе LLM: {text[:200]}")

        return json.loads(text[start:end])

    @staticmethod
    def _fallback_component_args(query: str) -> dict:
        """Минимальные аргументы компонентной диаграммы при ошибке LLM."""
        words = [w for w in query.split() if len(w) > 3][:6]
        components = [{"name": w.capitalize()} for w in words] or [{"name": "System"}]
        return {"components": components, "relations": []}