"""
Release Pipeline — автоматизация релиза через /release.

Использование:
    pipeline = ReleasePipeline(mcp_client, telegram_client, chat_id, api_key, model)
    result = await pipeline.execute()
    # result = {"version": "v1.3.0", "tag": "v1.3.0", "changelog_path": "docs/CHANGELOG.md",
    #           "commits": [...], "categories": {...}, "summary": "...",
    #           "telegram_sent": True/False}
"""

import json
import logging
import os
from pathlib import Path

import httpx

from activity import activity

logger = logging.getLogger(__name__)

# ── LLM prompt для классификации коммитов ──────────────────────────────────────

CLASSIFY_PROMPT = """Ты — release manager. Проанализируй список коммитов и подготовь changelog.

## Коммиты
{commits_text}

## Задача
1. Классифицируй каждый коммит по типу: feat, fix, refactor, docs, chore, test, style, perf
2. Сгруппируй связанные изменения
3. Определи suggested_version: major (ломающие изменения), minor (новый функционал), patch (исправления)
4. Напиши summary — краткое (1-2 предложения) описание релиза на русском

## Ответ — строго JSON без маркдауна:
{{
  "suggested_version": "minor",
  "categories": {{
    "feat": ["Добавлена панель активности агента", "..."],
    "fix": ["Спиннер гаснет после индексации", "..."],
    "refactor": [],
    "docs": [],
    "chore": [],
    "test": [],
    "style": [],
    "perf": []
  }},
  "summary": "Релиз добавляет панель активности и исправляет баги с индексацией RAG."
}}

Используй русский язык для описаний. Не добавляй markdown-форматирование.
Отвечай ТОЛЬКО JSON-объектом, без пояснений."""


def _resolve_api(model: str) -> tuple[str, str]:
    """Return (api_url, provider) for a model id."""
    if model.startswith("openrouter/") or model.startswith("openai/"):
        return "https://openrouter.ai/api/v1/chat/completions", "openrouter"
    if model.startswith("deepseek"):
        return "https://api.deepseek.com/v1/chat/completions", "deepseek"
    # fallback: treat everything as openrouter
    return "https://openrouter.ai/api/v1/chat/completions", "openrouter"


def format_release_result(result: dict) -> str:
    """Форматирует результат релиза для отображения в чате."""
    version = result.get("version", "?")
    tag = result.get("tag", "?")
    total = len(result.get("commits", []))
    cats = result.get("categories", {})
    summary = result.get("summary", "")
    telegram = "✅" if result.get("telegram_sent") else "❌ (не настроен)"
    pushed = "✅" if result.get("pushed") else "❌"

    lines = [
        f"## 🚀 Релиз {version}",
        "",
        f"**{summary}**" if summary else "",
        "",
        f"📦 Коммитов: **{total}**  |  🏷 Тег: `{tag}`  |  🚀 GitHub: {pushed}  |  ✈️ Telegram: {telegram}",
        "",
        "### Изменения",
    ]

    labels = {
        "feat": "✨ Новое",
        "fix": "🐛 Исправления",
        "refactor": "♻️ Рефакторинг",
        "docs": "📖 Документация",
        "chore": "🔧 Обслуживание",
        "test": "✅ Тесты",
        "style": "💄 Стиль",
        "perf": "⚡ Производительность",
    }

    for key, label in labels.items():
        items = cats.get(key, [])
        if items:
            lines.append(f"\n**{label}**")
            for item in items:
                lines.append(f"- {item}")

    lines.append(f"\n📄 Changelog: `docs/CHANGELOG.md`")
    return "\n".join(lines)


# ── ReleasePipeline ────────────────────────────────────────────────────────────


class ReleasePipeline:
    def __init__(
        self,
        mcp_client,
        telegram_client=None,
        telegram_chat_id: str = "",
        api_key: str = "",
        deepseek_api_key: str = "",
        model: str = "openrouter/anthropic/claude-sonnet-4.5",
    ):
        self.mcp = mcp_client
        self.telegram = telegram_client
        self.telegram_chat_id = telegram_chat_id
        self.api_key = api_key
        self.deepseek_api_key = deepseek_api_key
        self.model = model

    async def execute(self) -> dict:
        """Основной пайплайн релиза."""
        activity.emit("release", "Запуск release pipeline...", agent="release")

        # 1. Получить последний тег
        last_tag = await self._get_last_tag()

        # 2. Получить коммиты
        commits = await self._get_commits(last_tag)
        if not commits:
            activity.emit("release", "Нет новых коммитов — релиз не требуется", agent="release")
            return {
                "version": last_tag or "v0.0.0",
                "tag": None,
                "changelog_path": None,
                "commits": [],
                "categories": {},
                "summary": "Нет новых коммитов с последнего релиза.",
                "telegram_sent": False,
            }

        total = len(commits)
        activity.emit("release", f"Анализ {total} коммитов через LLM...", agent="release")

        # 3. Классифицировать коммиты через LLM
        classification = await self._classify_commits(commits)
        suggested = classification.get("suggested_version", "patch")
        categories = classification.get("categories", {})
        summary = classification.get("summary", "")

        # 4. Определить версию
        version = self._determine_version(last_tag, suggested)
        activity.emit("release", f"Версия определена: {version}", agent="release",
                      detail={"version": version, "from": last_tag, "suggested": suggested})

        # 5. Сгенерировать changelog
        changelog = self._generate_changelog(commits, categories, summary, version, last_tag)

        # 6. Записать CHANGELOG.md
        await self._write_changelog(changelog)
        activity.emit("release", "CHANGELOG.md записан", agent="release",
                      detail={"path": "docs/CHANGELOG.md"})

        # 6a. Закоммитить CHANGELOG.md
        await self._commit_changelog(version)
        activity.emit("release", "CHANGELOG.md закоммичен", agent="release")

        # 7. Создать тег (на коммите с CHANGELOG.md)
        await self._create_tag(version, summary)
        activity.emit("release", f"Тег {version} создан", agent="release",
                      detail={"tag": version})

        # 8. Запушить тег на GitHub
        pushed = await self._push_tag(version)
        activity.emit("release", f"Тег {version} запушен на GitHub" if pushed else "Пуш тега не удался",
                      agent="release", detail={"tag": version, "pushed": pushed})

        # 9. Telegram-уведомление
        telegram_sent = await self._notify_telegram(version, summary, categories)

        return {
            "version": version,
            "tag": version,
            "changelog_path": "docs/CHANGELOG.md",
            "commits": commits,
            "categories": categories,
            "summary": summary,
            "telegram_sent": telegram_sent,
            "pushed": pushed,
        }

    # ── Private helpers ─────────────────────────────────────────────────────────

    async def _get_last_tag(self) -> str | None:
        try:
            result_json = await self.mcp.call_tool("git_last_tag", {})
            result = json.loads(result_json)
            return result.get("tag")
        except Exception as e:
            logger.warning("[release] git_last_tag failed: %s", e)
            return None

    async def _get_commits(self, last_tag: str | None) -> list[dict]:
        args: dict = {"max_count": 100}
        if last_tag:
            args["range"] = f"{last_tag}..HEAD"
        try:
            result_json = await self.mcp.call_tool("git_log", args)
            result = json.loads(result_json)
            return result.get("commits", [])
        except Exception as e:
            logger.error("[release] git_log failed: %s", e)
            return []

    async def _classify_commits(self, commits: list[dict]) -> dict:
        """Отправить коммиты в LLM для классификации."""
        commits_text = "\n".join(
            f"{c['hash']} {c['message']}" for c in commits
        )
        prompt = CLASSIFY_PROMPT.format(commits_text=commits_text)

        messages = [
            {"role": "user", "content": prompt},
        ]

        response_text, _ = await self._call_llm(messages)
        try:
            # Убираем возможные markdown-обёртки ```json ... ```
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("[release] LLM returned non-JSON, using fallback: %.200s", response_text)
            return {
                "suggested_version": "patch",
                "categories": {"feat": [], "fix": [], "refactor": [], "docs": [], "chore": [], "test": [], "style": [], "perf": []},
                "summary": "Релиз (автоматический)",
            }

    def _determine_version(self, last_tag: str | None, suggested: str) -> str:
        """Вычислить новую версию на основе последнего тега и suggested_version."""
        if not last_tag:
            return "v0.1.0"
        # Парсим v1.2.3 → (1, 2, 3)
        clean = last_tag.lstrip("v")
        try:
            parts = [int(p) for p in clean.split(".")]
        except ValueError:
            return "v0.1.0"
        while len(parts) < 3:
            parts.append(0)
        major, minor, patch = parts[0], parts[1], parts[2]
        if suggested == "major":
            major += 1
            minor = 0
            patch = 0
        elif suggested == "minor":
            minor += 1
            patch = 0
        else:
            patch += 1
        return f"v{major}.{minor}.{patch}"

    def _generate_changelog(
        self,
        commits: list[dict],
        categories: dict,
        summary: str,
        version: str,
        last_tag: str | None,
    ) -> str:
        """Сгенерировать Markdown-текст CHANGELOG.md."""
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        range_str = f"{last_tag}..{version}" if last_tag else f"initial..{version}"
        total = len(commits)

        lines = [
            f"# Changelog",
            "",
            f"## {version} ({today})",
            "",
            f"{summary}",
            "",
            f"**{total} commits** in `{range_str}`",
            "",
        ]

        labels = {
            "feat": "### ✨ Новое",
            "fix": "### 🐛 Исправления",
            "refactor": "### ♻️ Рефакторинг",
            "docs": "### 📖 Документация",
            "chore": "### 🔧 Обслуживание",
            "test": "### ✅ Тесты",
            "style": "### 💄 Стиль",
            "perf": "### ⚡ Производительность",
        }

        for key, label in labels.items():
            items = categories.get(key, [])
            if items:
                lines.append(label)
                lines.append("")
                for item in items:
                    lines.append(f"- {item}")
                lines.append("")

        # Добавляем полный список коммитов в конце
        lines.append("<details>")
        lines.append(f"<summary>Все {total} коммитов</summary>")
        lines.append("")
        for c in commits:
            lines.append(f"- `{c['hash']}` {c['message']}")
        lines.append("")
        lines.append("</details>")

        return "\n".join(lines) + "\n"

    async def _write_changelog(self, changelog_text: str) -> None:
        """Записать CHANGELOG.md через MCP write_file."""
        try:
            result_json = await self.mcp.call_tool("write_file", {
                "path": "docs/CHANGELOG.md",
                "content": changelog_text,
            })
            result = json.loads(result_json)
            if not result.get("ok"):
                logger.error("[release] write_file failed: %s", result)
        except Exception as e:
            logger.error("[release] write_file error: %s", e)
            raise

    async def _create_tag(self, version: str, message: str) -> None:
        """Создать git tag."""
        tag_message = message[:500] if message else f"Release {version}"
        try:
            result_json = await self.mcp.call_tool("git_tag", {
                "name": version,
                "message": tag_message,
            })
            result = json.loads(result_json)
            if not result.get("ok"):
                logger.error("[release] git_tag failed: %s", result)
        except Exception as e:
            logger.error("[release] git_tag error: %s", e)
            raise

    async def _commit_changelog(self, version: str) -> None:
        """Закоммитить CHANGELOG.md через git_add + git_commit."""
        # git add docs/CHANGELOG.md
        add_result = await self.mcp.call_tool("git_add", {"paths": ["docs/CHANGELOG.md"]})
        add = json.loads(add_result)
        if not add.get("ok"):
            logger.warning("[release] git_add failed, continuing: %s", add.get("stderr", ""))
        # git commit
        result_json = await self.mcp.call_tool("git_commit", {"message": f"chore: update CHANGELOG.md for {version}"})
        commit = json.loads(result_json)
        if commit.get("ok"):
            logger.info("[release] committed CHANGELOG.md: %s", commit.get("commit", "?"))
        else:
            logger.warning("[release] git_commit failed (maybe nothing to commit): %s", commit.get("stderr", ""))

    async def _push_tag(self, version: str) -> bool:
        """Запушить тег на GitHub remote. Возвращает True если успешно."""
        try:
            result_json = await self.mcp.call_tool("git_push", {"ref": version})
            result = json.loads(result_json)
            ok = result.get("ok", False)
            if not ok:
                logger.warning("[release] git_push failed: %s", result.get("stderr", ""))
            return ok
        except Exception as e:
            logger.warning("[release] git_push error: %s", e)
            return False

    async def _notify_telegram(
        self, version: str, summary: str, categories: dict
    ) -> bool:
        """Отправить уведомление в Telegram. Возвращает True если отправлено."""
        if not self.telegram or not self.telegram_chat_id:
            return False

        total_feats = len(categories.get("feat", []))
        total_fixes = len(categories.get("fix", []))

        text = (
            f"🚀 Релиз {version}\n\n"
            f"{summary}\n\n"
            f"✨ Новое: {total_feats}  |  🐛 Исправления: {total_fixes}\n"
            f"📄 Changelog: docs/CHANGELOG.md"
        )

        try:
            result_json = await self.telegram.call_tool("send_telegram_message", {
                "chat_id": self.telegram_chat_id,
                "text": text,
            })
            logger.info("[release] Telegram notification sent")
            return True
        except Exception as e:
            logger.warning("[release] Telegram notification failed: %s", e)
            return False

    async def _call_llm(self, messages: list[dict]) -> tuple[str, dict]:
        """Один вызов LLM без инструментов. Возвращает (text, usage)."""
        api_url, provider = _resolve_api(self.model)
        auth_key = self.deepseek_api_key if provider == "deepseek" else self.api_key
        actual_model = self.model.split("/", 1)[1] if "/" in self.model else self.model

        headers = {
            "Authorization": f"Bearer {auth_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": actual_model,
            "messages": messages,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(api_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        text = choice["message"]["content"]
        usage = data.get("usage", {})
        return text, usage
