# YT Summarizer — Product Demo

---

## Problem

Video content is expensive to evaluate. A 10-minute video takes 10 minutes just to judge whether it's worth watching. Titles and thumbnails hide the real substance. You end up sitting through the intro, waiting for the point, and often leaving without what you came for.

YT Summarizer solves this: read the content of any YouTube video before deciding to watch it at all.

---

## What It Does

One URL in. Structured content out.

```
URL → Extract subtitles → Clean up text → Summarize → Chat Q&A
```

Each stage runs independently and stores its output separately. You can re-run any stage, swap models, and ask follow-up questions — all within the same interface.

---

## Who Uses It

- **Researchers and students** — extract key points from lectures, talks, and courses without watching every minute.
- **Knowledge workers** — stay on top of video content without the time commitment.
- **Anyone with a backlog** — paste multiple URLs at once, let it process, come back to results.

---

## Key Features

### Language & Structure

- **Auto language detection** — identifies the video's original language and requests the correct subtitles automatically.
- **Chapter-aware formatting** — if the creator added chapters, the output is structured by those chapters with `## Heading` markers. That structure travels intact through every stage: cleanup, summarization, and chat.

### Three Processing Modes (auto-selected by content)

Long-form content — lectures, courses, documentaries — can run to 100,000+ characters. A single LLM call can't handle that. The system picks the right mode automatically:

| Content type | Condition | Mode |
|---|---|---|
| Short video | < 24K chars | **Single-pass** — one LLM call, fast |
| Long video, no chapters | ≥ 24K chars | **Map-Reduce** — split into chunks → summarize each → combine |
| Long structured (with chapters) | ≥ 24K chars + chapters | **Full Extract** — each chapter processed independently, no compression step |

Full Extract is the key one: instead of compressing the whole text into a summary-of-summaries, each chapter is treated as a self-contained document. Nothing is lost to iterative over-summarization.

### Chat Q&A

After a summary is ready, ask questions about the video content. The model already has the context — no re-processing needed.

### Benchmark

Run the same video through 2–4 models side by side. Compare compression ratio, processing time, and output quality per model. Results persist in history across sessions.

### Bulk Queue

Paste a list of URLs — or a playlist URL. The system processes them one by one in the background. Come back when done.

---

## Tech

| | |
|---|---|
| Frontend | React + TypeScript + Vite |
| Backend | Python + FastAPI |
| LLM | Ollama — connect any local or remote model |
| Subtitle extraction | yt-dlp |
| Storage | SQLite |

---
---

# YT Summarizer — Демо продукта

---

## Проблема

Видео дорого обходится когнитивно. 10-минутное видео занимает 10 минут только на то, чтобы понять — стоит ли оно времени. Заголовки и превью скрывают реальное содержание. В итоге смотришь вступление, ждёшь сути, и часто уходишь ни с чем.

YT Summarizer решает это: читаешь содержание любого YouTube-видео — прежде чем решить, смотреть его вообще.

---

## Что делает

Один URL на входе. Структурированный контент на выходе.

```
URL → Извлечение субтитров → Очистка текста → Саммаризация → Чат
```

Каждый этап работает независимо и сохраняет результат отдельно. Можно перезапустить любой этап, сменить модель, задать уточняющие вопросы — всё в одном интерфейсе.

---

## Кому это полезно

- **Исследователи и студенты** — ключевые мысли из лекций, докладов и курсов без просмотра каждой минуты.
- **Knowledge workers** — оставаться в курсе видеоконтента без временных затрат.
- **Те, у кого накопился список** — вставил несколько URL, запустил обработку, вернулся к результатам.

---

## Ключевые функции

### Язык и структура

- **Автодетект языка** — система сама определяет оригинальный язык видео и запрашивает нужные субтитры.
- **Сохранение структуры глав** — если автор разметил видео главами, вывод структурирован по ним с заголовками `## Heading`. Структура проходит через все этапы: очистку, саммаризацию и чат без изменений.

### Три режима обработки (выбираются автоматически)

Длинный контент — лекции, курсы, документалки — может достигать 100 000+ символов. Один LLM-вызов не справится. Система выбирает режим сама:

| Тип контента | Условие | Режим |
|---|---|---|
| Короткое видео | < 24K символов | **Single-pass** — один LLM-вызов, быстро |
| Длинное, без глав | ≥ 24K символов | **Map-Reduce** — нарезка на чанки → саммари каждого → объединение |
| Длинное структурированное (с главами) | ≥ 24K + главы | **Full Extract** — каждая глава обрабатывается отдельно, без шага сжатия |

Full Extract — ключевой режим: вместо компрессии всего текста в summary-of-summaries каждая глава обрабатывается как самостоятельный документ. Ничего не теряется в итеративной саммаризации.

### Чат по видео

После готового саммари — задавай вопросы по содержанию. Модель уже в контексте, повторная обработка не нужна.

### Бенчмарк

Запусти одно видео через 2–4 модели параллельно. Сравни compression ratio, время обработки и качество вывода по каждой модели. Результаты хранятся в истории между сессиями.

### Очередь URL

Вставь список ссылок или URL плейлиста. Система обрабатывает их последовательно в фоне. Возвращайся к результатам когда удобно.

---

## Технологии

| | |
|---|---|
| Frontend | React + TypeScript + Vite |
| Backend | Python + FastAPI |
| LLM | Ollama — подключи любую локальную или облачную модель |
| Субтитры | yt-dlp |
| База данных | SQLite |
