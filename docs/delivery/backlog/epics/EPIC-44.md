# Epic 44: MCP Server

**Status:** 🔵 Planned  
**Phase:** 4 — Integrations  
**Depends on:** Epic 15 (Summary), Epic 34 (Queue)  
**Blocks:** —

---

## Strategic Context

YT Summarizer сейчас — замкнутый веб-инструмент. Пользователь открывает браузер, вставляет URL, переключается между вкладками. Это работает, но разрывает рабочий процесс: пользователь уже находится в Claude или другом AI-агенте, и вынужден переключаться в браузер ради одного действия.

MCP Server превращает YT Summarizer в **инструмент**, которым может пользоваться любой MCP-клиент — Claude Desktop, агенты на базе Claude API, Cursor, Zed. Пользователь говорит "суммируй это видео" прямо в чате, не открывая браузер.

---

## Goal

Запустить MCP Server как отдельный процесс (stdio transport для Claude Desktop) или как SSE-эндпоинт рядом с FastAPI. Клиент передаёт URL — MCP-сервер запускает обработку, ждёт результата и возвращает текст. Дополнительно: поиск по истории, получение существующих результатов, запуск отдельных стадий.

---

## User Stories

### US-4401: Инструменты обработки видео

**As a** пользователь Claude Desktop или AI-агент  
**I want** вызвать инструмент `process_video` с YouTube URL  
**So that** получить субтитры или summary без открытия браузера

**Given** YT Summarizer запущен и MCP Server доступен  
**When** клиент вызывает `process_video(url, language?)`  
**Then** сервер ставит видео в очередь, ждёт завершения (polling), возвращает `{video_id, title, summary_text | formatted_text}`

**Given** видео уже обработано  
**When** вызывается `process_video` с тем же URL  
**Then** возвращается существующий результат без повторной обработки

**Notes for Engineering:**
- Синхронный паттерн с polling: MCP-инструмент делает `POST /api/queue/bulk`, затем поллит `GET /api/result/{video_id}` каждые 3с до `status=done` или timeout (5 мин)
- Возвращает `summary_text` если есть, иначе `formatted_text`
- Если Ollama недоступна — возвращает только субтитры с пометкой `summary_unavailable: true`
- `language` опционально, по умолчанию `"auto"`

**Out of Scope:** загрузка локальных файлов через MCP, статус-стрим в реальном времени (SSE из MCP-инструмента)

**Edge Cases:**
- URL невалидный → ошибка с понятным сообщением
- Видео слишком длинное, processing занимает > 5 мин → timeout с объяснением и `video_id` для последующего `get_result`
- YT Summarizer backend недоступен → MCP-инструмент выбрасывает ошибку с подсказкой запустить сервер

---

### US-4402: Инструменты чтения результатов

**As a** пользователь или агент  
**I want** получить результат уже обработанного видео  
**So that** использовать данные из истории без повторной обработки

**Given** видео есть в истории  
**When** вызывается `get_result(video_id)`  
**Then** возвращается `{title, url, summary_text, cleaned_text, formatted_text, duration, language, created_at}`

**Given** нужно найти видео по теме  
**When** вызывается `search_history(query?, limit?)`  
**Then** возвращается список `[{video_id, title, url, has_summary, created_at}]`, отфильтрованный по query (поиск по заголовку и автору)

**Notes for Engineering:**
- `get_result` — прокси к `GET /api/result/{video_id}`
- `search_history` — прокси к `GET /api/history?search={query}`
- Возвращать только нужные поля, не весь `ResultResponse` (MCP-ответы идут в контекст LLM — важна компактность)
- Длинные тексты (`formatted_text` > 20K символов) — обрезать с пометкой `truncated: true` и полной длиной

**Out of Scope:** полный текст субтитров для очень длинных видео по умолчанию (слишком большой для контекста)

**Edge Cases:**
- `video_id` не найден → ошибка `not_found` с понятным сообщением
- `search_history` без query → возвращает последние N видео

---

### US-4403: Инструменты запуска стадий

**As a** пользователь или агент  
**I want** запустить отдельные стадии обработки (cleanup, summary) для уже извлечённых субтитров  
**So that** управлять пайплайном шагами, не перезапуская всё с нуля

**Given** у видео есть `formatted_text` но нет `summary_text`  
**When** вызывается `run_summary(video_id)`  
**Then** запускается суммаризация, инструмент ждёт завершения, возвращает `{summary_text, duration_seconds, model}`

**Given** у видео есть `formatted_text` но нет `cleaned_text`  
**When** вызывается `run_cleanup(video_id)`  
**Then** запускается AI-cleanup, инструмент ждёт, возвращает `{cleaned_text, duration_seconds, model}`

**Notes for Engineering:**
- Те же прямые эндпоинты (`POST /api/result/{video_id}/cleanup`, `.../summary`) что используют локальные файлы
- Polling до `status=done|failed`, timeout 5 мин
- Если Ollama недоступна — сразу ошибка (проверить `GET /api/health` перед запуском)

**Out of Scope:** `run_mindmap` (низкий приоритет для MCP-использования), отмена через MCP

**Edge Cases:**
- `video_id` не существует → ошибка
- Стадия уже запущена (`status=processing`) → ждать её завершения, не запускать повторно
- model не настроена → ошибка с подсказкой открыть Settings

---

### US-4404: Установка и конфигурация

**As a** разработчик или опытный пользователь  
**I want** настроить MCP Server за 5 минут  
**So that** использовать инструменты в Claude Desktop без написания кода

**Given** пользователь следует инструкции  
**When** добавляет MCP Server в `claude_desktop_config.json` и перезапускает Claude Desktop  
**Then** инструменты `process_video`, `get_result`, `search_history`, `run_summary`, `run_cleanup` появляются в Claude Desktop

**Notes for Engineering:**
- Transport: **stdio** — стандарт для локального MCP в Claude Desktop
- Сервер читает `BASE_URL` из переменной среды (default: `http://localhost:8000`)
- Зависит только от `mcp` и `httpx` — не тянет весь backend
- Конфиг для Claude Desktop:
```json
{
  "mcpServers": {
    "yt-summarizer": {
      "command": "python",
      "args": ["E:/path/to/yt-summarizer/app/mcp_server.py"],
      "env": { "YT_SUMMARIZER_URL": "http://localhost:8000" }
    }
  }
}
```
- Документация в `docs/guides/MCP_SETUP.md`: установка, конфиг, примеры запросов

**Out of Scope:** HTTP SSE transport (в первой версии), Docker-обёртка для MCP Server, аутентификация

**Edge Cases:**
- YT Summarizer backend не запущен при старте MCP Server → инструменты доступны, но каждый вызов возвращает ошибку с подсказкой запустить backend

---

## Архитектура

```
Claude Desktop / AI Agent
        │ MCP (stdio)
        ▼
app/mcp_server.py          ← новый файл, ~150 строк
   mcp.Server + tools
        │ HTTP (httpx)
        ▼
FastAPI (localhost:8000)    ← существующий backend
   /api/queue/bulk
   /api/result/{video_id}
   /api/history
   /api/result/{id}/cleanup
   /api/result/{id}/summary
   /api/health
```

**Почему HTTP-прокси, а не прямой импорт сервисов:**
- MCP Server запускается как отдельный процесс без доступа к общей памяти и DB-сессиям FastAPI
- Переиспользует всю существующую логику без дублирования
- Проще тестировать — MCP server = тонкий клиент

---

## Инструменты MCP (итог)

| Инструмент | Аргументы | Описание |
|---|---|---|
| `process_video` | `url`, `language?` | Поставить в очередь + дождаться результата |
| `get_result` | `video_id`, `include_text?` | Получить существующий результат |
| `search_history` | `query?`, `limit?` | Поиск по истории видео |
| `run_cleanup` | `video_id` | Запустить AI-cleanup + дождаться |
| `run_summary` | `video_id` | Запустить суммаризацию + дождаться |

---

## Implementation Plan

1. 🔴 **BLOCKER** `app/mcp_server.py` — MCP Server с stdio transport, 5 инструментов как `httpx`-прокси к FastAPI, синхронный polling
2. 🟠 Зависимости: добавить `mcp>=1.0`, `httpx` в `requirements.txt` (httpx уже есть)
3. 🟡 `docs/guides/MCP_SETUP.md` — руководство по установке для Claude Desktop + примеры
4. 🟢 Тест вручную: Claude Desktop → "суммируй https://youtube.com/watch?v=..." → результат

**Оценка:** ~3–4 часа работы

---

## Open Questions

- Нужен ли `run_cleanup` + `run_summary` отдельно, или достаточно `process_video` с `pipeline: ['extract', 'cleanup', 'summary']`? Оставить оба варианта — разные сценарии.
- Как возвращать очень длинные субтитры (30K+ символов)? Возвращать только `summary_text` + предлагать `include_full_text=true` как явный аргумент.
