# Epic 45: Claude Desktop Connection UI

**Status:** 🔵 Planned  
**Phase:** 4 — Integrations  
**Depends on:** Epic 44 (MCP Server ✅)  
**Blocks:** —

---

## Strategic Context

Epic 44 реализовал MCP Server, но установка требует ручного редактирования `claude_desktop_config.json`. Это приемлемо для разработчика, но неприемлемо для продуктового сценария: пользователь не должен знать где лежат конфиги Claude Desktop и что туда писать.

Аналог из практики: другое приложение того же автора (Career Agent) реализует кнопку "Connect Claude Desktop" в Settings → Connections. Кнопка находит файл конфига, показывает preview изменений, пишет запись с бэкапом, проверяет что подключение запустилось.

---

## Goal

Пользователь видит кнопку "Connect Claude Desktop" в Settings. Нажимает — приложение само делает всё: находит конфиг, добавляет запись, бэкапит. Показывает статус: Connected / Not connected. Не нужно знать ни про JSON, ни про пути.

---

## User Stories

### US-4501: Подключение Claude Desktop одной кнопкой

**As a** пользователь YT Summarizer  
**I want** нажать кнопку "Connect Claude Desktop"  
**So that** инструменты YT Summarizer появились в моём Claude Desktop без ручного редактирования конфигов

**Given** приложение запущено локально (не Docker), Claude Desktop установлен  
**When** пользователь нажимает "Connect Claude Desktop"  
**Then** приложение находит `claude_desktop_config.json`, добавляет запись `yt-summarizer`, сохраняет бэкап `...config.json.bak`, показывает "Connected"

**Given** Claude Desktop открыт в момент нажатия  
**When** пользователь нажимает "Connect"  
**Then** показывается предупреждение: "Close Claude Desktop first, then press Connect"

**Given** запись уже существует в конфиге  
**When** пользователь открывает Settings → Connections  
**Then** кнопка показывает статус "● Connected" и предлагает "Disconnect" или "Reconnect"

**Notes for Engineering:**
- Конфиг файл:
  - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
  - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Бэкенд знает свой путь через `Path(__file__).parent.parent` → `app/mcp_server.py`
- Запись которую пишем:
  ```json
  {
    "mcpServers": {
      "yt-summarizer": {
        "command": "python",
        "args": ["/absolute/path/to/app/mcp_server.py"],
        "env": { "YT_SUMMARIZER_URL": "http://localhost:9010" }
      }
    }
  }
  ```
- Если конфиг не существует — создать с нуля (`{}` + наша запись)
- Если `mcpServers` уже есть — merge, не перезаписывать другие серверы
- Бэкап: `config.json.bak` рядом с оригиналом, перезаписывается каждый раз

**Out of Scope:** автоматическая проверка что MCP сервер реально подключился (это делает Claude Desktop при следующем запуске)

**Edge Cases:**
- `claude_desktop_config.json` не найден → показать путь и инструкцию "Create it manually"
- Конфиг повреждён (невалидный JSON) → предложить заменить полностью, сохранить бэкап
- Нет прав на запись → показать ошибку с путём файла
- Docker deployment → кнопка неактивна, показывает инструкцию с конфигом для копирования

---

### US-4502: Disconnect и статус подключения

**As a** пользователь  
**I want** видеть статус подключения и иметь возможность отключить  
**So that** контролировать интеграцию без ручного редактирования файлов

**Given** запись существует в конфиге  
**When** пользователь нажимает "Disconnect"  
**Then** запись `yt-summarizer` удаляется из `mcpServers`, другие серверы остаются

**Given** Settings → Connections открыт  
**When** страница загружается  
**Then** `GET /api/mcp/status` проверяет конфиг и показывает актуальный статус (без поллинга)

**Notes for Engineering:**
- Статусы: `connected` | `not_connected` | `file_not_found` | `docker_mode`
- `docker_mode`: бэкенд запущен в контейнере (детектировать через `/.dockerenv` или env var `DOCKER=true`)

**Out of Scope:** автоматическое переподключение при изменении пути к mcp_server.py

**Edge Cases:**
- Файл изменился с момента последнего подключения — всё равно показывать актуальный статус на основе `GET /api/mcp/status`

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/mcp/status` | Проверяет конфиг, возвращает `{status, config_path, entry_exists}` |
| POST | `/api/mcp/connect` | Добавляет запись, делает бэкап, возвращает `{success, backup_path}` |
| DELETE | `/api/mcp/connect` | Удаляет запись `yt-summarizer` из конфига |

---

## Frontend

Settings → новая вкладка "Connections" (или раздел в General):

```
┌─────────────────────────────────────────────────────────┐
│ Claude Desktop                                          │
│ Lets Claude work with your videos directly in chat      │
│                                                         │
│  ● Connected                    [Disconnect]            │
│  Entry: yt-summarizer in ~/AppData/Roaming/Claude/...  │
└─────────────────────────────────────────────────────────┘
```

Или когда не подключено:
```
┌─────────────────────────────────────────────────────────┐
│ Claude Desktop                                          │
│ Lets Claude work with your videos directly in chat      │
│                                                         │
│  ○ Not connected          [Connect Claude Desktop]      │
└─────────────────────────────────────────────────────────┘
```

Docker mode:
```
┌─────────────────────────────────────────────────────────┐
│ Claude Desktop                                          │
│ Running in Docker — manual setup required               │
│                                                         │
│  Add to claude_desktop_config.json:                     │
│  [  code block с конфигом  ]  [Copy]                    │
└─────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

1. 🔴 **BLOCKER** `routers/api.py` — 3 эндпоинта: `GET/POST/DELETE /api/mcp/connect`. Утилита `_find_claude_config()` (cross-platform), `_read_config()`, `_write_config()` с бэкапом
2. 🟠 `SettingsPage.tsx` — новая вкладка "Connections", компонент `ClaudeDesktopCard`
3. 🟡 Docker-mode детект: проверить `/.dockerenv` или env `DOCKER=1`

**Оценка:** ~2–3 часа

---

## Decisions

- **Preview перед записью**: нет. Путь к `mcp_server.py` вычисляется автоматически и не требует подтверждения пользователем. Просто нажал → записалось → "Connected".
- **Анимация/прогресс**: нет, операция мгновенная.
