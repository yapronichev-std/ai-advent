"""
Ассистент поддержки пользователей.

Отвечает на вопросы о продукте, используя:
👉 RAG (FAQ + документация)
👉 Контекст пользователя/тикета из CRM
👉 MCP-интеграцию с CRM-сервером
"""

import json
import logging
import time
from typing import Optional

import httpx

from rag import RAGStore, rewrite_query, rerank_results

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

SUPPORT_SYSTEM_PROMPT = """Ты — ассистент поддержки пользователей. Твоя задача — помогать пользователям решать проблемы с продуктом.

Правила работы:
1. Внимательно изучи контекст пользователя (профиль, тикеты) и документацию (FAQ).
2. Отвечай персонализированно — обращайся к пользователю по имени, ссылайся на его тикеты.
3. Если проблема описана в FAQ — дай конкретные шаги по решению со ссылкой на источник.
4. Если проблема уникальна и не покрыта FAQ — предложи решение на основе контекста и лучших практик.
5. Если информации недостаточно — задай уточняющие вопросы.
6. Отвечай на русском языке, если пользователь пишет по-русски.

Формат ответа:
1. ANSWER — прямой ответ на вопрос.
2. CONTEXT — как учтён контекст пользователя/тикета.
3. FAQ — ссылки на документацию, если применимо.
4. NEXT STEPS — что делать дальше.
"""


class SupportAgent:
    """Ассистент поддержки с интеграцией CRM и RAG."""

    # ── Фразы положительной обратной связи (авто-закрытие тикета) ──────────
    _POSITIVE_FEEDBACK = [
        "спасибо", "помогло", "помогли", "работает", "заработало",
        "решило", "решили", "всё работает", "все работает",
        "отлично", "супер", "благодарю", "помог", "помогла",
        "разобрался", "разобралась", "проблема решена", "вопрос решён",
        "все ок", "всё ок", "ок спасибо", "thank you", "thanks",
        "that worked", "it works", "resolved", "fixed",
    ]

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-direct/deepseek-chat",
        deepseek_api_key: str = "",
        rag_store: Optional[RAGStore] = None,
        crm_client=None,  # MCPCRMClient
    ):
        self.api_key = api_key
        self.deepseek_api_key = deepseek_api_key
        self.model = model
        self.rag_store = rag_store
        self.crm_client = crm_client
        # ── Память диалогов: session_id → [{role, content, ticket_id, user_id}] ──
        self._sessions: dict[str, list[dict]] = {}

    def _get_session(self, session_id: str) -> list[dict]:
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        return self._sessions[session_id]

    def _detect_positive_feedback(self, text: str) -> bool:
        """Проверить, содержит ли сообщение пользователя положительную обратную связь."""
        text_lower = text.lower().strip()
        return any(phrase in text_lower for phrase in self._POSITIVE_FEEDBACK)

    async def answer_question(
        self,
        question: str,
        user_identifier: str = "",
        ticket_id: str = "",
        session_id: str = "default",
    ) -> dict:
        """
        Полный пайплайн ответа на вопрос поддержки.

        Args:
            question: вопрос пользователя
            user_identifier: имя, email или id пользователя (опционально)
            ticket_id: id конкретного тикета (опционально)

        Returns:
            {
                "answer": str,
                "user_context": dict | None,
                "ticket": dict | None,
                "rag_sources": list[dict],
                "rag_no_context": bool,
                "usage": dict,
                "elapsed_ms": int,
            }
        """
        t0 = time.monotonic()

        # ── 1. CRM: получить контекст пользователя ──────────────────────────
        user_context = None
        ticket = None

        if self.crm_client and ticket_id:
            try:
                result_json = await self.crm_client.call_tool(
                    "get_ticket", {"ticket_id": ticket_id}
                )
                result = json.loads(result_json)
                ticket = result.get("ticket")
                if ticket and not user_identifier:
                    user_identifier = ticket.get("user_id", "")
            except Exception as exc:
                logger.warning("[support] CRM get_ticket failed: %s", exc)

        if self.crm_client and user_identifier:
            try:
                # Сначала пробуем получить по id
                result_json = await self.crm_client.call_tool(
                    "get_user", {"user_id": user_identifier}
                )
                result = json.loads(result_json)
                if "error" not in result:
                    # Нашли — получаем полный контекст
                    ctx_json = await self.crm_client.call_tool(
                        "get_user_context", {"user_id": user_identifier}
                    )
                    ctx_result = json.loads(ctx_json)
                    user_context = ctx_result.get("context")
                else:
                    # Ищем по имени/email
                    sr_json = await self.crm_client.call_tool(
                        "search_users", {"query": user_identifier}
                    )
                    sr_result = json.loads(sr_json)
                    results = sr_result.get("results", [])
                    if results:
                        user = results[0]
                        ctx_json = await self.crm_client.call_tool(
                            "get_user_context", {"user_id": user["id"]}
                        )
                        ctx_result = json.loads(ctx_json)
                        user_context = ctx_result.get("context")
                        # Также получаем тикеты, если не задан конкретный
                        if not ticket:
                            for t in user_context.get("active_tickets", []):
                                ticket = t
                                break
            except Exception as exc:
                logger.warning("[support] CRM user lookup failed: %s", exc)

        # ── 2. RAG: поиск релевантной документации ──────────────────────────
        rag_sources: list[dict] = []
        rag_no_context = False

        if self.rag_store:
            try:
                search_query = rewrite_query(question, strategy="none")
                raw_results = await self.rag_store.retrieve(search_query, top_k=35)

                # ── Keyword supplement: extract all meaningful terms ──────────
                import re as _re
                kw_terms: list[str] = []

                # 1. Quoted phrases (exact match priority)
                for m in _re.finditer(r'[«"]([^»"]+)[»"]', question):
                    phrase = m.group(1).strip()
                    if len(phrase) >= 3:
                        kw_terms.append(phrase)

                # 2. CamelCase / technical identifiers (JC-Mobile, PKCS#11, etc.)
                tech_terms = _re.findall(r'[A-Z][a-z]+(?:[-_/][A-Za-z0-9]+)+|[A-Z]{2,}(?:\d+)?', question)
                for t in tech_terms:
                    if len(t) >= 3 and t.lower() not in [k.lower() for k in kw_terms]:
                        kw_terms.append(t)

                # 3. Russian/English words >= 4 chars (not stop words)
                from rag import _STOP_WORDS
                words = _re.findall(r'[a-zA-Zа-яёА-ЯЁ0-9_]{4,}', question.lower())
                for w in words:
                    if w not in _STOP_WORDS and w not in [k.lower() for k in kw_terms]:
                        kw_terms.append(w)

                if kw_terms:
                    kw_results = self.rag_store.retrieve_by_keywords(kw_terms, top_k=15)
                    if kw_results:
                        # Pull neighbor chunks from keyword-matched documents
                        extra_chunks: list[dict] = []
                        for kr in kw_results:
                            doc_id = kr.get("doc_id", "")
                            ci = kr.get("chunk_index", -1)
                            if doc_id and ci >= 0:
                                for offset in (1, 2, 3, -1):
                                    neighbor = self.rag_store.get_chunk_by_doc_index(doc_id, ci + offset)
                                    if neighbor:
                                        neighbor["score"] = kr["score"] - 0.02 * abs(offset)
                                        extra_chunks.append(neighbor)
                        # Pin keyword results at the top, bypassing MMR
                        seen = {r.get("chunk_id", "") for r in raw_results}
                        pinned_kw: list[dict] = []
                        for kr in kw_results + extra_chunks:
                            cid = kr.get("chunk_id", "")
                            if cid and cid not in seen:
                                kr["_pinned"] = True
                                pinned_kw.append(kr)
                                seen.add(cid)
                        raw_results = pinned_kw + raw_results
                        raw_results.sort(key=lambda r: r["score"], reverse=True)
                        logger.debug("[support] keyword supplement: %d terms → %d kw + %d neighbors, pool now %d",
                                     len(kw_terms), len(kw_results), len(extra_chunks), len(raw_results))

                # ── Boost FAQ/support documents so they rank above generic content ──
                FAQ_SOURCE_BOOST = 0.25
                for r in raw_results:
                    src = r.get("source", "")
                    if src.startswith("docs/support/"):
                        r["score"] = min(r["score"] + FAQ_SOURCE_BOOST, 1.0)
                        r["_faq_boosted"] = True
                        logger.debug("[support] FAQ boost: %s +%.2f → %.3f", src, FAQ_SOURCE_BOOST, r["score"])
                raw_results.sort(key=lambda r: r["score"], reverse=True)

                rerank = rerank_results(
                    raw_results, pre_k=30, post_k=10, threshold=0.25,
                    query=question,
                )
                final_results = rerank["results"]
                pinned_ids = {r.get("chunk_id") for r in final_results}
                for r in raw_results:
                    if r.get("_pinned") and r.get("chunk_id") not in pinned_ids:
                        final_results.append(r)
                rag_sources = final_results
                if not rag_sources and rerank["before_count"] > 0:
                    rag_no_context = True
            except Exception as exc:
                logger.warning("[support] RAG retrieval failed: %s", exc)

        # ── 3. История диалога ─────────────────────────────────────────────
        session = self._get_session(session_id)

        # Сохраняем сообщение пользователя
        session.append({"role": "user", "content": question})

        # ── 4. Построение сообщений ──────────────────────────────────────────
        messages = self._build_messages(
            question=question,
            user_context=user_context,
            ticket=ticket,
            rag_sources=rag_sources,
            rag_no_context=rag_no_context,
            history=session,
        )

        # ── 5. Вызов LLM ─────────────────────────────────────────────────────
        answer, usage = await self._call_api(messages)

        # Сохраняем ответ в историю
        session.append({"role": "assistant", "content": answer})
        # Ограничиваем историю 20 последними сообщениями
        if len(session) > 20:
            self._sessions[session_id] = session[-20:]

        elapsed_ms = round((time.monotonic() - t0) * 1000)

        # ── 6. Авто-закрытие тикета при положительной обратной связи ─────────
        ticket_closed = False
        if ticket_id and self._detect_positive_feedback(question):
            if self.crm_client:
                try:
                    close_msg = "Тикет закрыт автоматически: пользователь подтвердил решение проблемы."
                    await self.crm_client.call_tool("update_ticket", {
                        "ticket_id": ticket_id,
                        "status": "closed",
                        "message": close_msg,
                        "message_role": "support",
                    })
                    ticket_closed = True
                    # Обновляем ticket в ответе
                    if ticket:
                        ticket["status"] = "closed"
                    logger.info("[support] ticket %s auto-closed (positive feedback)", ticket_id)
                except Exception as exc:
                    logger.warning("[support] auto-close ticket failed: %s", exc)

        return {
            "answer": answer,
            "user_context": user_context,
            "ticket": ticket,
            "rag_sources": rag_sources,
            "rag_no_context": rag_no_context,
            "usage": usage,
            "elapsed_ms": elapsed_ms,
            "ticket_closed": ticket_closed,
        }

    def _build_messages(
        self,
        question: str,
        user_context: dict | None,
        ticket: dict | None,
        rag_sources: list[dict],
        rag_no_context: bool,
        history: list[dict] | None = None,
    ) -> list[dict]:
        """Построить сообщения для LLM с учётом CRM-контекста, RAG и истории диалога."""
        messages: list[dict] = []

        # 1. System prompt
        messages.append({"role": "system", "content": SUPPORT_SYSTEM_PROMPT})

        # 2. CRM-контекст пользователя
        if user_context:
            user = user_context.get("user", {})
            summary = user_context.get("summary", {})
            active = user_context.get("active_tickets", [])

            crm_block_parts = [
                "[CRM — Контекст пользователя]",
                f"Имя: {user.get('name', '—')}",
                f"Email: {user.get('email', '—')}",
                f"Компания: {user.get('company') or '—'}",
                f"Тариф: {user.get('plan', '—')}",
                f"Статус: {user.get('status', '—')}",
                f"Теги: {', '.join(user.get('tags', [])) or '—'}",
                f"Дата регистрации: {user.get('created_at', '—')}",
                f"Последний вход: {user.get('last_login', '—')}",
                "",
                f"Всего тикетов: {summary.get('total_tickets', 0)}",
                f"Открытых: {summary.get('open_tickets', 0)}",
                f"Закрытых: {summary.get('closed_tickets', 0)}",
            ]

            if active:
                crm_block_parts.append("\nАктивные тикеты:")
                for t in active:
                    crm_block_parts.append(
                        f"  - [{t['id']}] {t['subject']} "
                        f"(статус: {t['status']}, приоритет: {t['priority']}, "
                        f"категория: {t['category']})"
                    )

            messages.append({"role": "system", "content": "\n".join(crm_block_parts)})

        # 3. Конкретный тикет
        if ticket:
            ticket_parts = [
                "[Тикет — детали]",
                f"ID: {ticket.get('id', '—')}",
                f"Тема: {ticket.get('subject', '—')}",
                f"Статус: {ticket.get('status', '—')}",
                f"Приоритет: {ticket.get('priority', '—')}",
                f"Категория: {ticket.get('category', '—')}",
                f"Создан: {ticket.get('created_at', '—')}",
                f"Описание: {ticket.get('description', '—')}",
                "",
                "Сообщения в тикете:",
            ]
            for msg in ticket.get("messages", []):
                role_label = "👤 Пользователь" if msg["role"] == "user" else "🎧 Поддержка"
                ticket_parts.append(
                    f"  [{msg.get('at', '?')}] {role_label}: {msg['text']}"
                )
            messages.append({"role": "system", "content": "\n".join(ticket_parts)})

        # 4. RAG-контекст
        if rag_no_context and self.rag_store:
            messages.append({"role": "system", "content": self.rag_store.build_no_context_instructions()})
        elif rag_sources and self.rag_store:
            rag_block = self.rag_store.build_context_block(rag_sources)
            if rag_block:
                messages.append({"role": "system", "content": rag_block})
                messages.append({"role": "system", "content": self.rag_store.build_rag_output_instructions()})

        # 5. История диалога (предыдущие сообщения)
        if history:
            # Не дублируем последнее сообщение (оно уже в history)
            for msg in history[:-1]:
                messages.append(msg)

        # 6. Текущий вопрос
        messages.append({"role": "user", "content": question})

        return messages

    async def _call_api(self, messages: list[dict]) -> tuple[str, dict]:
        """Вызвать LLM API (поддерживает OpenRouter и DeepSeek)."""
        if self.model.startswith("deepseek-direct/"):
            api_url = DEEPSEEK_URL
            auth_key = self.deepseek_api_key
            actual_model = self.model[len("deepseek-direct/"):]
        elif self.model.startswith("deepseek/"):
            api_url = OPENROUTER_URL
            auth_key = self.api_key
            actual_model = self.model
        else:
            api_url = OPENROUTER_URL
            auth_key = self.api_key
            actual_model = self.model

        headers = {
            "Authorization": f"Bearer {auth_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": actual_model,
            "messages": messages,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(6):
                try:
                    response = await client.post(api_url, headers=headers, json=payload)
                except Exception:
                    if attempt == 5:
                        raise
                    await __import__("asyncio").sleep(2 ** attempt)
                    continue

                if response.status_code == 429:
                    wait = min(2 ** attempt, 60)
                    logger.warning("[support] 429, retrying in %ds (attempt %d/6)", wait, attempt + 1)
                    await __import__("asyncio").sleep(wait)
                    continue
                response.raise_for_status()
                break

            data = response.json()
            usage = data.get("usage", {})
            answer = data["choices"][0]["message"]["content"]
            return answer, usage
