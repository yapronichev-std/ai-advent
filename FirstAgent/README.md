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

### Предыдущие доработки

| День | Фича |
|---|---|
| Day 15 | Интеграция MCP погодного сервера (`mcp_weather.py`) |
| Day 14 | Конечный автомат задач (Task FSM) с явными переходами состояний |
| Day 13 | Инварианты (`invariants.py`) — правила поведения агента |
| Day 12 | Глобальный системный промпт, редактируемый через UI |