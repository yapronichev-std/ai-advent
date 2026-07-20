# Changelog

## v0.1.0 (2026-07-20)

Релиз добавляет множество новых функций: панель активности агента, File Assistant, Ассистенты поддержки и разработчика, Code Review, RAG с гибридным поиском и структурированным выводом, интеграцию с Ollama и удалёнными LLM, MCP серверы, модель памяти и Telegram-бот. Также исправлены критические баги с индексацией RAG, health check и блокирующими операциями.

**76 commits** in `initial..v0.1.0`

### ✨ Новое

- Добавлена панель активности агента — глобальный статус-бар снизу и лог событий
- Добавлены per-file события индексации RAG в панели активности
- Добавлена подсказка «как запустить Ollama» при ошибке индексации RAG
- Добавлен стриминг, edit_file, git diff по веткам, история сессий в File Assistant
- Добавлен File Assistant для проактивной работы с файлами
- Добавлен Ассистент поддержки пользователей
- Добавлена панель управления пользователями справа
- Добавлена вкладка Code Review с авто-ревью через LLM
- Добавлен Ассистент разработчика
- Добавлен SSE streaming для Remote LLM с fallback для reasoning_content
- Добавлена вкладка Remote LLM для чата с удалённым llama.cpp сервером
- Добавлены параметры Local LLM и поддержка HTML/MHTML RAG
- Подключён конвейер RAG поиска к вкладке Local LLM
- Добавлен переключатель локальных моделей, бейдж модели и время ответа
- Добавлена вкладка Local LLM с Ollama llama3.2:3b чатом
- Добавлен гибридный RAG поиск — keyword supplement, структурное слияние и закреплённые чанки
- Добавлено отображение источников RAG в сообщениях чата
- Добавлен структурированный RAG вывод с цитированием источников и защитой 'Я не знаю'
- Добавлена панель контрольных вопросов для сравнения режимов RAG
- Добавлен выбор модели и прямая поддержка DeepSeek API
- Добавлены RAG reranker, фильтр релевантности и переписывание запроса с 5-режимным сравнением
- Реализовано сравнение запросов с RAG и без
- Добавлен модуль RAG
- Добавлены две стратегии чанкинга с метаданными
- Добавлена панель RAG для загрузки документов
- Добавлен компонент RAG
- Реализованы длинные MCP инструменты
- Добавлена отправка файлов в Telegram бот
- Реализован MCP пайплайн
- Добавлена периодическая отправка сводки в Telegram бот
- Добавлен mcp-telegram-server
- Добавлено отображение результирующих диаграмм
- Добавлен MCP сервер UML диаграмм
- Интегрирован MCP сервер погоды
- Добавлены явные переходы состояний
- Добавлены инварианты
- Реализован state machine
- Глобальный системный промпт теперь редактируется через UI и хранится отдельно
- Добавлен веб-интерфейс для профилей пользователей
- Добавлены профили пользователей и персонализация на основе модели памяти
- Добавлена модель памяти (2 коммита)
- Добавлено хранение истории не более 10 сообщений, суммаризация каждые 10 сообщений
- Добавлен подсчёт токенов
- Добавлено сохранение/восстановление истории сообщений через JSON
- Добавлено 3 запроса на каждое сообщение пользователя с разными параметрами
- Добавлены параметры LLM — temperature, top_p, top_k
- Добавлен minimalchat
- Создана структура приложения и исправлены ошибки сборки

### 🐛 Исправления

- Убран имя индексируемого файла из бейджа RAG в шапке
- Спиннер гаснет после индексации — статус done всегда и поллинг после done
- Сброс hint при переходе в indexing
- Health check на asyncio вместо httpx и fail-fast в /project/stream
- Fail-fast при недоступной Ollama — health check перед индексацией
- Неблокирующий старт — RAG индексация в фоне и статус в UI
- Исправлено 'Argument list too long' в PR review workflow
- Добавлено разрешение pull-requests write для токена workflow
- Исправлены trailing whitespace в mcp_git_server
- Перемещён GitHub Actions workflow в корень репозитория
- Улучшен RAG поиск с keyword-boost и структурным слиянием чанков
- Использование структурного чанкинга и отключение переписывания запроса в чате
- Переключение модели на nvidia/nemotron-3-super-120b-a12b:free

### ♻️ Рефакторинг

- Унифицировано поле ввода на всех вкладках — стили, Enter, auto-grow, история

### 📖 Документация

- Обновлён Day 30 README с SSE streaming, reasoning_content fallback и миграцией на Qwen2.5-1.5B
- Добавлена запись Day 26 — вкладка Local LLM с Ollama и llama.cpp
- Добавлены Days 23-25 в README (выбор модели, структурированный RAG вывод, контрольные вопросы)
- Отредактирован README.md
- Добавлен CLAUDE.md
- Добавлен FirstAgent проект
- Добавлен new-feature.cmd
- Добавлен README.md

### 🔧 Обслуживание

- Merge pull request #1
- Инициализация проекта CycleCoach
- Перемещён README.md

<details>
<summary>Все 76 коммитов</summary>

- `8942c1a` fix: убрать имя индексируемого файла из бейджа RAG в шапке
- `3d083dd` feat: per-file события индексации RAG в панели активности
- `c840d8c` feat: панель активности агента — глобальный статус-бар снизу + лог событий
- `cb78558` fix: спиннер гаснет после индексации — статус done всегда + поллинг после done
- `6a258d5` fix: сбрасывать hint при переходе в indexing (иначе подсказка остаётся)
- `a8bfca9` fix: health check на asyncio вместо httpx + fail-fast в /project/stream
- `466acfc` feat: подсказка «как запустить Ollama» при ошибке индексации RAG
- `42f85a1` fix: fail-fast при недоступной Ollama — health check перед индексацией
- `674b4d8` fix: неблокирующий старт — RAG индексация в фоне + статус в UI
- `535692e` feat: стриминг, edit_file, git diff по веткам, история сессий в File Assistant
- `14f1251` refactor: унифицировать поле ввода на всех вкладках — стили, Enter, auto-grow, история
- `9bb00f0` feat: Day 34 — File Assistant для проактивной работы с файлами
- `17fdb03` fix: avoid 'Argument list too long' in PR review workflow
- `ae63529` feat: Day 33 — Ассистент поддержки пользователей
- `6739132` Merge pull request #1 from yapronichev-std/day32
- `5bab884` fix: add pull-requests write permission to workflow token
- `6813c88` fix: trailing whitespace cleanup in mcp_git_server
- `c814893` feat: вынести управление пользователями в отдельную панель справа
- `f03fae2` fix: move GitHub Actions workflow to repo root
- `59e73c8` feat: Day 32 — Вкладка Code Review с авто-ревью через LLM
- `1c58b37` feat: Day 31 — Ассистент разработчика
- `047d15d` docs: update Day 30 README with SSE streaming, reasoning_content fallback, and Qwen2.5-1.5B migration
- `a65b26e` feat: SSE streaming for Remote LLM + fallback for reasoning_content
- `3533e75` feat: add Remote LLM tab — chat with remote llama.cpp server via HTTP API
- `ed8c439` feat: Local LLM params + HTML/MHTML RAG support
- `240cdb1` feat: connect RAG retrieval pipeline to Local LLM tab
- `de0c3d3` docs: add Day 26 entry — Local LLM tab with Ollama + llama.cpp
- `f7e090c` feat: add local model switcher, model badge, and response time
- `272bd01` feat: add Local LLM tab with Ollama llama3.2:3b chat
- `0c3e638` feat: hybrid RAG retrieval — keyword supplement + structural merge + pinned chunks
- `233c9da` fix: improve RAG retrieval with keyword-boost and structural chunk merging
- `9f01f23` fix: use structural chunking + disable query rewrite in chat
- `dbe5b72` docs: add Days 23-25 to README (model selection, structured RAG output, control questions)
- `fcdc5b3` feat: display RAG sources in chat messages
- `117ae0a` Add structured RAG output format with source citations and "I don't know" guard
- `415479f` Add control questions panel to RAG tab for comparing modes against expected answers
- `d5eebd8` Add model selection dropdown and DeepSeek direct API support
- `a506b5b` Add RAG reranker, relevance filter, and query rewrite with 5-mode comparison
- `ce4b597` compare requests with / without RAG
- `af8c445` add rag module
- `f4d9fe2` add metadata two chunking strategies
- `9fdb3d4` RAG panel for uploading docs
- `3a826e2` RAG component added
- `08e1531` long flow mcp tools
- `3a57092` sending files to telegram bot
- `55e4ffe` implemeted mcp pipeline
- `8b0038e` switch model to nvidia/nemotron-3-super-120b-a12b:free
- `2598350` periodical sending summary to telegrem bot
- `6f6a90e` added mcp-telegram-server
- `95533be` display result diagrams
- `44e19f1` edit README.md
- `24b91b3` move README.md
- `cc1c5f9` save diagram to file
- `b922c5d` add uml diagram mcp server
- `c4cbcd6` integrate weather mcp
- `b2d820b` explicit state transitions
- `05d07e2` invariants
- `cd7b9b5` realization of state machine
- `6169852` global system prompt: editable via UI, stored separately
- `269fbce` web interface for user profiles
- `07dc91f` user profiles and personalization over memory model
- `7c5db29` memory model
- `1436c52` memory model
- `e62c710` storing history of no more than 10 messages, summary every 10 messages
- `cd9359c` accumulate tokens
- `e569ac5` feature calc tokens
- `622b1b8` store/restore message history feature by json
- `1b1ac14` add CLAUDE.md
- `10ab18e` add FirstAgent project
- `48a571a` add three requests for every user message, with different params
- `64e335c` add llm parameters - temperature, top_p, top_k
- `a6aa0c4` add minimalchat sources
- `0dacada` add new-feature.cmd
- `ef76408` created structure of application and fix build errors
- `d923414` init commit add CycleCoach blank application
- `32053b5` add README.md

</details>
