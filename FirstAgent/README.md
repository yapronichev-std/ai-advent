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

### Day 28 — Оптимизация локальной модели: параметры, квантование, шаблоны промптов

Добавлены пользовательские настройки для локальных моделей во вкладке Local LLM: управление параметрами генерации (temperature, max tokens, context window), отображение уровня квантования и настраиваемые шаблоны системных промптов.

#### Параметры генерации

На вкладке Local LLM появилась сворачиваемая панель **Parameters** с шестью настройками:

| Параметр | По умолчанию | Ollama поле | llama.cpp поле |
|----------|-------------|-------------|----------------|
| Temperature | 0.8 | `options.temperature` | `temperature` |
| Max Tokens | 2048 | `options.num_predict` | `max_tokens` |
| Top-P | 0.9 | `options.top_p` | `top_p` |
| Top-K | 40 | `options.top_k` | *недоступно* |
| Repeat Penalty | 1.1 | `options.repeat_penalty` | `frequency_penalty` + `presence_penalty` |
| Context Window | 4096 | `options.num_ctx` | *требует перезапуска сервера* |

Каждый параметр — связка слайдер + числовой ввод с двусторонней синхронизацией. Сохранение — debounce 500ms, per-user. Для разных провайдеров поля маппятся по-разному: Ollama использует `options.*`, llama.cpp — поля верхнего уровня (`temperature`, `max_tokens`, etc.).

Параметры, недоступные для конкретного провайдера, автоматически скрываются или блокируются с примечанием.

#### Квантование

Рядом с селектором модели отображается цветной бейдж с уровнем квантования:

| Бейдж | Уровни | Цвет |
|-------|--------|------|
| `Q4_K_M` | Q2, Q3, Q4 | Оранжевый (низкое) |
| `Q5_K_M` | Q5 | Синий (среднее) |
| `Q8_0` | Q6, Q8, F16 | Зелёный (высокое) |

Информация о квантовании извлекается:
- Для **GGUF-файлов** llama.cpp — парсинг имени файла (регулярка)
- Для **Ollama-моделей** — через `POST /api/show`

Результат кешируется на 60 секунд.

#### Шаблоны системных промптов

Панель **System Prompt** со сворачиваемым блоком:

| Шаблон | Описание |
|--------|----------|
| **RAG-ассистент** | По умолчанию: полезный ассистент с поддержкой контекста документов |
| **Код-ревью** | Экспертная проверка кода: баги, производительность, безопасность |
| **Креативное письмо** | Выразительный и образный стиль |
| **Лаконичный** | Краткие, прямые ответы без лишних слов |
| **Свой шаблон** | Пользователь пишет системный промпт самостоятельно |

Все шаблоны — на русском языке. При выборе предустановки textarea авто-заполняется. Выбор сохраняется per-user. Системный промпт вставляется **перед** RAG-контекстом в сообщения.

#### Новые API endpoints

| Метод | URL | Описание |
|---|---|---|
| `GET` | `/chat/local/params?user_id=...` | Текущие параметры генерации |
| `POST` | `/chat/local/params?user_id=...` | Обновить параметры (частичное слияние) |
| `GET` | `/chat/local/templates` | Список доступных шаблонов промптов |
| `GET` | `/chat/local/prompt-template?user_id=...` | Текущий шаблон пользователя |
| `POST` | `/chat/local/prompt-template?user_id=...` | Установить шаблон |
| `GET` | `/chat/local/model-detail?model_id=...` | Информация о модели (квантование, размер, семейство) |

#### Изменённые файлы

| Файл | Что изменилось |
|---|---|
| `main.py` | Константы `DEFAULT_LOCAL_PARAMS`, `PROMPT_TEMPLATES`; словари `user_local_params`, `user_local_prompt_template`, `user_local_system_prompt`; Pydantic-модели `LocalParamsRequest`, `LocalPromptTemplateRequest`; 6 новых endpoints; обновление `_chat_ollama`/`_chat_llamacpp` для приёма `params`; сборка сообщений с системным промптом перед RAG-контекстом |
| `static/index.html` | Панели `<details>` для Parameters и System Prompt; бейдж квантования `#local-quant-badge` |
| `static/app.js` | `syncRangeAndNumber()`, `loadLocalParams()`, `saveLocalParams()`, `loadLocalPromptTemplate()`, `loadTemplateDefinitions()`, `saveLocalTemplate()`, `loadLocalModelDetail()`; обновление обработчика табов |
| `static/style.css` | Стили `.param-row`, `.param-num`, `.quant-badge`, `.local-sysprompt-body`, адаптивность |

#### Архитектурные решения

- **Частичное слияние параметров** — можно обновить один параметр, не затрагивая остальные
- **Debounce 500ms** — предотвращает лавину запросов при перетаскивании слайдера
- **Разный маппинг для разных провайдеров** — `repeat_penalty` (Ollama) → `frequency_penalty` + `presence_penalty` (llama.cpp), `max_tokens` → `num_predict` (Ollama)
- **Авто-скрытие неподдерживаемых параметров** — при выборе llama.cpp-модели Top-K скрывается, Context Window блокируется

---

### Day 29 — Поддержка HTML и MHTML в RAG-системе

Реализована предобработка HTML и MHTML-документов перед индексацией в RAG: извлечение чистого текста, конвертация HTML-заголовков в Markdown-формат для structural-чанкера, извлечение метаданных (`<title>`), автоматическое определение формата.

#### Проблема

Раньше HTML-файлы индексировались как сырой текст — теги, скрипты и стили попадали в эмбеддинги, создавая шум и ухудшая качество поиска. MHTML (сохранённые веб-страницы) не поддерживались вообще.

#### Решение: `html_parser.py`

Новый модуль с классом `HtmlExtractor` (только stdlib: `html.parser` + `email`):

| Метод | Описание |
|---|---|
| `detect_format(text)` | Автоопределение: `html`, `mhtml` или `text` |
| `from_html(text)` | Извлечение чистого текста + метаданных из HTML |
| `from_mhtml(text)` | Парсинг MIME-конверта → извлечение HTML → `from_html()` |

#### Обработка HTML

```
Вход:  <html><head><title>Мой документ</title><script>alert(1)</script></head>
       <body><h1>Введение</h1><p>Текст <b>жирный</b>.</p></body></html>

Выход: # Введение
       Текст жирный.
       title: "Мой документ"
```

- **`<script>`, `<style>`, `<noscript>`** — удаляются полностью вместе с содержимым
- **`<h1>...<h6>`** → `# ... ######` — конвертируются в Markdown-заголовки (structural-чанкер распознаёт их как секции)
- **`<p>`, `<div>`, `<li>`** — добавляют переносы строк
- **`<b>`, `<i>`, `<code>`** — inline-теги удаляются, текст сохраняется
- **`<title>`** — извлекается как название документа

#### Обработка MHTML

MHTML (MIME HTML, `.mhtml`/`.mht`) — формат сохранения веб-страниц браузером. Представляет собой MIME-конверт `multipart/related`.

1. Python-модуль `email` парсит MIME-структуру
2. Находится часть с `Content-Type: text/html`
3. Декодируется (quoted-printable / base64)
4. Передаётся в `from_html()`

#### Интеграция в pipeline

Предобработка встроена в `RAGStore.add_document_stream()` и `add_document()`:

```python
if format == "auto":
    detected = HtmlExtractor.detect_format(text)
elif detected in ("html", "mhtml"):
    result = HtmlExtractor.from_html(text)  # или from_mhtml
    text = result["clean_text"]
    if not source:
        source = result["title"]
```

Формат можно указать вручную (`html`, `mhtml`, `text`) или оставить `auto` для автоопределения.

#### API

Поле `format` добавлено в `RAGDocumentRequest`:

```json
{
  "text": "<html>...</html>",
  "source": "page.html",
  "strategy": "structural",
  "format": "auto"
}
```

Ответ `done` содержит определённый формат и извлечённый title:

```json
{
  "type": "done",
  "detected_format": "html",
  "extracted_title": "Мой документ"
}
```

#### UI

- **Селектор формата** — рядом со стратегией чанкинга: `Auto`, `Plain Text`, `HTML`, `MHTML`
- **Расширенный accept** — `.mhtml`, `.mht`, `.htm` добавлены в диалог выбора файла
- **Статус загрузки** — показывает определённый формат: `✓ page.html (4 chunks, structural, html)`

#### Изменённые файлы

| Файл | Что изменилось |
|---|---|
| `html_parser.py` | **Новый файл**. Класс `HtmlExtractor`: `detect_format()`, `from_html()`, `from_mhtml()` |
| `rag.py` | Импорт `HtmlExtractor`; параметр `format` в `add_document()` и `add_document_stream()`; предобработка перед `split_chunks()`; поля `detected_format`, `extracted_title` в ответе |
| `main.py` | Поле `format` в `RAGDocumentRequest`; валидация и передача в `add_document_stream`/`add_document` |
| `static/index.html` | Селектор `#rag-format-select`; `.mhtml,.mht` в `accept` |
| `static/app.js` | Переменная `ragFormatSelect`; передача `format` при загрузке; отображение определённого формата в статусе |

#### Архитектурные решения

- **Только stdlib** — без внешних зависимостей: `html.parser` для HTML, `email` для MIME
- **Прозрачная интеграция** — существующий код чанкинга и эмбеддингов не затронут
- **Auto-definition** — формат определяется по сигнатурам в начале файла (`<!DOCTYPE html>`, `<html`, `MIME-Version:`)
- **Структурный чанкинг + HTML** — конвертация `<h1>` в `#` позволяет structural-чанкеру корректно разбивать HTML-документы по логическим секциям
- **Title как source** — если пользователь не указал `source`, берётся `<title>` из HTML

---

### Day 30 — Вкладка Remote LLM: чат с удалённой моделью llama.cpp

Вкладка для подключения к удалённому серверу llama.cpp по HTTP API (OpenAI-совместимый протокол). Позволяет использовать мощный удалённый сервер с GPU/CPU для инференса без запуска моделей локально.

#### Сервер

Развёрнут на удалённой машине:
- **IP:** `195.58.153.66:8080`
- **Модель:** Qwen2.5-1.5B-Instruct-Q4_K_M (1.5B параметров, контекст 8192)
- **CPU:** 4 vCPU Intel Xeon Gold 6240R (AVX512), 8 GB RAM
- **RAM:** 634 MiB (против 7.3 GB у предыдущей Qwen3-4B)

#### Архитектура

```
Browser (Remote LLM tab)
    │  fetch SSE stream /chat/remote
    ▼
FirstAgent (FastAPI, main.py)
    │  httpx.stream → POST /v1/chat/completions (stream: true)
    ▼
llama-server (195.58.153.66:8080)
    │  llama.cpp inference
    ▼
Qwen2.5-1.5B-Instruct-Q4_K_M model
```

#### Ключевые доработки (v2)

**1. SSE-стриминг**
- `POST /chat/remote` теперь возвращает `StreamingResponse` (`text/event-stream`)
- Токены приходят по мере генерации — пользователь видит текст сразу, а не через 3-5 минут
- Формат событий: `data: {"token": "Хорошо", "done": false}` / `data: {"token": "", "done": true, "model": "...", "elapsed_ms": 34600}`
- Проксирование SSE-потока от llama.cpp через `httpx.AsyncClient.stream()` + `aiter_lines()`

**2. Fallback на reasoning_content**
- Qwen3 и другие reasoning-модели помещают ответ в `reasoning_content`, оставляя `content` пустым
- Бэкенд проверяет оба поля: сначала `content`, затем `reasoning_content`
- Работает как в обычном, так и в стриминговом режиме

**3. Кнопка Stop**
- Кнопка `⏹ Stop` появляется вместо `Send` во время генерации
- Вызывает `AbortController.abort()` — прерывает fetch и SSE-стрим
- Уже полученный текст сохраняется в чате

**4. Смена модели (Qwen3-4B → Qwen2.5-1.5B)**

| Параметр | Было (Qwen3-4B) | Стало (Qwen2.5-1.5B) |
|----------|-----------------|----------------------|
| Скорость | ~5 tok/s | **~16 tok/s** (3×) |
| Время ответа* | 226 сек | **35 сек** (6.5×) |
| RAM | 7.3 GB | 0.6 GB |
| reasoning_content | весь ответ | не используется |
| content | всегда пустой | сразу ответ |

*На запросе «напиши алгоритм быстрой сортировки на языке c++»

#### Новые файлы

| Файл | Назначение |
|---|---|
| `llama-cpp-readme.md` | Инструкция по работе с llama.cpp на удалённом сервере |

#### Изменённые файлы

- **`main.py`** — добавлены эндпоинты:
  - `GET /chat/remote/health` — проверка доступности сервера (latency, модель, параметры)
  - `GET /chat/remote/models` — список моделей на удалённом сервере
  - `POST /chat/remote` — **SSE-стриминг**: проксирует поток от llama.cpp, извлекает токены из `content` / `reasoning_content`
  - `GET /chat/remote/history` — история чата
  - `DELETE /chat/remote/history` — очистка истории
- **`static/index.html`** — новая кнопка в навбаре `Remote LLM` и панель `tab-remote`:
  - Индикатор статуса сервера (зелёный/красный/проверка)
  - Диагностическая панель: модель, параметры, контекст, latency
  - Поле ввода с авто-блокировкой при недоступности сервера
  - Кнопка `⏹ Stop` для остановки генерации
- **`static/app.js`** — логика вкладки Remote LLM:
  - `checkRemoteHealth()` — health-check при открытии вкладки
  - Авто-мониторинг каждые 30 секунд
  - **SSE-стриминг** через `ReadableStream` + `TextDecoder` — токены отображаются по мере получения
  - Кнопка `⏹ Stop` через `AbortController`
  - Отображение времени ответа и tok/s в футере сообщений
  - Обработка ошибок соединения
  - Вспомогательная функция `escapeHtml()`
- **`static/style.css`** — стили для Remote LLM:
  - `.remote-server-badge` — адрес сервера
  - `.remote-status-dot` / `.online` / `.offline` / `.checking` — анимированный индикатор
  - `.remote-diag-bar` — панель диагностики
  - `.msg-footer` / `.msg-time` — футер сообщений с метриками
  - `.msg-error-tag` — тег ошибки
  - `.stop-btn` — кнопка остановки генерации
  - Стили `#remote-input`, `#remote-send-btn` приведены к общему виду с остальными вкладками

#### API Endpoints

**Проверка здоровья:**
```bash
curl http://localhost:8000/chat/remote/health
# → {"available": true, "latency_ms": 56, "models": [{"id": "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf", ...}]}
```

**SSE-стриминг (токены приходят по мере генерации):**
```bash
curl -N http://localhost:8000/chat/remote?user_id=test \
  -H "Content-Type: application/json" \
  -d '{"text": "Привет!", "user_id": "test"}'
# data: {"token": "При", "done": false}
# data: {"token": "вет", "done": false}
# ...
# data: {"token": "", "done": true, "model": "Qwen2.5-1.5B...", "elapsed_ms": 1234}
```

#### UX-фичи

- 🔴🟢 Индикатор состояния сервера в реальном времени
- Автоблокировка ввода при недоступности сервера
- **Постепенное отображение текста** — токены появляются по мере генерации
- **Кнопка ⏹ Stop** — мгновенная остановка генерации с сохранением полученного текста
- Время ответа и скорость генерации (tok/s) под каждым сообщением
- Общий стиль с остальными вкладками (Chat, Local LLM)

#### Результаты тестирования

| Тест | Результат |
|---|---|
| Доступ по сети | ✅ latency 56ms |
| SSE-стриминг (простой запрос) | ✅ ответ ~1.2 сек, 15.9 tok/s |
| SSE-стриминг (сложный запрос) | ✅ 35 сек, 1516 символов C++ кода |
| 5 последовательных запросов | ✅ все успешны, без ошибок |
| Rate limiting | ✅ не обнаружен (llama.cpp без лимитов) |
| Кнопка Stop | ✅ генерация останавливается, текст сохраняется |
| Fallback reasoning_content | ✅ пустой content → берётся reasoning_content |

---

### Day 31 — Ассистент разработчика: RAG по документации проекта + MCP git-инструменты + /help

Ассистент разработчика, который отвечает на вопросы о проекте, используя документацию (README, docs/) и контекст проекта (git-ветка, список файлов, diff).

#### Возможности

- **RAG по документации проекта** — авто-индексация README.md, CLAUDE.md и docs/ при старте
- **MCP Git Server** — 6 инструментов для получения контекста проекта
- **`/help <вопрос>`** — отвечает о структуре, архитектуре и коде проекта на основе RAG + MCP
- **Переключение проектов** — боковая панель с недавними проектами, мгновенное переключение
- **Изолированные коллекции RAG** — отдельная ChromaDB-коллекция на каждый проект
- **Прогресс-бар** — SSE-стриминг этапов при первом переключении на проект
- **Выбор папки проекта** — нативный диалог macOS/Linux/Windows через `osascript`/`zenity`/`powershell`
- **Сворачиваемые источники RAG** — в чате источники свёрнуты по умолчанию, разворачиваются по клику
- **История сообщений** — последние 10 сообщений сохраняются в localStorage, навигация по ArrowUp/ArrowDown

#### Новые файлы

| Файл | Назначение |
|---|---|
| `mcp_git_server/server.py` | MCP-сервер (stdio) с инструментами: `set_project_root`, `get_git_branch`, `get_git_status`, `get_git_diff`, `list_project_files`, `read_file` |
| `mcp_git_client.py` | MCP-клиент для git-сервера, поддерживает смену `project_root` через env |

#### Изменённые файлы

| Файл | Что изменилось |
|---|---|
| `main.py` | `GET/POST /project` + `POST /project/stream` (SSE) — переключение проектов; `GET/DELETE /projects/recent` — список недавних; `POST /pick-folder` — нативный диалог; `GET /browse` + `POST /browse-native` — браузер папок; авто-индексация `README.md` + `CLAUDE.md` + `docs/` при старте и при смене проекта |
| `agent.py` | `/help` без аргументов → список команд; `/help <вопрос>` → RAG-поиск + MCP git-контекст → LLM-ответ о проекте; `_enrich_help_question()` — обогащение вопроса контекстом проекта |
| `mcp_multi.py` | `reconnect_client()` — замена подклиента без перезапуска MCP-стека; улучшена обработка `CancelledError` |
| `rag.py` | Изолированные per-project коллекции: `set_project()`, `delete_project()`, `_collection_name()` с MD5-хешом; улучшено логирование `retrieve()` |
| `static/index.html` | Боковая панель проектов `projects-sidebar`; проект-бар с путём, кнопкой 📂 и Switch; прогресс-бар для загрузки проекта |
| `static/app.js` | `switchProject()` через SSE-стрим с прогресс-баром; `loadRecentProjects()` / `renderRecentProjects()`; `pickFolder()` — нативный диалог; сворачиваемые RAG-источники; история сообщений в localStorage; `setProjectLoading()` |
| `static/style.css` | Стили боковой панели, проект-бара, shimmer-анимации загрузки, прогресс-бара, кнопки 📂, сворачиваемых RAG-источников |

#### MCP Git Server — инструменты

| Инструмент | Описание |
|---|---|
| `set_project_root` | Сменить корневую папку проекта (все остальные инструменты работают с ней) |
| `get_git_branch` | Текущая ветка + последний коммит (hash, автор, дата, сообщение) |
| `get_git_status` | Статус рабочей копии в porcelain-формате (staged/unstaged/untracked) |
| `get_git_diff` | Diff изменений (unstaged по умолчанию, `staged=true` для staged, фильтр по файлу) |
| `list_project_files` | Список файлов проекта с фильтрацией по поддиректории и паттерну |
| `read_file` | Чтение файла проекта с валидацией пути (только внутри project root) |

#### API — новые эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/project` | Информация о текущем проекте (путь, ветка, количество RAG-чанков) |
| `POST` | `/project` | Переключить проект: `{"project_root": "/path/to/project"}` |
| `POST` | `/project/stream` | SSE-стрим переключения с прогресс-событиями (`git` → `rag` → `done`) |
| `GET` | `/projects/recent` | Список недавних проектов (из `memory/recent_projects.json`) |
| `DELETE` | `/projects/recent?path=...` | Удалить проект из недавних + его RAG-коллекцию |
| `POST` | `/pick-folder` | Открыть нативный диалог выбора папки (macOS/Linux/Windows) |

#### Примеры использования /help

```
/help                              → список всех команд + справка
/help Какая архитектура у проекта? → RAG-поиск + git-контекст → развёрнутый ответ
/help Какие Python модули есть?    → перечисление файлов и их назначения
/help Что делает agent.py?         → конкретный ответ про файл
```

#### Команды /help

| Команда | Описание |
|---|---|
| `/help` | Список всех команд + подсказка |
| `/help <вопрос>` | Ответ на вопрос о проекте с использованием RAG и MCP-контекста |

---

### Day 32 — Вкладка Code Review: ревью кода через LLM + GitHub Actions

Добавлена вкладка «Code Review» для автоматического ревью кода с использованием LLM и RAG-контекста проекта. Два режима: ревью текущей ветки (через git MCP) и ревью по вставленному diff.

#### Новые файлы

| Файл | Назначение |
|---|---|
| `code_review.py` | `CodeReviewAgent` — агент ревью кода: собирает diff через MCP, обогащает RAG-контекстом, вызывает LLM, парсит ответ |
| `.github/workflows/pr-review.yml` | GitHub Actions workflow — авто-ревью при открытии/обновлении PR, результат публикуется комментарием |

#### Изменённые файлы

- **`main.py`** — инициализация `CodeReviewAgent` в lifespan; три новых эндпоинта:
  - `GET /review/status` — проверка доступности (модель, git, RAG, текущая ветка, список всех веток)
  - `POST /review/pr` — ревью переданного diff (PR)
  - `POST /review/local` — ревью текущего рабочего дерева (diff через git MCP)
- **`static/index.html`** — новая вкладка `#tab-review`:
  - Переключатель режимов: Current Branch / Manual Diff
  - Выпадающий список base branch (заполняется из git) + бейдж текущей ветки
  - Поле ввода diff + changed files для Manual режима
  - Панель результатов: сводка, категории (Bugs, Architecture, Security, Performance, Recommendations)
  - Каждая категория сворачивается/разворачивается, issues с severity и файлами
  - Блок RAG Sources
- **`static/app.js`** — логика вкладки Code Review:
  - `loadReviewStatus()` — проверка доступности, заполнение списка веток, отображение текущей ветки
  - `runLocalReview()` — ревью текущей ветки через `POST /review/local`
  - `runManualReview()` — ревью diff через `POST /review/pr`
  - `renderReviewResult()` — отрисовка результатов по категориям
  - `Ctrl+Enter` в diff-поле для быстрого запуска
- **`static/style.css`** — стили `.review-page`, `.review-mode-tabs`, `.review-select-branch`, `.review-current-branch`, `.review-result`, категорий, severity-бейджей, `.review-categories` со скроллом

#### UX фичи

- **Выпадающий список base branch** — автоматически заполняется из git, можно выбрать любую локальную ветку
- **Бейдж текущей ветки** — отображается рядом с base branch (например, `day32`)
- **Скроллируемые категории** — при раскрытии категорий с большим количеством issues панель корректно скроллится
- **GitHub Actions** — при PR автоматически запускается ревью через локальный API, результат публикуется комментарием

#### API эндпоинты

```bash
# Статус
curl http://localhost:8000/review/status
# → {"available": true, "current_branch": "day32", "all_branches": ["main", "day32"], ...}

# Ревью текущей ветки
curl -X POST http://localhost:8000/review/local \
  -H "Content-Type: application/json" \
  -d '{"base_branch": "main"}'

# Ревью PR diff
curl -X POST http://localhost:8000/review/pr \
  -H "Content-Type: application/json" \
  -d '{"pr_title": "My PR", "diff_text": "...", "changed_files": ["main.py"]}'
```

#### GitHub Actions Workflow

Workflow `.github/workflows/pr-review.yml` запускается на events `pull_request: [opened, synchronize]`:

1. Checkout репозитория (`fetch-depth: 0` для истории)
2. `git diff origin/<base>...HEAD` — получение diff PR
3. `curl POST /review/pr` — вызов локального API ревью
4. `actions/github-script` — публикация результата как PR-комментарий с форматированием по категориям

Требует `runs-on: self-hosted` (раннер на той же машине, где запущен FirstAgent).

---

### Day 33 — Ассистент поддержки пользователей

Реализован мини-сервис для поддержки пользователей: ассистент отвечает на вопросы о продукте, использует RAG (FAQ + документация), учитывает контекст пользователя и тикета из CRM через MCP-интеграцию.

#### Новые файлы

| Файл | Назначение |
|---|---|
| `mcp_crm_server/server.py` | MCP-сервер CRM (stdio) — 6 инструментов: `search_users`, `get_user`, `get_user_tickets`, `get_ticket`, `search_tickets`, `get_user_context` |
| `mcp_crm_client.py` | MCP-клиент для stdio-соединения с CRM-сервером |
| `support_agent.py` | `SupportAgent` — ассистент поддержки: обогащает запрос контекстом CRM + RAG, вызывает LLM |
| `data/users.json` | 5 тестовых пользователей (разные тарифы, статусы, теги) |
| `data/tickets.json` | 7 тестовых тикетов (авторизация, биллинг, баги, интеграции, блокировка) |
| `docs/support/faq-auth.md` | FAQ: частые проблемы с авторизацией (Google OAuth, сброс пароля, 2FA) |
| `docs/support/faq-billing.md` | FAQ: оплата и тарифы (тарифные планы, смена тарифа, двойное списание, возврат) |
| `docs/support/product-overview.md` | FAQ: обзор продукта ExampleApp (API, экспорт отчётов, блокировка аккаунта) |
| `docs/support/faq-jacarta-overview.md` | FAQ: JC-Mobile SDK Android — обзор, устройства, системные требования, JaCarta Service |
| `docs/support/faq-jacarta-integration.md` | FAQ: JC-Mobile SDK Android — интеграция в Android Studio, состав SDK, сборка примеров |
| `docs/support/faq-jacarta-applets.md` | FAQ: JC-Mobile SDK Android — 4 типа апплетов, полный список примеров (GOST2, PKI, GOST, LICENSE) |
| `docs/support/faq-jacarta-api.md` | FAQ: JC-Mobile SDK Android — API: стандарт PKCS#11 + расширения (PKI, Криптотокен 2 ЭП, Laser) |
| `docs/support/faq-jacarta-troubleshooting.md` | FAQ: JC-Mobile SDK Android — решение проблем (библиотеки, сборка, PIN, токены, архитектура) |

#### Изменённые файлы

- **`main.py`** — импорт `MCPCRMClient` и `SupportAgent`; создание CRM-клиента в lifespan и добавление в `MultiMCPClient`; инициализация `SupportAgent`; автоиндексация `docs/support/` в RAG при старте; 6 новых API-эндпоинтов:
  - `POST /support/chat` — задать вопрос ассистенту (с учётом CRM + RAG)
  - `GET /support/status` — статус CRM, RAG, FAQ
  - `POST /support/users/search` — поиск пользователей в CRM
  - `GET /support/users/{id}` — профиль пользователя
  - `GET /support/users/{id}/tickets` — тикеты пользователя с фильтром по статусу
  - `GET /support/tickets/{id}` — детали тикета
- **`support_agent.py`** — улучшен retrieval: keyword supplement для тех. терминов (CamelCase, русские/английские слова), FAQ source boost (+0.25 приоритет документам `docs/support/`)
- **`static/index.html`** — новая вкладка Support (`#tab-support`):
  - Левая панель: поиск пользователей, карточка контекста, список тикетов, статус-бар
  - Правая панель: чат с ассистентом, бейдж контекста (имя + тикет), источники RAG
- **`static/app.js`** — логика вкладки Support:
  - `searchSupportUsers()` — поиск пользователей через `POST /support/users/search`
  - `selectSupportUser(userId)` — загрузка профиля и тикетов, отрисовка карточки
  - `appendSupportMessage()` — отправка вопроса и отображение ответа с источниками
  - `loadSupportStatus()` — статус CRM, RAG, FAQ при активации вкладки
- **`static/style.css`** — стили `.support-page`, `.support-left`, `.support-search-*`, `.support-user-*`, `.support-ticket-*`, `.support-chat-container`, `.support-context-badge`, `.support-message-sources`

#### Архитектура

```
Вопрос → SupportAgent → CRM MCP (контекст пользователя + тикеты)
                      → RAG (FAQ + документация, с source boost)
                      → LLM (персонализированный ответ)
```

#### Примеры

```bash
# Вопрос с учётом пользователя и тикета
curl -X POST http://localhost:8000/support/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Почему не работает авторизация через Google?",
       "user_identifier":"usr_001","ticket_id":"tkt_101"}'

# Поиск пользователей
curl -X POST http://localhost:8000/support/users/search \
  -H "Content-Type: application/json" \
  -d '{"query":"иван"}'

# Тикеты пользователя
curl http://localhost:8000/support/users/usr_001/tickets?status=open
```

#### Сценарий из задания

«Почему не работает авторизация?» → ассистент находит пользователя Ивана Петрова, его тикет #101, проверяет FAQ по авторизации (`faq-auth.md`) и даёт персонализированный ответ с конкретными шагами по решению проблемы.

#### MCP-инструменты CRM

| Инструмент | Описание |
|---|---|
| `search_users` | Поиск пользователей по имени, email или id |
| `get_user` | Полный профиль пользователя |
| `get_user_tickets` | Тикеты пользователя (с фильтром по статусу) |
| `get_ticket` | Детали тикета (включая переписку) |
| `search_tickets` | Поиск тикетов по ключевым словам и статусу |
| `get_user_context` | Сводка: профиль + активные тикеты + история |
| `create_ticket` | Создать новый тикет (сохраняется в `data/tickets.json`) |
| `update_ticket` | Обновить статус тикета или добавить сообщение |

#### Дополнительные возможности

**Пользователи из `memory/users/`.** CRM читает реальных пользователей приложения, а не статический JSON. Профили заполняются через `/profile` на вкладке Chat. Выбор пользователя — выпадающий список с кнопкой обновления.

**Создание тикетов.** Через API `POST /support/tickets` или форму на вкладке Support (тема, описание, приоритет, категория). Новый тикет автоматически выбирается активным.

**Память диалога.** Ассистент хранит историю разговора в рамках сессии (`session_id`). Follow-up вопросы понимаются без повторения контекста.

**Авто-закрытие тикетов.** Если пользователь пишет «спасибо, помогло», «всё работает» и т.п. — тикет автоматически переводится в `closed`, в переписку добавляется сообщение, UI показывает зелёный баннер и обновляет список.

**Группировка тикетов.** В панели тикеты разделены на «Активные» и «Закрытые», статусы на русском, закрытые полупрозрачные.

---

### Day 34 — File Assistant: ассистент для проактивной работы с файлами

Реализован ассистент, который активно работает с файлами проекта: ищет использования компонентов/API, анализирует код, создаёт отчёты, генерирует документацию. Ассистент сам решает какие инструменты вызывать — задача ставится на уровне цели, а не «открой файл X».

#### Новые файлы

| Файл | Назначение |
|---|---|
| `file_assistant.py` | `FileAssistant` — агент с dynamic tool-calling loop, файловым системным промптом и сессионной памятью |

#### Изменённые файлы

- **`mcp_git_server/server.py`** — 2 новых MCP-инструмента (теперь 8 вместо 6):
  - `search_content` — grep-поиск по проекту (регексы, glob-фильтр, Python fallback без grep)
  - `write_file` — создание/перезапись файлов с режимом `diff_only=true` для превью изменений через git diff
- **`main.py`** — импорт `FileAssistant`; глобальная переменная `file_assistant`; инициализация в `lifespan()` с передачей общего `MultiMCPClient`; 2 API-эндпоинта:
  - `GET /file/status` — доступность агента, количество инструментов, модель
  - `POST /file/query` — выполнить файловую задачу (возвращает ответ, список затронутых файлов, usage)
- **`static/index.html`** — новая вкладка File Assistant (`#tab-file`):
  - Левая панель: статус агента и список затронутых файлов
  - Правая панель: чат с ассистентом, примеры задач в плейсхолдере
- **`static/app.js`** — логика вкладки File Assistant:
  - `loadFileStatus()` — статус агента (tools, модель) при активации вкладки
  - Отправка задачи через `POST /file/query`, отображение ответа и списка `files_affected`
  - Кнопка Clear для сброса истории
- **`static/style.css`** — стили `.file-page`, `.file-left`, `.file-section-title`, `.file-status-bar`, `.file-affected-item`, `.file-chat-container`

#### Архитектура

```
Задача → FileAssistant.execute()
           → _call_api()  ← dynamic tool-calling loop (ChatAgent pattern)
             → LLM решает: search_content(pattern="ChatAgent", glob="*.py")
             → MultiMCPClient → MCPGitClient → mcp_git_server
             → результат возвращается LLM
             → LLM решает: read_file(path="agent.py") для контекста
             → LLM решает: write_file(diff_only=true, ...) — превью
             → финальный ответ + files_affected
```

#### MCP-инструменты (новые)

| Инструмент | Описание |
|---|---|
| `search_content` | Поиск текста/регекса по файлам проекта. Аргументы: `pattern` (обязательный), `glob` (фильтр, например `*.py`), `max_results` (default 50). Использует системный `grep` для скорости, fallback на Python `os.walk` + `re`. |
| `write_file` | Создать/перезаписать файл. Аргументы: `path`, `content`, `diff_only` (default false). При `diff_only=true` возвращает diff без записи. Для существующих файлов использует `git diff --no-index`. |

#### Примеры

```bash
# Поиск использований компонента
curl -X POST http://localhost:8000/file/query \
  -H "Content-Type: application/json" \
  -d '{"task":"Найди все использования ChatAgent в кодовой базе и подготовь сводку"}'

# Проверка паттернов в коде
curl -X POST http://localhost:8000/file/query \
  -H "Content-Type: application/json" \
  -d '{"task":"Проверь все Python файлы на наличие try/except и создай отчёт"}'

# Генерация документации
curl -X POST http://localhost:8000/file/query \
  -H "Content-Type: application/json" \
  -d '{"task":"Сгенерируй CHANGELOG.md на основе последних git-коммитов"}'
```

#### Сценарии из задания

1. **«Найди все использования ChatAgent»** — агент вызывает `search_content("ChatAgent", "*.py")`, находит class definition в `agent.py:42`, импорт и фабрику в `main.py:20,56,103-117`, готовит структурированную сводку. Работает с 2+ файлами.

2. **«Проверь Python файлы на try/except»** — агент вызывает `search_content("try:", "*.py")` + `search_content("except", "*.py")`, анализирует 29 файлов, создаёт табличный отчёт с качественной оценкой для каждого файла.

#### Ключевые решения

- **Dynamic tool calling** — агент использует тот же pattern что и `ChatAgent._call_api` (agent.py:1027-1106): в цикле отправляет tools в LLM, при `finish_reason == "tool_calls"` диспатчит в MCP, добавляет результат и перевызывает LLM. В отличие от `CodeReviewAgent` и `SupportAgent`, которые жёстко кодируют вызовы инструментов.
- **diff_only preview** — перед записью агент инструктирован вызывать `write_file(diff_only=true)`, чтобы пользователь видел изменения до применения.
- **Безопасность** — `write_file` валидирует путь через `_is_safe_path()` (только внутри PROJECT_ROOT); `search_content` ограничен 50 результатами и 30-секундным таймаутом.
- **Переиспользование MCP** — FileAssistant получает уже созданный `MultiMCPClient` из `lifespan()`, новые инструменты появляются автоматически.

---

### Предыдущие доработки

| День | Фича |
|---|---|
| Day 34 | File Assistant: проактивная работа с файлами — grep-поиск, запись с diff-превью, 2 демо-сценария |
| Day 33 | Ассистент поддержки: CRM через MCP, RAG FAQ (включая JaCarta SDK), память диалога, авто-закрытие тикетов |
| Day 31 | Ассистент разработчика: RAG по документации, MCP git, /help, переключение проектов |
| Day 30 | Вкладка Remote LLM: SSE-стриминг, fallback reasoning_content, кнопка Stop, модель Qwen2.5-1.5B (6.5× быстрее) |
| Day 29 | Поддержка HTML и MHTML в RAG-системе |
| Day 28 | Оптимизация локальной модели: параметры, квантование, шаблоны промптов |
| Day 27 | RAG-система подключена к вкладке Local LLM |
| Day 26 | Вкладка Local LLM: чат с Ollama + llama.cpp |
| Day 25 | Панель контрольных вопросов на вкладке RAG |
| Day 24 | Структурированный вывод RAG и отображение источников в чате |
| Day 23 | Выбор модели и прямое API DeepSeek |
| Day 22 | RAG: реранкер, фильтр релевантности и query rewrite |
| Day 21 | Расширенный RAG: метаданные + две стратегии чанкинга + compare + вкладка RAG |
| Day 20 | RAG система на базе Ollama + ChromaDB |
| Day 18 | MCP-сервер поиска и пайплайн «поиск → диаграмма → Telegram» |
| Day 17 | MCP-сервер генерации UML-диаграмм (draw.io) |
| Day 15 | Интеграция MCP погодного сервера (`mcp_weather.py`) |
| Day 14 | Конечный автомат задач (Task FSM) с явными переходами состояний |
| Day 13 | Инварианты (`invariants.py`) — правила поведения агента |
| Day 12 | Глобальный системный промпт, редактируемый через UI |