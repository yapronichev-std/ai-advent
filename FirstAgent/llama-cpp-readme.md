# llama.cpp — Локальный LLM движок

## Конфигурация сервера
- **CPU:** 4 vCPU Intel Xeon Gold 6240R @ 2.40GHz (AVX512)
- **RAM:** 7.8 GB
- **GPU:** нет
- **Диск:** 87 GB (74 GB свободно)
- **ОС:** Ubuntu 26.04 LTS

## Расположение
- **Бинарники:** `/opt/llama.cpp/build/bin/`
- **Модели:** `/opt/llama.cpp/models/`
- **Исходники:** `/opt/llama.cpp/`
- **PATH:** добавлен в `/etc/profile.d/llama-cpp.sh`

---

## Установленные модели

| Модель | Файл | Размер | Контекст |
|---|---|---|---|
| Qwen3 4B Q4_K_M | `Qwen3-4B-Q4_K_M.gguf` | 2.4 GB | 32768 |
| Phi-4-mini-instruct 3.8B Q4_K_M | `Phi-4-mini-instruct-Q4_K_M.gguf` | 2.4 GB | 128K |
| Qwen2.5-7B-Instruct Q4_K_M | `Qwen2.5-7B-Instruct-Q4_K_M.gguf` | 4.4 GB | 128K |

---

## Запуск llama-server (OpenAI-совместимый API)

### Qwen3 4B (рекомендуется — оптимальный баланс):
```bash
llama-server -m /opt/llama.cpp/models/Qwen3-4B-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8080 --ctx-size 8192 --threads 4
```

### Phi-4-mini-instruct 3.8B (лучшее рассуждение):
```bash
llama-server -m /opt/llama.cpp/models/Phi-4-mini-instruct-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8080 --ctx-size 8192 --threads 4
```

### Qwen2.5-7B-Instruct (максимальное качество, медленнее):
```bash
llama-server -m /opt/llama.cpp/models/Qwen2.5-7B-Instruct-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8080 --ctx-size 4096 --threads 4
```

### Фоновый запуск с логом:
```bash
nohup llama-server -m /opt/llama.cpp/models/Qwen3-4B-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8080 --ctx-size 8192 --threads 4 \
  > /tmp/llama-server.log 2>&1 &
```

### Остановка сервера:
```bash
pkill -f llama-server
```

### Проверка что сервер работает:
```bash
pgrep -a llama-server
curl -s http://localhost:8080/health
```

---

## API использование (OpenAI-совместимый)

### Список моделей:
```bash
curl http://195.58.153.66:8080/v1/models
```

### Чат (чат-комплишн):
```bash
curl http://195.58.153.66:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-4b",
    "messages": [{"role": "user", "content": "Привет! Как дела?"}],
    "max_tokens": 256,
    "temperature": 0.7
  }'
```

### Чат без thinking-режима (быстрее):
```bash
curl http://195.58.153.66:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-4b",
    "messages": [
      {"role": "system", "content": "Отвечай сразу, без размышлений."},
      {"role": "user", "content": "Столица России?"}
    ],
    "max_tokens": 64,
    "temperature": 0.0
  }'
```

### Эмбеддинги:
```bash
curl http://195.58.153.66:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-4b",
    "input": "Привет, мир!"
  }'
```

---

## Запуск CLI (интерактивный чат)

### Qwen3 4B:
```bash
llama-cli -m /opt/llama.cpp/models/Qwen3-4B-Q4_K_M.gguf \
  --ctx-size 8192 --threads 4 -i --color
```

### Phi-4-mini:
```bash
llama-cli -m /opt/llama.cpp/models/Phi-4-mini-instruct-Q4_K_M.gguf \
  --ctx-size 8192 --threads 4 -i --color
```

### Qwen2.5-7B:
```bash
llama-cli -m /opt/llama.cpp/models/Qwen2.5-7B-Instruct-Q4_K_M.gguf \
  --ctx-size 4096 --threads 4 -i --color
```

### One-shot (один запрос):
```bash
llama-cli -m /opt/llama.cpp/models/Qwen3-4B-Q4_K_M.gguf \
  --ctx-size 4096 --threads 4 -n 256 --temp 0.7 \
  -p "Напиши код на Python для сортировки списка"
```

---

## Сборка из исходников

```bash
cd /opt/llama.cpp
git pull
cmake -B build -DGGML_AVX512=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON
cmake --build build --config Release -j4
```

---

## Скачивание моделей

```bash
cd /opt/llama.cpp/models

# Через wget (пример):
wget -O model.gguf "https://huggingface.co/user/repo/resolve/main/model-Q4_K_M.gguf"

# Через llama-cli (автоматически):
llama-cli -hf bartowski/Qwen_Qwen3-4B-GGUF:Q4_K_M
```

---

## Ожидаемая производительность

| Модель | Prompt (t/s) | Generation (t/s) | RAM |
|---|---|---|---|
| Qwen3 4B Q4_K_M | ~30 | ~5-6 | ~1.9 GB |
| Phi-4-mini Q4_K_M | ~30 | ~5-7 | ~1.9 GB |
| Qwen2.5-7B Q4_K_M | ~20 | ~3-5 | ~4.5 GB |

---

## Решение проблем

### Порт занят:
```bash
ss -tlnp | grep 8080
fuser -k 8080/tcp
```

### Модель не загружается (не хватает памяти):
```bash
free -h
# Уменьшить контекст: --ctx-size 2048
```

### Логи сервера:
```bash
tail -f /tmp/llama-server.log
```

### Перезапуск сервера:
```bash
pkill -f llama-server
sleep 2
llama-server -m /opt/llama.cpp/models/Qwen3-4B-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8080 --ctx-size 8192 --threads 4 \
  > /tmp/llama-server.log 2>&1 &
```