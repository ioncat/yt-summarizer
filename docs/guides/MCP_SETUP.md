# YT Summarizer — MCP Server Setup

Подключи YT Summarizer к Claude Desktop или Claude Code как инструмент. После настройки можно прямо в чате написать "суммируй это видео" и получить результат без открытия браузера.

## Требования

- YT Summarizer backend запущен (`uvicorn main:app --port 9010`)
- Python-окружение с установленными зависимостями (`pip install -r app/backend/requirements.txt`)

## Настройка Claude Desktop

Открой файл конфигурации Claude Desktop:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

Добавь секцию `mcpServers`:

```json
{
  "mcpServers": {
    "yt-summarizer": {
      "command": "python",
      "args": ["E:/My files/0 My_Dev/my_prj/yt-summarizer/app/mcp_server.py"],
      "env": {
        "YT_SUMMARIZER_URL": "http://localhost:9010"
      }
    }
  }
}
```

Замени путь на абсолютный путь к `mcp_server.py` на своей машине.

Перезапусти Claude Desktop. В интерфейсе появятся 5 инструментов YT Summarizer.

## Настройка Claude Code

Добавь в `.claude/settings.json` проекта или в глобальный `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "yt-summarizer": {
      "command": "python",
      "args": ["/path/to/yt-summarizer/app/mcp_server.py"],
      "env": {
        "YT_SUMMARIZER_URL": "http://localhost:9010"
      }
    }
  }
}
```

## Доступные инструменты

| Инструмент | Описание |
|---|---|
| `process_video(url, language?)` | Извлечь субтитры. Если видео уже обработано — вернуть сразу |
| `get_result(video_id, include_text?)` | Получить результат по video_id |
| `search_history(query?, limit?)` | Поиск по истории обработанных видео |
| `run_cleanup(video_id)` | Запустить AI-очистку текста, дождаться результата |
| `run_summary(video_id)` | Запустить суммаризацию, дождаться результата |

## Примеры использования

```
# Базовое использование
Суммируй это видео: https://www.youtube.com/watch?v=dQw4w9WgXcQ

# С указанием языка
process_video("https://youtube.com/watch?v=...", language="ru")

# Найти видео в истории
search_history("machine learning")

# Получить полный транскрипт
get_result("dQw4w9WgXcQ", include_text=True)
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `YT_SUMMARIZER_URL` | `http://localhost:9010` | URL бэкенда YT Summarizer |

## Устранение проблем

**"Cannot connect to YT Summarizer"** — бэкенд не запущен. Запусти `uvicorn main:app --port 9010` в директории `app/backend/`.

**"Ollama is not available"** — Ollama не запущена или не настроена. Открой настройки YT Summarizer и проверь раздел General.

**Инструменты не появляются в Claude Desktop** — проверь путь к `mcp_server.py` в конфиге (должен быть абсолютный путь) и перезапусти Claude Desktop.
