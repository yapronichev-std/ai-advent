"""
CodeReviewAgent — оркестрирует автоматическое ревью кода.

Принимает diff и метаданные PR, извлекает релевантный контекст через RAG,
вызывает LLM и возвращает структурированное ревью с категоризацией проблем.

Переиспользует: RAGStore, MCP-инструменты git, паттерн API-вызовов ChatAgent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, asdict, field
from typing import Optional

import httpx

from rag import RAGStore, rewrite_query, rerank_results

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = "deepseek-direct/deepseek-chat"
MAX_DIFF_CHARS = 80_000  # обрезаем слишком большие диффы


# ── Data classes ────────────────────────────────────────────────────────────────


@dataclass
class ReviewIssue:
    """Одна найденная проблема в коде."""
    severity: str          # "critical" | "major" | "minor"
    file_path: str         # относительный путь к файлу (или "" для проекта)
    line_number: int | None  # номер строки (или None)
    description: str       # описание проблемы
    suggestion: str        # конкретное предложение по исправлению
    category: str          # "bug" | "architecture" | "security" | "performance" | "best_practice"

    def to_dict(self) -> dict:
        """Ручная сериализация — надёжнее asdict для вложенных структур."""
        return {
            "severity": self.severity,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "description": self.description,
            "suggestion": self.suggestion,
            "category": self.category,
        }


@dataclass
class ReviewResult:
    """Полный результат ревью."""
    summary: dict = field(default_factory=lambda: {
        "overall_assessment": "",
        "review_quality": "medium",
        "total_issues": 0,
    })
    bugs: list[ReviewIssue] = field(default_factory=list)
    architecture_issues: list[ReviewIssue] = field(default_factory=list)
    security_issues: list[ReviewIssue] = field(default_factory=list)
    performance_issues: list[ReviewIssue] = field(default_factory=list)
    recommendations: list[ReviewIssue] = field(default_factory=list)
    rag_sources: list[dict] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    diff_snippet: str = ""
    model_used: str = ""
    elapsed_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        """Собрать результат в словарь, готовый к JSON-сериализации."""
        return {
            "summary": dict(self.summary),
            "bugs": [i.to_dict() for i in self.bugs],
            "architecture_issues": [i.to_dict() for i in self.architecture_issues],
            "security_issues": [i.to_dict() for i in self.security_issues],
            "performance_issues": [i.to_dict() for i in self.performance_issues],
            "recommendations": [i.to_dict() for i in self.recommendations],
            "rag_sources": list(self.rag_sources),
            "changed_files": list(self.changed_files),
            "diff_snippet": self.diff_snippet,
            "model_used": self.model_used,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
        }


# ── Review system prompt ────────────────────────────────────────────────────────


REVIEW_SYSTEM_PROMPT = """\
Ты — эксперт по код-ревью с многолетним опытом. Твоя задача — проанализировать предоставленный diff и найти:

1. **БАГИ** (bugs): Ошибки, которые могут привести к некорректной работе, падению, логическим сбоям или неправильным результатам.
2. **ПРОБЛЕМЫ АРХИТЕКТУРЫ** (architecture): Нарушения SOLID, неправильное разделение ответственности, избыточная связанность, циклические зависимости.
3. **ПРОБЛЕМЫ БЕЗОПАСНОСТИ** (security): Инъекции, XSS, недостаточная валидация, утечка чувствительных данных, небезопасная работа с файлами.
4. **ПРОБЛЕМЫ ПРОИЗВОДИТЕЛЬНОСТИ** (performance): Неэффективные алгоритмы, N+1 запросы, избыточные вычисления, блокирующие операции.
5. **УЛУЧШЕНИЯ** (recommendations): Стиль кода, best practices, дублирование, читаемость, тестируемость.

## Формат ответа

Ответь СТРОГО в формате JSON (без markdown-обрамления, без пояснений вне JSON):

{
  "summary": {
    "overall_assessment": "краткая общая оценка изменений (1-3 предложения)",
    "review_quality": "high|medium|low",
    "total_issues": N
  },
  "bugs": [
    {
      "severity": "critical|major|minor",
      "file_path": "путь/к/файлу.py",
      "line_number": 42,
      "description": "описание проблемы",
      "suggestion": "конкретное предложение по исправлению"
    }
  ],
  "architecture_issues": [...],
  "security_issues": [...],
  "performance_issues": [...],
  "recommendations": [...]
}

## Важные правила

- Если проблем в категории нет — верни пустой массив: []
- Для каждого issue ОБЯЗАТЕЛЬНО указывай severity, file_path, description и suggestion
- line_number может быть null, если проблема не привязана к конкретной строке
- Будь конкретным: ссылайся на реальные строки кода из diff
- Предлагай КОНКРЕТНЫЕ исправления, а не общие советы
- Учитывай контекст документации проекта, если она предоставлена
- Не выдумывай проблемы, которых нет в коде
- Если diff пустой или тривиальный — честно скажи об этом в overall_assessment
- Пиши description и suggestion на русском языке, если код и комментарии на русском
"""


# ── CodeReviewAgent ────────────────────────────────────────────────────────────


def _resolve_model_id(model_id: str) -> tuple[str, str]:
    """Return (provider, actual_model_name) for a model_id."""
    if model_id.startswith("deepseek-direct/"):
        return "deepseek", model_id[len("deepseek-direct/"):]
    return "openrouter", model_id


class CodeReviewAgent:
    """Оркестрирует автоматическое ревью кода с использованием RAG и LLM."""

    def __init__(
        self,
        api_key: str,
        deepseek_api_key: str = "",
        model: str = DEFAULT_MODEL,
        rag_store: RAGStore | None = None,
        mcp_client=None,  # MultiMCPClient | None
    ):
        self.api_key = api_key
        self.deepseek_api_key = deepseek_api_key
        self.model = model
        self.rag_store = rag_store
        self.mcp_client = mcp_client

    # ── Public API ─────────────────────────────────────────────────────────

    async def review_pr(
        self,
        pr_title: str = "",
        pr_description: str = "",
        base_branch: str = "main",
        head_branch: str = "",
        diff_text: str = "",
        changed_files: list[str] | None = None,
        user_id: str = "review",
    ) -> ReviewResult:
        """Выполнить ревью PR по переданному diff.

        Args:
            pr_title: Заголовок PR
            pr_description: Описание PR
            base_branch: Базовая ветка (обычно main)
            head_branch: Ветка с изменениями
            diff_text: Текст git diff
            changed_files: Список изменённых файлов
            user_id: Идентификатор пользователя (для логирования)

        Returns:
            ReviewResult со структурированным ревью
        """
        t0 = time.monotonic()
        changed_files = changed_files or []

        if not diff_text.strip():
            return ReviewResult(
                summary={
                    "overall_assessment": "Diff пуст — нечего ревьюировать.",
                    "review_quality": "low",
                    "total_issues": 0,
                },
                changed_files=changed_files,
                model_used=self.model,
                elapsed_ms=0,
            )

        # 1. Собрать контекст из PR
        context = self._gather_pr_context(
            pr_title, pr_description, base_branch, head_branch,
            diff_text, changed_files,
        )

        # 2. Извлечь RAG-контекст
        rag_sources: list[dict] = []
        if self.rag_store and self.rag_store.count() > 0:
            try:
                rag_sources = await self._retrieve_rag_context(context)
            except Exception as exc:
                logger.warning("[review] RAG retrieval failed: %s", exc)

        # 3. Построить промпт и вызвать LLM
        messages = self._build_review_prompt(context, rag_sources)
        response_text, usage = await self._call_api(messages)

        # 4. Распарсить ответ
        result = self._parse_response(response_text, diff_text, changed_files)

        elapsed_ms = round((time.monotonic() - t0) * 1000)
        result.rag_sources = rag_sources
        result.changed_files = changed_files
        result.diff_snippet = diff_text[:2000]
        result.model_used = self.model
        result.elapsed_ms = elapsed_ms

        logger.info(
            "[review] completed in %dms — %d issues found (%d bugs, %d arch, %d sec, %d perf, %d rec)",
            elapsed_ms,
            result.summary.get("total_issues", 0),
            len(result.bugs),
            len(result.architecture_issues),
            len(result.security_issues),
            len(result.performance_issues),
            len(result.recommendations),
        )

        return result

    async def review_current_branch(
        self,
        base_branch: str = "main",
        user_id: str = "review",
    ) -> ReviewResult:
        """Выполнить ревью текущей рабочей ветки через MCP-инструменты git.

        Собирает unstaged + staged diff, статус и список изменённых файлов.
        """
        if not self.mcp_client:
            return ReviewResult(
                summary={
                    "overall_assessment": "MCP-клиент git недоступен — невозможно собрать diff.",
                    "review_quality": "low",
                    "total_issues": 0,
                },
                model_used=self.model,
                error="MCP git client not connected",
            )

        t0 = time.monotonic()

        try:
            diff_text, changed_files, branch_info = await self._get_current_diff()
        except Exception as exc:
            logger.exception("[review] Failed to get local diff")
            return ReviewResult(
                summary={
                    "overall_assessment": f"Ошибка получения diff: {exc}",
                    "review_quality": "low",
                    "total_issues": 0,
                },
                model_used=self.model,
                error=str(exc),
                elapsed_ms=round((time.monotonic() - t0) * 1000),
            )

        if not diff_text.strip():
            return ReviewResult(
                summary={
                    "overall_assessment": "Рабочее дерево чистое — нет изменений для ревью.",
                    "review_quality": "low",
                    "total_issues": 0,
                },
                changed_files=changed_files,
                model_used=self.model,
                elapsed_ms=round((time.monotonic() - t0) * 1000),
            )

        branch_name = branch_info.get("current_branch", "unknown")
        pr_title = f"Local changes on {branch_name}"
        pr_description = f"Uncommitted changes on branch '{branch_name}' (base: {base_branch})"

        result = await self.review_pr(
            pr_title=pr_title,
            pr_description=pr_description,
            base_branch=base_branch,
            head_branch=branch_name,
            diff_text=diff_text,
            changed_files=changed_files,
            user_id=user_id,
        )

        return result

    # ── Context gathering ──────────────────────────────────────────────────

    def _gather_pr_context(
        self,
        pr_title: str,
        pr_description: str,
        base_branch: str,
        head_branch: str,
        diff_text: str,
        changed_files: list[str],
    ) -> dict:
        """Разобрать diff и метаданные PR в структурированный контекст."""
        # Обрезаем слишком большой diff
        if len(diff_text) > MAX_DIFF_CHARS:
            diff_text = diff_text[:MAX_DIFF_CHARS] + "\n... [diff truncated]"

        # Извлекаем файлы из diff, если не переданы явно
        if not changed_files:
            changed_files = list(set(
                m.group(1) for m in re.finditer(
                    r'^diff --git a/(.+?) b/(.+?)$', diff_text, re.MULTILINE
                )
            ))
            # Если паттерн diff --git не сработал, пробуем +++
            if not changed_files:
                changed_files = [
                    m.group(1).lstrip('b/') for m in re.finditer(
                        r'^\+\+\+ b/(.+)$', diff_text, re.MULTILINE
                    )
                ]

        # Статистика: строки добавлены/удалены
        additions = len(re.findall(r'^\+(?!\+\+)', diff_text, re.MULTILINE))
        deletions = len(re.findall(r'^-(?!---)', diff_text, re.MULTILINE))

        # Группировка diff по файлам
        diff_by_file: dict[str, str] = {}
        file_blocks = re.split(r'^(?=diff --git)', diff_text, flags=re.MULTILINE)
        for block in file_blocks:
            if not block.strip():
                continue
            match = re.search(r'^diff --git a/(.+?) b/(.+?)$', block, re.MULTILINE)
            if match:
                fname = match.group(1)
                diff_by_file[fname] = block.strip()

        # Определяем технологии по расширениям файлов
        extensions = {f.rsplit('.', 1)[-1] if '.' in f else '' for f in changed_files}
        technologies = {
            '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
            '.html': 'HTML', '.css': 'CSS', '.java': 'Java', '.go': 'Go',
            '.rs': 'Rust', '.cpp': 'C++', '.c': 'C', '.rb': 'Ruby',
            '.php': 'PHP', '.sql': 'SQL', '.yaml': 'YAML', '.yml': 'YAML',
            '.json': 'JSON', '.md': 'Markdown', '.toml': 'TOML',
        }
        detected_techs = [tech for ext, tech in technologies.items() if ext in extensions]

        return {
            "pr_title": pr_title,
            "pr_description": pr_description,
            "base_branch": base_branch,
            "head_branch": head_branch,
            "diff_text": diff_text,
            "changed_files": changed_files,
            "additions": additions,
            "deletions": deletions,
            "lines_changed": additions + deletions,
            "diff_by_file": diff_by_file,
            "technologies": detected_techs,
        }

    async def _retrieve_rag_context(self, context: dict) -> list[dict]:
        """Извлечь релевантный контекст из RAG по файлам и технологиям."""
        if not self.rag_store:
            return []

        changed_files = context.get("changed_files", [])
        technologies = context.get("technologies", [])
        pr_description = context.get("pr_description", "")
        pr_title = context.get("pr_title", "")

        all_results: list[dict] = []

        # ── Семантический поиск по описанию PR ────────────────────────
        search_text = f"{pr_title} {pr_description} {' '.join(technologies)}".strip()
        if search_text:
            try:
                query = rewrite_query(search_text, strategy="keywords")
                semantic_results = await self.rag_store.retrieve(query, top_k=15)
                all_results.extend(semantic_results)
            except Exception as exc:
                logger.debug("[review] semantic RAG search failed: %s", exc)

        # ── Keyword-поиск по именам изменённых файлов ──────────────────
        if changed_files:
            # Ищем по именам файлов (без расширения) и по названиям директорий
            search_terms: list[str] = []
            for f in changed_files:
                name = f.rsplit('/', 1)[-1] if '/' in f else f
                # Имя файла без расширения
                stem = name.rsplit('.', 1)[0] if '.' in name else name
                if len(stem) >= 3:
                    search_terms.append(stem)
                # Родительская директория
                if '/' in f:
                    parent = f.rsplit('/', 1)[0].rsplit('/', 1)[-1]
                    if len(parent) >= 3:
                        search_terms.append(parent)

            # Убираем дубликаты
            unique_terms = list(dict.fromkeys(search_terms))[:10]

            if unique_terms:
                try:
                    kw_results = self.rag_store.retrieve_by_keywords(unique_terms, top_k=10)
                    all_results.extend(kw_results)
                except Exception as exc:
                    logger.debug("[review] keyword RAG search failed: %s", exc)

        if not all_results:
            return []

        # ── Дедупликация по chunk_id ──────────────────────────────────
        seen: set[str] = set()
        deduped: list[dict] = []
        for r in all_results:
            cid = r.get("chunk_id", "")
            if cid and cid not in seen:
                seen.add(cid)
                deduped.append(r)

        # ── Реранкинг ─────────────────────────────────────────────────
        try:
            rerank = rerank_results(
                deduped,
                pre_k=25,
                post_k=12,
                threshold=0.2,
                use_mmr=True,
                query=search_text,
            )
            return rerank["results"]
        except Exception:
            # Сортируем по score и берём top-10
            deduped.sort(key=lambda r: r.get("score", 0), reverse=True)
            return deduped[:10]

    # ── Prompt building ────────────────────────────────────────────────────

    def _build_review_prompt(
        self,
        context: dict,
        rag_sources: list[dict],
    ) -> list[dict]:
        """Построить список сообщений для LLM."""
        messages: list[dict] = []

        # 1. Системный промпт ревью
        messages.append({"role": "system", "content": REVIEW_SYSTEM_PROMPT})

        # 2. RAG-контекст (документация проекта)
        if rag_sources and self.rag_store:
            rag_block = self.rag_store.build_context_block(rag_sources)
            if rag_block:
                messages.append({"role": "system", "content": rag_block})
                messages.append({"role": "system", "content": (
                    "[RAG CONTEXT INSTRUCTIONS]\n"
                    "Выше приведены релевантные фрагменты документации и кода проекта. "
                    "Используй их для понимания архитектуры и принятых в проекте практик. "
                    "Если изменения в diff противоречат документации — отметь это как архитектурную проблему. "
                    "Ссылайся на источники из RAG-контекста, когда это уместно."
                )})

        # 3. Метаданные PR
        pr_title = context.get("pr_title", "")
        pr_description = context.get("pr_description", "")
        base_branch = context.get("base_branch", "main")
        head_branch = context.get("head_branch", "")

        meta_lines = ["[PR INFORMATION]"]
        if pr_title:
            meta_lines.append(f"Title: {pr_title}")
        if pr_description:
            meta_lines.append(f"Description: {pr_description}")
        if head_branch:
            meta_lines.append(f"Branch: {head_branch} → {base_branch}")

        meta_lines.append(f"Files changed: {', '.join(context.get('changed_files', []))}")
        meta_lines.append(
            f"Stats: +{context.get('additions', 0)} / -{context.get('deletions', 0)} "
            f"({context.get('lines_changed', 0)} total lines)"
        )
        if context.get("technologies"):
            meta_lines.append(f"Technologies: {', '.join(context['technologies'])}")

        messages.append({"role": "system", "content": "\n".join(meta_lines)})

        # 4. Сам diff
        diff_text = context.get("diff_text", "")
        diff_block = (
            "[CODE DIFF FOR REVIEW]\n"
            "Ниже приведён git diff для ревью. Проанализируй каждое изменение.\n\n"
            f"{diff_text}"
        )
        messages.append({"role": "user", "content": diff_block})

        # 5. Инструкция для пользовательского сообщения
        messages.append({"role": "user", "content": (
            "Выполни код-ревью предоставленных изменений. "
            "Найди баги, архитектурные проблемы, уязвимости безопасности, "
            "проблемы производительности и дай рекомендации по улучшению. "
            "Верни результат СТРОГО в формате JSON, как указано в system prompt."
        )})

        return messages

    # ── LLM API call ───────────────────────────────────────────────────────

    async def _call_api(self, messages: list[dict]) -> tuple[str, dict]:
        """Вызвать LLM API (OpenRouter или DeepSeek).

        Переиспользует паттерн из ChatAgent._call_api: маршрутизация,
        rate-limit retries, без tool calling.
        """
        provider, actual_model = _resolve_model_id(self.model)

        if provider == "deepseek":
            api_url = DEEPSEEK_URL
            auth_key = self.deepseek_api_key
        else:
            api_url = OPENROUTER_URL
            auth_key = self.api_key

        headers = {
            "Authorization": f"Bearer {auth_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": actual_model,
            "messages": messages,
            "temperature": 0.3,   # низкая температура для более стабильного JSON
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            for attempt in range(5):
                response = await client.post(api_url, headers=headers, json=payload)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait = int(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                    wait = min(wait, 60)
                    logger.warning("[review] 429 rate limit, retrying in %ds (attempt %d/5)", wait, attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                break
            else:
                raise RuntimeError("API rate limit: exceeded retries (429)")

            data = response.json()
            usage = data.get("usage", {})

            if "choices" not in data or not data["choices"]:
                err_msg = data.get("error", {}).get("message") or str(data)
                logger.error("[review] API response missing 'choices': %s", data)
                raise RuntimeError(f"API error: {err_msg}")

            return data["choices"][0]["message"]["content"], usage

    # ── Response parsing ───────────────────────────────────────────────────

    def _parse_response(
        self,
        raw_text: str,
        diff_text: str = "",
        changed_files: list[str] | None = None,
    ) -> ReviewResult:
        """Извлечь JSON из ответа LLM и преобразовать в ReviewResult."""
        changed_files = changed_files or []

        # 1. Пытаемся извлечь JSON из ответа
        json_text = self._extract_json(raw_text)

        if not json_text:
            return ReviewResult(
                summary={
                    "overall_assessment": "Не удалось распарсить ответ модели — ответ не содержит валидного JSON.",
                    "review_quality": "low",
                    "total_issues": 0,
                },
                error=f"Failed to parse JSON from response: {raw_text[:500]}",
                diff_snippet=diff_text[:2000],
                changed_files=changed_files,
            )

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as exc:
            # Пробуем исправить частые проблемы
            try:
                # Убираем trailing commas
                fixed = re.sub(r',\s*}', '}', json_text)
                fixed = re.sub(r',\s*]', ']', fixed)
                data = json.loads(fixed)
            except json.JSONDecodeError:
                return ReviewResult(
                    summary={
                        "overall_assessment": f"Ответ модели содержит некорректный JSON: {exc}",
                        "review_quality": "low",
                        "total_issues": 0,
                    },
                    error=f"JSON parse error: {exc}",
                    diff_snippet=diff_text[:2000],
                    changed_files=changed_files,
                )

        # 2. Извлечь summary
        summary_data = data.get("summary", {})
        summary = {
            "overall_assessment": summary_data.get("overall_assessment", "Ревью завершено."),
            "review_quality": summary_data.get("review_quality", "medium"),
            "total_issues": summary_data.get("total_issues", 0),
        }

        # 3. Распарсить каждую категорию
        def _parse_issues(raw_list: list, default_category: str) -> list[ReviewIssue]:
            issues: list[ReviewIssue] = []
            for item in (raw_list or []):
                if not isinstance(item, dict):
                    continue
                issues.append(ReviewIssue(
                    severity=item.get("severity", "minor"),
                    file_path=item.get("file_path", ""),
                    line_number=item.get("line_number"),
                    description=item.get("description", ""),
                    suggestion=item.get("suggestion", ""),
                    category=item.get("category", default_category),
                ))
            return issues

        bugs = _parse_issues(data.get("bugs", []), "bug")
        architecture_issues = _parse_issues(data.get("architecture_issues", []), "architecture")
        security_issues = _parse_issues(data.get("security_issues", []), "security")
        performance_issues = _parse_issues(data.get("performance_issues", []), "performance")
        recommendations = _parse_issues(data.get("recommendations", []), "best_practice")

        # Пересчитать total_issues
        actual_total = (
            len(bugs) + len(architecture_issues) + len(security_issues) +
            len(performance_issues) + len(recommendations)
        )
        if summary["total_issues"] == 0 and actual_total > 0:
            summary["total_issues"] = actual_total

        return ReviewResult(
            summary=summary,
            bugs=bugs,
            architecture_issues=architecture_issues,
            security_issues=security_issues,
            performance_issues=performance_issues,
            recommendations=recommendations,
            diff_snippet=diff_text[:2000],
            changed_files=changed_files,
        )

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """Извлечь JSON из текста: убрать markdown-ограждение, найти { ... }."""
        if not text:
            return None

        # Убираем ```json ... ``` обрамление
        cleaned = re.sub(r'^```(?:json)?\s*', '', text.strip())
        cleaned = re.sub(r'\s*```$', '', cleaned)

        # Ищем JSON-объект: от первой { до последней }
        start = cleaned.find('{')
        if start == -1:
            return None
        end = cleaned.rfind('}')
        if end == -1 or end <= start:
            return None

        return cleaned[start:end + 1]

    # ── Git diff gathering ─────────────────────────────────────────────────

    async def _get_current_diff(self) -> tuple[str, list[str], dict]:
        """Собрать diff и список файлов через MCP-инструменты git.

        Returns:
            (combined_diff, changed_files, branch_info)
        """
        import json as _json

        diff_parts: list[str] = []
        all_files: set[str] = set()

        # Unstaged diff
        try:
            result = await self.mcp_client.call_tool("get_git_diff", {"staged": False})
            data = _json.loads(result)
            if data.get("diff") and not data.get("is_empty"):
                diff_parts.append(data["diff"])
        except Exception as exc:
            logger.warning("[review] get_git_diff (unstaged) failed: %s", exc)

        # Staged diff
        try:
            result = await self.mcp_client.call_tool("get_git_diff", {"staged": True})
            data = _json.loads(result)
            if data.get("diff") and not data.get("is_empty"):
                diff_parts.append(data["diff"])
        except Exception as exc:
            logger.warning("[review] get_git_diff (staged) failed: %s", exc)

        # Статус для списка файлов
        try:
            result = await self.mcp_client.call_tool("get_git_status", {})
            status_data = _json.loads(result)
            for entry in status_data.get("staged", []):
                all_files.add(entry.get("file", ""))
            for entry in status_data.get("unstaged", []):
                all_files.add(entry.get("file", ""))
            for f in status_data.get("untracked", []):
                all_files.add(f)
        except Exception as exc:
            logger.warning("[review] get_git_status failed: %s", exc)

        # Информация о ветке
        branch_info: dict = {}
        try:
            result = await self.mcp_client.call_tool("get_git_branch", {})
            branch_info = _json.loads(result)
        except Exception as exc:
            logger.warning("[review] get_git_branch failed: %s", exc)

        combined_diff = "\n".join(diff_parts)
        changed_files = sorted(f for f in all_files if f)

        return combined_diff, changed_files, branch_info
