# Changelog

## v0.3.1 (2026-07-23)

Релиз содержит исправления для команды /release (добавлен fetch тэгов, исправлена последовательность пуша и тега), а также обновление ссылки на CHANGELOG.md. Внесены сопутствующие служебные изменения.

**8 commits** in `v0.3.0..v0.3.1`

### ✨ Новое

- Команда /release теперь выполняет git fetch --tags перед определением версии

### 🐛 Исправления

- Команда /release теперь пушит ветку перед созданием тега
- Ссылка на CHANGELOG.md в релизе указывает на тег, а не на main

### 🔧 Обслуживание

- Обновлён CHANGELOG.md для v0.3.1 (4 раза)
- Добавлена конфигурация запуска PyCharm (Uvicorn)

<details>
<summary>Все 8 коммитов</summary>

- `f43a265` feat: /release делает git fetch --tags перед определением версии
- `495f45c` chore: update CHANGELOG.md for v0.3.1
- `b540234` chore: update CHANGELOG.md for v0.3.1
- `7b564a8` chore: update CHANGELOG.md for v0.3.1
- `a26ad0a` chore: add PyCharm run configuration (Uvicorn)
- `9f49499` chore: update CHANGELOG.md for v0.3.1
- `b7c93aa` fix: /release пушит ветку перед тегом, а не только тег
- `7c8b048` fix: ссылка на CHANGELOG.md в релизе указывает на тег, а не на main

</details>
