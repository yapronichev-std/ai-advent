# Changelog

## v0.3.1 (2026-07-23)

Релиз исправляет порядок действий в /release (добавлен fetch --tags, пуш ветки перед тегом) и поправляет ссылку на CHANGELOG.md. Также добавлена новая функциональность: /release теперь предварительно получает теги.

**9 commits** in `v0.3.0..v0.3.1`

### ✨ Новое

- Команда /release теперь выполняет git fetch --tags перед определением версии

### 🐛 Исправления

- Команда /release пушит ветку перед созданием тега, а не только тег
- Ссылка на CHANGELOG.md в релизе указывает на тег, а не на main

### 🔧 Обслуживание

- Обновление CHANGELOG.md для v0.3.1 (5 коммитов)
- Добавлена конфигурация запуска PyCharm (Uvicorn)

<details>
<summary>Все 9 коммитов</summary>

- `3fc72c5` chore: update CHANGELOG.md for v0.3.1
- `f43a265` feat: /release делает git fetch --tags перед определением версии
- `495f45c` chore: update CHANGELOG.md for v0.3.1
- `b540234` chore: update CHANGELOG.md for v0.3.1
- `7b564a8` chore: update CHANGELOG.md for v0.3.1
- `a26ad0a` chore: add PyCharm run configuration (Uvicorn)
- `9f49499` chore: update CHANGELOG.md for v0.3.1
- `b7c93aa` fix: /release пушит ветку перед тегом, а не только тег
- `7c8b048` fix: ссылка на CHANGELOG.md в релизе указывает на тег, а не на main

</details>
