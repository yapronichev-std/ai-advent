# ai-advent

Учебный AI-агент с веб-интерфейсом на базе FastAPI + OpenRouter.

## Проект: FirstAgent

Минималистичный чат-агент с памятью, инвариантами, профилями пользователей и интеграцией MCP-серверов.

### Быстрый старт

```bash
cp .env.example .env          # вписать OPENROUTER_API_KEY
pip install -r requirements.txt
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Или на Windows: `run.bat`. Интерфейс доступен по адресу `http://localhost:8000`.

---

## История доработок

### Day 17 — MCP-сервер генерации UML-диаграмм (draw.io)

Реализован MCP-сервер `mcp_drawio_server`, который генерирует UML-диаграммы в формате **draw.io XML** (`.drawio`). Сервер встроен в FirstAgent через MCP-клиент по той же схеме, что и погодный сервер.

#### Новые файлы

| Файл | Назначение |
|---|---|
| `mcp_drawio_server/server.py` | MCP-сервер (stdio), регистрирует три инструмента |
| `mcp_drawio_server/tools.py` | Обработчики инструментов, оркестрируют валидацию и генерацию |
| `mcp_drawio_server/drawio_builder.py` | Генерация draw.io XML через `xml.etree.ElementTree` |
| `mcp_drawio_server/models.py` | Pydantic-модели входных данных (поддержка поля `from` через alias) |
| `mcp_drawio_server/layout.py` | Авторасстановка элементов по сетке, когда `x`/`y` не заданы |
| `mcp_drawio_server/requirements.txt` | Зависимости сервера (`mcp`, `pydantic`) |
| `mcp_drawio_client.py` | MCP-клиент для drawio-сервера (запускает subprocess, аналог `mcp_weather.py`) |
| `mcp_multi.py` | `MultiMCPClient` — объединяет несколько MCP-клиентов в единый интерфейс |

#### Изменённые файлы

- **`main.py`** — lifespan создаёт `MultiMCPClient([MCPWeatherClient(), MCPDrawioClient()])` вместо одного клиента
- **`requirements.txt`** — добавлен пакет `mcp`

#### Инструменты сервера

**`generate_class_diagram`**
Принимает список классов (имя, атрибуты, методы, опционально родитель) и список связей.
Возвращает XML диаграммы классов с swimlane-блоками и стрелками наследования / агрегации / зависимости и др.

**`generate_component_diagram`**
Принимает список компонентов и связей между ними.
Возвращает XML диаграммы компонентов (`shape=component`).

**`generate_use_case_diagram`**
Принимает акторов, прецеденты и связи (`association`, `include`, `extend`, `generalization`).
Возвращает XML диаграммы вариантов использования (акторы — `shape=mxgraph.uml.actor`, прецеденты — эллипсы).

Каждый инструмент возвращает:
```json
{
  "drawio_xml": "<mxfile ...>...</mxfile>",
  "filename": "class_diagram_20260417.drawio",
  "base64": "<base64-строка>"
}
```

#### Пример вызова

```json
{
  "name": "generate_class_diagram",
  "arguments": {
    "classes": [
      {"name": "User", "attributes": ["id: int", "name: str"], "methods": ["login()", "logout()"]},
      {"name": "Admin", "inherits": "User", "methods": ["deleteUser()"]}
    ],
    "relations": [
      {"from": "Admin", "to": "User", "type": "inheritance"}
    ]
  }
}
```

#### Архитектурные решения

- **Транспорт** — stdio (стандарт MCP); сервер запускается как дочерний процесс через `StdioServerParameters`.
- **Авторасстановка** — если `x`/`y` не указаны, `layout.apply_grid_layout` расставляет элементы по сетке с настраиваемым шагом.
- **XML** — генерируется через стандартный `xml.etree.ElementTree`, сторонних зависимостей не требуется.
- **MultiMCPClient** — агрегирует инструменты нескольких серверов; `agent.py` не менялся (duck typing).

---

### Day 18 — MCP-сервер поиска и пайплайн «поиск → диаграмма → Telegram»

Добавлен `mcp_search_server` и полный автоматический пайплайн для запросов на построение диаграмм: агент сам находит актуальные практики, генерирует диаграмму и отправляет её в Telegram.

#### Новые файлы

| Файл | Назначение |
|---|---|
| `mcp_search_server/server.py` | MCP-сервер (stdio) с инструментом `search_and_analyze` — поиск через Brave/SerpAPI + анализ через OpenRouter |
| `mcp_search_client.py` | MCP-клиент для search-сервера (запускает subprocess, аналог `mcp_drawio_client.py`) |
| `diagram_pipeline.py` | Класс `DiagramPipeline` — оркестрирует 4-шаговый пайплайн |

#### Изменённые файлы

- **`agent.py`** — добавлены параметр `diagram_pipeline`, метод `_classify_as_diagram` и маршрутизация в `send_message`
- **`main.py`** — lifespan подключает `MCPSearchClient`, создаёт `DiagramPipeline`
- **`.env.example`** — новые переменные для поиска и пайплайна

#### Пайплайн (для запросов «построй диаграмму...»)

```
Пользовательский запрос
        │
        ▼
_classify_as_diagram()        ← LLM: YES/NO, таймаут 10 с
        │ YES
        ▼
mcp-search: search_and_analyze    ← Brave/SerpAPI + OpenRouter, таймаут 45 с
        │                           fallback: продолжить без поиска
        ▼
OpenRouter: генерация JSON-аргументов для drawio    ← таймаут 30 с
        │                           fallback: DRAWIO_FALLBACK_MODEL
        ▼
mcp-drawio: generate_*_diagram    ← таймаут 60 с
        │                           retry с другой моделью при ошибке
        ▼
mcp-telegram: send_telegram_message    ← таймаут 30 с
        │                               fallback: файл сохранён локально
        ▼
Ответ пользователю: «Диаграмма готова и отправлена в Telegram»
```

Для запросов без ключевого слова «диаграмма» поведение агента не изменилось.

#### Инструмент mcp-search

**`search_and_analyze(query, analysis_instruction, num_results=5)`**

Использует OpenRouter с параметром `plugins: [{"id": "web"}]`, который добавляет веб-поиск к любой совместимой модели. Отдельный API-ключ поискового сервиса не нужен — достаточно уже имеющегося `OPENROUTER_API_KEY`.

Рекомендуется использовать онлайн-модели:
- `perplexity/sonar-pro` — встроенный поиск Perplexity (по умолчанию)
- `openai/gpt-4o:online` — GPT-4o + web-плагин OpenRouter
- `anthropic/claude-3.5-sonnet:online`

#### Новые переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `SEARCH_MODEL` | `perplexity/sonar-pro` | Онлайн-модель OpenRouter для поиска и анализа |
| `DRAWIO_FALLBACK_MODEL` | `openai/gpt-4o` | Резервная модель при ошибке mcp-drawio |

#### Архитектурные решения

- **Пайплайн — код, не tool-calling**: шаги выполняются явным кодом в `DiagramPipeline`, а не через LLM tool-choice. Это даёт предсказуемость и соблюдение таймаутов.
- **Классификация отделена от основного потока**: `_classify_as_diagram` делает лёгкий LLM-вызов без истории, не загрязняя контекст агента.
- **`MCPSearchClient` зарегистрирован в lifespan** для единообразного lifecycle (connect/disconnect), но `DiagramPipeline` вызывает его напрямую, минуя LLM tool-choice.
- **Все шаги async/await** с явными таймаутами через `asyncio.wait_for`.

---

### Day 20 — RAG система на базе Ollama + ChromaDB

Реализована полноценная RAG (Retrieval-Augmented Generation) система: агент автоматически находит релевантные документы из локального хранилища и добавляет их в контекст перед каждым ответом LLM.

#### Стек

| Компонент | Технология |
|---|---|
| Эмбеддинги | Ollama (`nomic-embed-text`) — локально, без API |
| Векторное хранилище | ChromaDB (persistent, cosine similarity) |
| Хранение данных | `memory/rag/` — сохраняется между перезапусками |

#### Новые файлы

| Файл | Назначение |
|---|---|
| `rag.py` | `RAGStore` — чанкинг, эмбеддинги через Ollama, CRUD операции с ChromaDB |

#### Изменённые файлы

- **`agent.py`** — `ChatAgent` принимает `rag_store`; `send_message` делает семантический поиск до вызова LLM; `_build_messages` инжектирует найденные чанки как системный блок `[RAG CONTEXT]`
- **`main.py`** — инициализация `RAGStore` в lifespan; 4 новых REST endpoint
- **`requirements.txt`** — добавлен пакет `chromadb`

#### Предварительные требования

Ollama должна быть запущена локально, модель `nomic-embed-text` загружена:

```bash
ollama pull nomic-embed-text
ollama serve          # запускается автоматически при старте Ollama
```

#### API endpoints

| Метод | URL | Описание |
|---|---|---|
| `POST` | `/rag/documents` | Загрузить документ (`text`, `source`) |
| `GET` | `/rag/documents` | Список всех документов с метаданными |
| `GET` | `/rag/search?q=...&top_k=5` | Семантический поиск (без сохранения в историю) |
| `DELETE` | `/rag/documents/{doc_id}` | Удалить документ по id |

#### Пример использования

```bash
# Загрузить документ
curl -X POST http://localhost:8000/rag/documents \
  -H "Content-Type: application/json" \
  -d '{"text": "FastAPI — это современный веб-фреймворк для Python...", "source": "fastapi_docs.txt"}'

# Ответ: {"doc_id": "doc_a1b2c3d4", "chunks": 3, "source": "fastapi_docs.txt"}

# Теперь агент автоматически находит релевантные чанки при каждом вопросе
```

#### Как работает поток

```
Сообщение пользователя
        │
        ▼
RAGStore.retrieve(query, top_k=5)      ← Ollama генерирует эмбеддинг запроса
        │                                 ChromaDB ищет ближайшие чанки (cosine)
        ▼
_build_messages()
  [system] base prompt
  [system] invariants
  [system] memory context
  [system] [RAG CONTEXT] чанк 1 / чанк 2 / ...   ← инжектируется только если найдено
  [user/assistant] история
        │
        ▼
LLM (OpenRouter)   ← отвечает с учётом документов из RAG
```

#### Чанкинг

Документы разбиваются на чанки по 500 символов с перекрытием 50 символов. Каждый чанк хранится отдельно с метаданными `doc_id`, `source`, `chunk_index`.

#### Архитектурные решения

- **Полностью локальный**: эмбеддинги через Ollama — никаких внешних API, никаких затрат на эмбеддинги
- **Graceful degradation**: если Ollama недоступна — RAG пропускается, агент работает в обычном режиме
- **Персистентность**: ChromaDB хранит векторы на диске, переживает перезапуски сервера
- **Изоляция от агента**: `RAGStore` — независимый модуль, не привязан к конкретному пользователю (один индекс на всех)

#### UI — загрузка документов

В правой панели Memory появилась секция **RAG Docs**:

- Список проиндексированных документов: имя файла, количество чанков, кнопка удаления `×`
- Кнопка **`+ Upload file`** — открывает системный диалог выбора файла
- Строка статуса: `Reading…` → `Indexing…` → `✓ file.txt (12 chunks)`

Поддерживаемые форматы: `.txt`, `.md`, `.rst`, `.csv`, `.json`, `.py`, `.js`, `.ts`, `.html`, `.xml`, `.yaml`

Файл читается прямо в браузере через `FileReader` и отправляется на `/rag/documents`. Во время загрузки кнопка блокируется.

Изменённые файлы фронтенда:

| Файл | Что добавлено |
|---|---|
| `static/index.html` | Секция `RAG Docs` с `<input type="file">` в memory panel |
| `static/style.css` | Стили для секции, кнопки загрузки, строк документов |
| `static/app.js` | Функции `loadRagDocuments`, `renderRagDocuments`, обработчик `change` на file input |

---

### Day 21 — Расширенный RAG: метаданные + две стратегии чанкинга

Доработана RAG-система: к каждому чанку добавлены полные метаданные, реализованы две стратегии разбиения документов с возможностью их сравнения прямо в UI.

#### Две стратегии чанкинга

**`fixed` — фиксированный размер**
Разбивает текст окнами по 500 символов с перекрытием 50. Работает для любого текста независимо от структуры. Секция называется `chunk_0`, `chunk_1` и т.д.

**`structural` — по структуре**
Ищет Markdown-заголовки (`#`, `##`, `###`…) и создаёт отдельный чанк для каждого раздела с именем заголовка как `section`. Если заголовков нет — разбивает по двойным переносам строк (параграфы). Лучше сохраняет семантические границы документа.

#### Метаданные каждого чанка

| Поле | Описание | Пример |
|---|---|---|
| `source` | Исходный файл | `guide.md` |
| `title` | Имя файла без расширения | `guide` |
| `section` | Раздел / параграф / позиция | `Installation` или `chunk_2` |
| `chunk_id` | Уникальный id чанка | `fixed_6b0e2446` / `struct_c75ea6` |
| `chunk_index` | Порядковый номер в документе | `0`, `1`, `2` … |
| `strategy` | Стратегия, которой создан чанк | `fixed` / `structural` |

#### Новый API

| Метод | URL | Описание |
|---|---|---|
| `POST` | `/rag/documents` | Загрузить документ; добавлен параметр `strategy: "fixed" \| "structural"` |
| `POST` | `/rag/compare` | Сравнить обе стратегии без сохранения эмбеддингов |

#### Ответ `/rag/compare`

```json
{
  "total_chars": 1234,
  "fixed":      { "count": 8, "avg_len": 490, "min_len": 120, "max_len": 500, "sections": ["chunk_0", ...], "preview": [...] },
  "structural": { "count": 4, "avg_len": 310, "min_len": 65,  "max_len": 530, "sections": ["Intro", "Installation", ...], "preview": [...] },
  "verdict": "structural"
}
```

#### Контекстный блок в промпте

Формат `build_context_block` дополнен секцией и заголовком:

```
[RAG CONTEXT — relevant documents retrieved by semantic search]
(1) [guide / Installation] Run pip install to get started…
(2) [guide / Configuration] Set your API key…
```

#### Изменённые файлы

| Файл | Что изменилось |
|---|---|
| `rag.py` | Полная переработка: функции `chunk_fixed`, `chunk_structural`, `split_chunks`, `compare_strategies`; метаданные во всех методах `RAGStore` |
| `main.py` | `RAGDocumentRequest` + поле `strategy`; новый endpoint `POST /rag/compare`; импорт `compare_strategies` |
| `static/index.html` | Dropdown стратегии, кнопка `⇄ Compare` с отдельным file input, блок результата сравнения |
| `static/app.js` | Стратегия передаётся при загрузке; функции `renderCompareResult`; бейджи `Fixed` / `Structural` в списке документов |
| `static/style.css` | Стили для бейджей, панели сравнения, колонок с превью чанков |

#### UI — управление стратегиями

В секции **RAG Docs** появились новые элементы управления:

- **Dropdown `Fixed / Structural`** — выбирает стратегию перед загрузкой файла
- **Кнопка `⇄ Compare`** — выбрать файл и получить side-by-side сравнение без индексирования
- **Бейджи** на каждом документе: жёлтый `Fixed` или синий `Structural`
- **Панель сравнения**: количество чанков, средняя/мин/макс длина, список секций, preview первых 4 чанков каждой стратегии, отметка рекомендованной стратегии `✓ recommended`

---

### Day 21 (продолжение) — RAG Query Compare: ответ с RAG и без RAG

Реализован полный цикл **вопрос → поиск чанков → объединение → LLM** с явным сравнением ответов модели при наличии и отсутствии контекста из базы знаний.

#### Поток выполнения

```
Вопрос пользователя
        │
        ▼
RAGStore.retrieve(question, top_k=5)   ← Ollama: эмбеддинг вопроса → ChromaDB cosine search
        │
        ├─── base_messages ──────────────────────────────────────┐
        │    [system] prompt                                      │
        │    [user]   вопрос                                      │
        │                                                         │
        └─── rag_messages ───────────────────────────────────────┤
             [system] prompt                                      │
             [system] [RAG CONTEXT] чанк 1 / чанк 2 / ...       │
             [user]   вопрос                                      │
                                                                  │
        asyncio.gather(─────────────────────────────────────)────┘
              _call_api(base_messages)   _call_api(rag_messages)
                    │                          │
              answer_without_rag         answer_with_rag
```

Оба вызова LLM выполняются **параллельно** через `asyncio.gather` — задержка равна максимуму двух запросов, а не их сумме.

#### Новый API endpoint

| Метод | URL | Описание |
|---|---|---|
| `POST` | `/rag/query-compare` | Получить два ответа — с RAG и без RAG |

**Запрос:**
```json
{ "question": "Что такое FastAPI?", "user_id": "default", "top_k": 5 }
```

**Ответ:**
```json
{
  "question": "Что такое FastAPI?",
  "without_rag": {
    "answer": "FastAPI — это современный фреймворк...",
    "usage": { "prompt_tokens": 120, "completion_tokens": 95, "total_tokens": 215 }
  },
  "with_rag": {
    "answer": "Согласно документации (guide / Installation)...",
    "usage": { "prompt_tokens": 580, "completion_tokens": 140, "total_tokens": 720 },
    "chunks_used": 3,
    "chunks": [
      { "text": "FastAPI — это...", "source": "guide.md", "section": "Introduction", "score": 0.92 }
    ]
  },
  "rag_available": true,
  "elapsed_ms": 1840
}
```

#### Изменённые файлы

| Файл | Что добавлено |
|---|---|
| `agent.py` | Метод `compare_rag(question, top_k)` — строит два набора сообщений, параллельно вызывает LLM |
| `main.py` | Модель `RAGQueryCompareRequest`; endpoint `POST /rag/query-compare` |

---

### Day 21 (продолжение) — Вкладка RAG как отдельная страница

RAG-панель вынесена из боковой колонки Memory в самостоятельную глобальную вкладку на уровне всего приложения.

#### Новая структура интерфейса

```
┌──────────────────────────────────────────────────────────────┐
│  [Chat]  [RAG]          ← глобальный tab bar                 │
├──────────────────────────────────────────────────────────────┤
│  tab=chat:                                                    │
│  ┌───────────────────────┬──────────────────┐                │
│  │  Chat                 │  Memory          │                │
│  │  (сообщения + форма)  │  Invariants      │                │
│  │                       │  Short-term      │                │
│  │                       │  Working         │                │
│  │                       │  Long-term       │                │
│  └───────────────────────┴──────────────────┘                │
│                                                              │
│  tab=rag:                                                    │
│  ┌────────────────────┬─────────────────────────────────┐   │
│  │  Documents (340px) │  Ask with / without RAG          │   │
│  │  Список + Upload   │  Поле вопроса + кнопка Ask       │   │
│  │  Стратегия         │  ┌────────────┬───────────────┐  │   │
│  │  ⇄ Compare         │  │ Без RAG    │ С RAG         │  │   │
│  │                    │  │ ответ      │ ответ + чанки │  │   │
│  │                    │  └────────────┴───────────────┘  │   │
│  └────────────────────┴─────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

#### Изменённые файлы

| Файл | Что изменилось |
|---|---|
| `static/index.html` | Обёртка `.app-root` + `<nav class="main-nav">` с двумя вкладками; `#tab-chat` содержит Chat + Memory (без RAG); `#tab-rag` — полноэкранная RAG-страница с двумя колонками |
| `static/style.css` | Добавлены `.app-root`, `.main-nav`, `.main-nav-tab`, `.main-tab-panel`, `.rag-page`, `.rag-page-col`; убраны `border-radius` и `box-shadow` с `.chat-container` и `.memory-panel` (теперь задаёт `.main-tab-panel`); все CSS-переменные в RAG-блоке заменены на конкретные цвета светлой темы |
| `static/app.js` | Обработчик кликов по `.main-nav-tab`; переключение классов `.active` на панелях; автозагрузка `loadRagDocuments()` при переходе на вкладку RAG |

---

### Day 22 — RAG: реранкер, фильтр релевантности и query rewrite

Добавлена вторая стадия обработки результатов поиска — **реранкер с пороговой фильтрацией и MMR-диверсификацией**, а также **перезапись запроса** (query rewrite) для улучшения качества retrieval. Реализовано сравнение **5 режимов** RAG-пайплайна.

#### Pipeline

```
Запрос пользователя
        │
        ▼
① Query rewrite ─────────────────────────────────────────────────────
   • keywords — вырезает стоп-слова (en + ru), оставляет значимые токены
   • expand   — дополняет запрос ключевыми словами
   • none     — запрос без изменений
        │
        ▼
② Semantic search (pre_k=10) ────────────────────────────────────────
   Ollama эмбеддинг переписанного запроса → ChromaDB cosine search
        │
        ▼
③ Reranker ───────────────────────────────────────────────────────────
   • threshold filter — отсекает чанки с score ниже порога (по умолчанию 0.3)
   • MMR (Maximum Marginal Relevance) — балансирует релевантность и
     разнообразие: отбрасывает почти дублирующиеся чанки в пользу
     более разнородных. Параметр λ (по умолчанию 0.7):
       1.0 = чистая релевантность, 0.0 = чистое разнообразие
   • post_k — ограничение финальной выдачи (по умолчанию 5)
        │
        ▼
④ RAG контекст → LLM
```

#### Сравнение 5 режимов

Endpoint `POST /rag/compare-all` параллельно вызывает LLM с пятью вариантами контекста:

| # | Режим | Описание |
|---|---|---|
| 1 | **No RAG** | Без контекста — baseline |
| 2 | **RAG basic** | Сырой запрос, без фильтрации |
| 3 | **RAG + rewrite** | Перезапись запроса, без реранкера |
| 4 | **RAG + rerank** | Пороговая фильтрация + MMR, без rewrite |
| 5 | **RAG + rewrite + rerank** | Полный пайплайн |

Пример ответа:
```json
{
  "question": "Как Горчев описывает идеальное мироустройство?",
  "modes": {
    "no-rag":               { "answer": "...", "usage": {...}, "elapsed_ms": 21709 },
    "rag-basic":            { "answer": "...", "usage": {...}, "elapsed_ms": 49858 },
    "rag+rewrite":          { "answer": "...", "usage": {...}, "elapsed_ms": 84231 },
    "rag+rerank":           { "answer": "...", "usage": {...}, "elapsed_ms": 49285 },
    "rag+rewrite+rerank":   { "answer": "...", "usage": {...}, "elapsed_ms": 41870 }
  },
  "pipeline_info": {
    "rewritten_query": "горчев описывает идеальное мироустройство",
    "chunks_before_rerank": 10,
    "chunks_after_rerank": 4,
    "threshold": 0.3,
    "pre_k": 10,
    "post_k": 4,
    "rewrite_strategy": "keywords",
    "use_mmr": true
  }
}
```

#### Результаты на реальных данных

Тест на трёх русскоязычных документах Дмитрия Горчева (169 чанков):

| Режим | Токены | Время | Качество |
|---|---|---|---|
| **No RAG** | 2675 | 21.7s | «Не знаю такого автора, укажите произведение…» |
| **RAG basic** | 4329 | 49.9s | Детальный ответ: утопия, подавление индивидуальности, оценка коммунистов |
| **RAG + rewrite** | 4410 | 84.2s | Структурированный ответ с двумя уровнями справедливости |
| **RAG + rerank** | 3925 | 49.3s | Конкретный ответ, меньше токенов за счёт фильтрации дубликатов |
| **RAG + rewrite + rerank** | 4130 | 41.9s | Лучший баланс: осмысленный ответ за разумное время |

**Выводы:**
- **No RAG проваливается** на специфических/редких авторах — модель не знает контекста
- **Реранкер экономит токены** (3925 vs 4329), отсеивая слабые и дублирующиеся чанки без потери качества
- **Rewrite + rerank** даёт наилучший баланс качества и скорости

#### Стоп-слова

Поддерживаются **английский и русский** языки. Список из ~150 слов: артикли, предлоги, союзы, местоимения, вопросительные слова, частицы. Регулярки обновлены для захвата кириллицы (`[a-zA-Zа-яёА-ЯЁ0-9_]`).

#### Параметры по умолчанию

| Параметр | Значение | Описание |
|---|---|---|
| `pre_k` | 10 | Сколько чанков извлечь из ChromaDB до фильтрации |
| `post_k` | 5 | Максимум чанков после реранкера |
| `threshold` | 0.3 | Минимальный similarity score (0–1) |
| `use_mmr` | true | Включить MMR-диверсификацию |
| `mmr_lambda` | 0.7 | Баланс релевантность/разнообразие |
| `rewrite` | `keywords` | Стратегия перезаписи: `none` / `keywords` / `expand` |

#### Новые и изменённые файлы

| Файл | Что изменилось |
|---|---|
| `rag.py` | Стоп-слова (en+ru), `rewrite_query_keywords`, `rewrite_query_expand`, `rewrite_query`; `apply_score_threshold`, `apply_mmr`, `rerank_results`; класс `RAGRetriever` — оркестратор полного пайплайна |
| `agent.py` | `send_message` использует rewrite + rerank по умолчанию; метод `compare_all_rag` — 5 параллельных LLM-вызовов для сравнения режимов |
| `main.py` | `/rag/search` принимает параметры `pre_k`, `threshold`, `rewrite`, `use_mmr`; новый endpoint `POST /rag/compare-all` |
| `static/index.html` | Блок настроек реранкера (Pre-K, Post-K, Threshold, MMR, Rewrite); переключатель режимов «A/B» / «All 5 modes» |
| `static/app.js` | `renderRagCompareAll` — отрисовка 5-колоночного сравнения; пайплайн-инфо с rewritten query и статистикой фильтрации |
| `static/style.css` | Стили контролов реранкера, табов режимов, пайплайн-бара, 5-колоночного лейаута, визуальных индикаторов score |

#### Архитектурные решения

- **Реранкер работает локально** — не требует отдельной модели, использует Jaccard-разнообразие на токенах
- **MMR без внешних зависимостей** — токенизация через regex, Jaccard-коэффициент, жадный отбор
- **Query rewrite без LLM** — чисто эвристический (стоп-слова + keyword extraction), не добавляет задержки
- **5-режимное сравнение** — все LLM-вызовы выполняются параллельно через `asyncio.gather`
- **Основной чат использует полный пайплайн** — rewrite + rerank с threshold=0.25 по умолчанию

---

### Day 23 — Выбор модели и прямое API DeepSeek

Добавлен выпадающий список выбора модели в интерфейсе и поддержка прямого API DeepSeek (минуя OpenRouter).

#### Поддерживаемые модели

| ID | Лейбл | Провайдер |
|---|---|---|
| `nvidia/nemotron-3-super-120b-a12b:free` | Nemotron (OpenRouter, free) | OpenRouter |
| `deepseek/deepseek-chat` | DeepSeek (OpenRouter) | OpenRouter |
| `deepseek-direct/deepseek-chat` | DeepSeek (Direct API) | DeepSeek |

#### Прямой API DeepSeek

Модели с префиксом `deepseek-direct/` маршрутизируются напрямую на `https://api.deepseek.com/v1/chat/completions`, а не через OpenRouter. Требует `DEEPSEEK_API_KEY` в `.env`.

Логика маршрутизации — функция `_resolve_model_id()` в `agent.py`:
- `deepseek-direct/*` → `provider="deepseek"`, URL=`https://api.deepseek.com/v1/chat/completions`
- всё остальное → `provider="openrouter"`, URL=`https://openrouter.ai/api/v1/chat/completions`

#### API endpoints

| Метод | URL | Описание |
|---|---|---|
| `GET` | `/models` | Список доступных моделей с флагами `available` |
| `GET` | `/model?user_id=...` | Текущая модель пользователя |
| `POST` | `/model?user_id=...` | Установить модель пользователю (`{"model_id": "..."}`) |

Модель сохраняется per-user (словарь `user_models` в `main.py`), модель по умолчанию — `deepseek-direct/deepseek-chat`.

#### UI

Выпадающий список `Model` в заголовке чата. Модели без API-ключа отображаются как `(no key)` и заблокированы. При смене модели отправляется `POST /model`, агент пользователя обновляется через `agent.set_model()`.

#### Изменённые файлы

| Файл | Что изменилось |
|---|---|
| `agent.py` | Функция `_resolve_model_id()`, параметр `deepseek_api_key`, метод `set_model()`; `_call_api` и `_classify_as_diagram` маршрутизируют по провайдеру |
| `main.py` | Список `AVAILABLE_MODELS`, `DEFAULT_MODEL`, словарь `user_models`; endpoints `/models`, `/model` (GET+POST) |
| `.env.example` | Добавлен `DEEPSEEK_API_KEY` |
| `static/index.html` | Выпадающий список `#model-select` в `chat-header` |
| `static/app.js` | Функции `loadModels()`, обработчик `change` на `#model-select`, `currentModelId` |

---

### Day 24 — Структурированный вывод RAG и отображение источников в чате

Реализован структурированный формат вывода RAG: модель обязана отвечать в формате ANSWER / SOURCES / QUOTES, а при отсутствии релевантного контекста — честно говорить «я не знаю». Источники RAG отображаются под каждым сообщением ассистента в чате.

#### Структурированный формат вывода

В системный промпт инжектятся инструкции `build_rag_output_instructions()`:

```
[RAG OUTPUT FORMAT — MANDATORY]
1. ANSWER: прямой ответ на вопрос на основе найденного контекста
2. SOURCES: список использованных источников в формате:
   - source (section: name, chunk_id: id)
3. QUOTES: для каждого утверждения — цитата из чанка в формате «...»
```

Если релевантный контекст не найден — модель ОБЯЗАНА ответить:
> «Я не знаю ответа на этот вопрос. В найденных документах недостаточно информации. Пожалуйста, уточните вопрос или предоставьте дополнительные материалы.»

Это решает проблему галлюцинаций при отсутствии релевантных документов.

#### Два сценария RAG в чате

**Релевантные чанки найдены:**
```
[RAG CONTEXT] чанк 1 / чанк 2 / ...
[RAG OUTPUT FORMAT — MANDATORY] ← инструкции
```

**Чанки найдены, но все ниже порога релевантности:**
```
[RAG — No relevant context found]
Semantic search did not find documents relevant enough...
Модель ОБЯЗАНА ответить «я не знаю»
```

#### Отображение источников в чате

Для каждого ответа ассистента, если были использованы RAG-источники, под сообщением отображается блок:

```
📚 3 sources
┌──────────────────────────────────────────────────┐
│ guide.md › Installation              92%         │
│ Run pip install to get started…                  │
├──────────────────────────────────────────────────┤
│ guide.md › Configuration              78%         │
│ Set your API key in the environment…             │
└──────────────────────────────────────────────────┘
```

Цветовая индикация score: зелёный (≥70%), жёлтый (40-69%), красный (<40%).

Если контекст не найден — отображается:
> 📚 RAG — no relevant documents found
> All retrieved chunks were below the relevance threshold.

#### Изменённые файлы

| Файл | Что изменилось |
|---|---|
| `rag.py` | Методы `build_rag_output_instructions()` и `build_no_context_instructions()` |
| `agent.py` | Свойства `last_rag_sources`, `last_rag_no_context`; `_build_messages` инжектит `rag_no_context` или `rag_output` инструкции |
| `main.py` | Поля `rag_sources` и `rag_no_context` в `MessageResponse` |
| `static/app.js` | Функция `appendRagSources()` — отрисовка блока источников под сообщением |
| `static/style.css` | Стили `.rag-sources`, `.rag-source-item`, `.rag-source-score`, `.rag-source-preview`, `.rag-sources-none` |

#### Архитектурные решения

- **Структурированный вывод — через system prompt**, а не через tool-calling. Это универсально для любых моделей.
- **«I don't know» guard** — модель явно инструктирована не выдумывать ответ при отсутствии контекста.
- **Источники в чате** — пользователь видит, откуда взят ответ, может оценить релевантность.
- **Graceful degradation** — если RAG недоступен, агент работает как обычно.

---

### Day 25 — Панель контрольных вопросов

Добавлена панель контрольных вопросов на вкладке RAG: можно выбрать вопрос из списка, увидеть ожидаемый ответ и запустить сравнение всех RAG-режимов для проверки качества Retrieval.

#### Источник вопросов

Файл `docs/горчев/контрольные вопросы.txt` парсится при старте сервера. Формат:

```
1. Как Горчев описывает идеальное мироустройство?
Ожидаемый ответ: Горчев описывает утопическое общество...

2. Какие основные темы поднимает автор в рассказе «Счастье»?
Ожидаемый ответ: ...
```

Парсер (`_parse_control_questions`) использует regex, извлекает номер, текст вопроса и ожидаемый ответ.

#### API

| Метод | URL | Описание |
|---|---|---|
| `GET` | `/rag/control-questions` | Список вопросов с ожидаемыми ответами |

#### Интеграция с RAG-сравнением

При выборе вопроса:
1. Текст вопроса автоматически подставляется в строку поиска
2. Ожидаемый ответ отображается в левой панели
3. При запуске сравнения (`/rag/query-compare` или `/rag/compare-all`) ожидаемый ответ передаётся в запросе и отображается над результатами — можно визуально сравнить ответы модели с эталоном

#### UI

В левой колонке вкладки RAG:

- **Список вопросов** — кликабельные строки с номерами и текстом
- **Блок ожидаемого ответа** — появляется при выборе вопроса, показывает эталонный ответ

#### Изменённые файлы

| Файл | Что изменилось |
|---|---|
| `main.py` | Функция `_parse_control_questions()`, глобальная переменная `control_questions`, endpoint `GET /rag/control-questions`; поле `expected_answer` в `RAGQueryCompareRequest` и `RAGCompareAllRequest` |
| `static/index.html` | Секция «Контрольные вопросы» с `#rag-ctrl-list` и `#rag-ctrl-expected` |
| `static/app.js` | `controlQuestions[]`, `loadControlQuestions()`, `renderControlQuestions()`, `selectControlQuestion()`, `_getExpectedAnswer()` |
| `static/style.css` | Стили `.rag-ctrl-item`, `.rag-ctrl-expected`, `.rag-qc-expected` |

#### Архитектурные решения

- **Контрольные вопросы загружаются один раз при старте** — не меняются без перезапуска сервера
- **Ожидаемый ответ — опциональное поле** — если не передан, UI просто не показывает блок
- **Интеграция с существующими endpoint сравнения** — минимальные изменения API, обратная совместимость

---

### Day 26 — Вкладка Local LLM: чат с локальными моделями (Ollama + llama.cpp)

Добавлена отдельная вкладка «Local LLM» для чата с локальными моделями без использования облачных API. Поддерживаются два источника моделей: **Ollama** и **llama.cpp**.

#### Поддерживаемые провайдеры

| Провайдер | API | Модели |
|---|---|---|
| **Ollama** | `localhost:11434/api/chat` | Все чат-модели, установленные в Ollama (llama3.2:3b, gemma4 и др.) |
| **llama.cpp** | `localhost:8080/v1/chat/completions` | `.gguf` файлы из `llama.cpp/models/` (OpenAI-совместимый API) |

#### API endpoints

| Метод | URL | Описание |
|---|---|---|
| `GET` | `/chat/local/models` | Список доступных локальных моделей (Ollama + llama.cpp) с флагами `available` |
| `GET` | `/chat/local/model?user_id=...` | Текущая выбранная модель пользователя |
| `POST` | `/chat/local/model?user_id=...` | Установить модель (`{"model_id": "ollama:llama3.2:3b"}`) |
| `POST` | `/chat/local` | Отправить сообщение в чат с локальной моделью |
| `GET` | `/chat/local/history?user_id=...` | История локального чата |
| `DELETE` | `/chat/local/history?user_id=...` | Очистить историю локального чата |

#### Обнаружение моделей

- **Ollama** — через `GET /api/tags`, эмбеддинг-модели (nomic-embed-text и др.) исключаются из списка
- **llama.cpp** — сканирование папки `models/` на `.gguf` файлы (исключая `ggml-vocab-*`), проверка доступности сервера на `localhost:8080`

Модели отмечаются как `(offline)` и блокируются в селекте, если соответствующий сервер не запущен.

#### Переключатель моделей

В хидере вкладки Local LLM — выпадающий список `Model` для выбора локальной модели. Выбор сохраняется per-user и синхронизирован с бэкендом через `POST /chat/local/model`.

#### UI чата

- Полноэкранный чат без боковой панели памяти — только сообщения, поле ввода и кнопка Clear
- **Метка модели и времени ответа** — под каждым ответом ассистента отображается бейдж вида `llama3.2:3b · 2.53s`
- Поле ввода и кнопки стилизованы идентично вкладке Chat

#### Маршрутизация запросов

```
POST /chat/local
        │
        ▼
_resolve_local_model(user_id)
        │
        ├── provider=ollama    → POST localhost:11434/api/chat
        │                        { "model": "llama3.2:3b", "messages": [...], "stream": false }
        │
        └── provider=llamacpp → POST localhost:8080/v1/chat/completions
                                 { "model": "qwen2.5-1.5b...", "messages": [...] }
```

История диалога хранится в памяти на сервере (словарь `local_chat_history`, per-user), теряется при перезапуске.

#### Изменённые файлы

| Файл | Что изменилось |
|---|---|
| `main.py` | Константы `OLLAMA_URL`, `LLAMACPP_SERVER_URL`, `LLAMACPP_MODELS_DIR`; словари `local_chat_history`, `user_local_models`; функции `_discover_ollama_models()`, `_discover_llamacpp_models()`, `_resolve_local_model()`, `_chat_ollama()`, `_chat_llamacpp()`; endpoints для моделей и чата |
| `static/index.html` | Вкладка `#tab-local` с контейнером `.local-chat-container`, селектом `#local-model-select`, полем ввода и кнопками |
| `static/app.js` | `loadLocalModels()`, `loadLocalHistory()`, `appendLocalMessage()`, `sendLocalMessage()`; обработчики селекта моделей, отправки сообщений, очистки истории |
| `static/style.css` | Стили `.local-chat-container`, `.local-model-badge` (в хидере и внутри сообщений) |

#### Архитектурные решения

- **Локальные модели — без внешних API**: запросы не покидают машину, не требуют API-ключей
- **Изоляция от основного чата**: история локального чата не пересекается с историей OpenRouter/DeepSeek
- **Graceful degradation**: если Ollama или llama.cpp сервер недоступен — модель показывается как `(offline)`, но список других провайдеров продолжает работать
- **Единый интерфейс**: обе вкладки Chat и Local LLM выглядят и работают одинаково (отправка Enter, Shift+Enter для новой строки, авто-resize textarea)

#### Предварительные требования

```bash
# Ollama (уже должен быть запущен)
ollama serve

# llama.cpp (опционально)
/Users/yaroslav/develop/ai-assist/llama.cpp/llama-server \
  -m models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
  --port 8080
```

---

### Day 27 — RAG для вкладки Local LLM

RAG-система, ранее работавшая только в основном чате (вкладка Chat), теперь подключена и к локальным моделям (вкладка Local LLM). При отправке сообщения в локальную модель выполняется тот же retrieval pipeline: семантический поиск → keyword-дополнение → реранкер → инжекция контекста в промпт.

#### Как работает

```
POST /chat/local
        │
        ▼
RAG retrieval (тот же pipeline что в ChatAgent)
        │
        ├── semantic search (top_k=35)
        ├── keyword supplement (фразы в кавычках «...» / "...")
        ├── neighbor chunks (offset ±1, 2, 3 для keyword-совпадений)
        └── reranker (pre_k=30, post_k=10, threshold=0.25, MMR)
                │
                ▼
Build messages:
  [system] RAG context block (чанки с метаданными)
  [system] RAG instructions (упрощённые для локальных моделей)
  [user/assistant] история диалога
        │
        ▼
Ollama / llama.cpp → ответ с учётом контекста
```

#### Отличия от основного чата

| Аспект | Chat (OpenRouter/DeepSeek) | Local LLM (Ollama/llama.cpp) |
|---|---|---|
| RAG-инструкции | Полный формат ANSWER/SOURCES/QUOTES | Упрощённые: «ответь по контексту, укажи источники» |
| System prompt | Полный (память, инварианты, FSM, etc.) | Только RAG-контекст + краткая инструкция |
| Отображение источников | ✅ (блок под ответом) | ✅ (такой же блок, scroll в localMessagesEl) |

#### Изменённые файлы

| Файл | Что изменилось |
|---|---|
| `main.py` | Импорт `rewrite_query`, `rerank_results` из `rag`; поля `rag_sources`, `rag_no_context` в `LocalChatResponse`; RAG retrieval pipeline в `POST /chat/local`; `_chat_ollama` / `_chat_llamacpp` принимают `messages` вместо `history` |
| `static/app.js` | `appendRagSources()` — опциональный 4-й параметр `scrollEl`; `sendLocalMessage()` вызывает `appendRagSources()` с `localMessagesEl` |

#### Архитектурные решения

- **Единый retrieval pipeline** — код поиска и реранкинга идентичен основному чату, не дублирован (используются те же функции `rag_store.retrieve()`, `rerank_results()`, `rewrite_query()`)
- **Упрощённые инструкции для локальных моделей** — небольшие модели (3B-7B) могут не справиться со сложным форматом ANSWER/SOURCES/QUOTES, поэтому получают краткую инструкцию
- **Graceful degradation** — если RAG не инициализирован (нет Ollama для эмбеддингов), локальный чат работает без RAG как раньше
- **Скролл в правильный контейнер** — `appendRagSources` принимает опциональный `scrollEl`, чтобы на вкладке Local LLM скроллился `localMessagesEl`, а не `messagesEl`

---

### Предыдущие доработки

| День | Фича |
|---|---|
| Day 15 | Интеграция MCP погодного сервера (`mcp_weather.py`) |
| Day 14 | Конечный автомат задач (Task FSM) с явными переходами состояний |
| Day 13 | Инварианты (`invariants.py`) — правила поведения агента |
| Day 12 | Глобальный системный промпт, редактируемый через UI |