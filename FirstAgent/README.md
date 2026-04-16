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

### Предыдущие доработки

| День | Фича |
|---|---|
| Day 15 | Интеграция MCP погодного сервера (`mcp_weather.py`) |
| Day 14 | Конечный автомат задач (Task FSM) с явными переходами состояний |
| Day 13 | Инварианты (`invariants.py`) — правила поведения агента |
| Day 12 | Глобальный системный промпт, редактируемый через UI |