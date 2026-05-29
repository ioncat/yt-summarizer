# Epic 34: Bulk URL Queue

**Status:** 🔵 Planned  
**Phase:** 2 — Summarization Quality  
**Depends on:** —  
**Blocks:** Epic 35 (Playlist Import)

---

## Strategic Context

Обработка одного видео — это ручной workflow. Пользователь с большим списком контента (курс, канал, исследование) вынужден добавлять видео по одному и ждать каждого. Batch-очередь убирает этот барьер и открывает сценарии неконтролируемой фоновой обработки.

---

## Goal

Пользователь вставляет несколько URL построчно → все попадают в очередь → backend обрабатывает по одному последовательно через выбранный pipeline → пользователь видит статус каждого в очереди.

---

## User Stories

### US-3401: DB schema и queue worker

**Given** backend стартует  
**When** `_migrate_db()` выполняется  
**Then** таблица `processing_queue` существует с колонками:
`id`, `url`, `video_id`, `status`, `pipeline_stages`, `error_message`, `added_at`, `started_at`, `finished_at`, `sort_order`

**Notes for Engineering:**
- `status` ∈ `pending | processing | done | failed | skipped`
- `pipeline_stages` — JSON array: `["extract"]` / `["extract","cleanup"]` / `["extract","cleanup","summary"]`
- `video_id` — заполняется после завершения extraction (связь с `videos` таблицей)
- Queue worker: asyncio background task, старт в `lifespan()`, polling каждые 5 сек
- Worker берёт один `pending` item, выставляет `processing`, запускает pipeline stages последовательно
- На ошибке: `status = failed`, `error_message` заполняется, переходит к следующему
- **Одновременно обрабатывается строго один item** — Ollama не поддерживает параллельные heavy запросы
- DB backup перед миграцией

**Out of Scope:** приоритизация внутри очереди, pause/resume всей очереди

**Edge Cases:**
- Backend рестарт во время обработки → items со статусом `processing` при старте сбрасываются в `pending`
- Дубликат URL в очереди → добавляется (пользователь мог хотеть повторную обработку), не блокируется
- URL недоступен → `status = failed`, message из subtitle_extractor error classification

---

### US-3402: API endpoints

**Given** очередь реализована  
**When** клиент вызывает API  
**Then** доступны:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/queue/bulk` | Принимает `{urls: string[], pipeline_stages: string[]}` → добавляет в очередь → возвращает список добавленных id |
| GET | `/api/queue` | Возвращает все items, сортировка по `sort_order` + `added_at` |
| DELETE | `/api/queue/{id}` | Удаляет pending item. Нельзя удалить processing |
| DELETE | `/api/queue` | Очищает только `pending` items (не трогает processing/done/failed) |

**Notes for Engineering:**
- Validation: каждый URL прогоняется через `extract_video_id()` при добавлении — невалидные отклоняются сразу с указанием строки
- `pipeline_stages` default если не передан: читать из `app_settings` (`queue_default_pipeline`, seed = `["extract"]`)
- `GET /api/queue` включает поля для UI: `id`, `url`, `video_id`, `status`, `error_message`, `added_at`, `started_at`, `finished_at`

**Out of Scope:** pagination для GET /api/queue (при разумном числе видео не нужно)

**Edge Cases:**
- POST с пустым массивом URL → 400
- DELETE processing item → 409 Conflict

---

### US-3403: Frontend — Bulk Add panel на HomePage

**Given** пользователь на HomePage  
**When** кликает "Bulk add" (кнопка рядом с основным полем URL)  
**Then** раскрывается панель:
- `<textarea>` — "Paste URLs, one per line"
- Selector pipeline stages: "Extract only" / "Extract + Cleanup" / "Full pipeline"
- Кнопка "Add to queue (N URLs)" — N обновляется live при вводе
- Кнопка Cancel — скрывает панель

**Notes for Engineering:**
- Парсинг textarea: split по `\n`, trim каждой строки, фильтр пустых
- Валидация на frontend: простой regex на youtube.com/watch или youtu.be — остальное бэкенд отклонит
- После сабмита: панель закрывается, показывается toast "N videos added to queue"
- Не navigates away — пользователь остаётся на странице

**Out of Scope:** drag & drop файла со списком URL, импорт из clipboard API

**Edge Cases:**
- Все URL невалидны → показать ошибки inline под textarea
- Часть валидны, часть нет → добавить валидные, показать список невалидных

---

### US-3404: Frontend — Queue status view

**Given** в очереди есть items  
**When** пользователь открывает Queue страницу (`/queue`) или панель  
**Then** видит список items с колонками: порядок / URL (короткий) / статус / pipeline / время

**Notes for Engineering:**
- Новый nav link "⏱ Queue" рядом с History (показывается только если есть pending/processing items — badge с числом)
- Polling GET /api/queue каждые 3 сек пока есть processing/pending items
- Статусы с иконками: ⏸ pending / ⏳ processing / ✓ done / ❌ failed / — skipped
- `done` items — clickable → navigate to `/result/{video_id}`
- `failed` items — показывают error_message при hover/expand
- Кнопка "Clear completed" — DELETE /api/queue (только pending) + убирает done/failed из UI
- Кнопка "✕" у pending item — DELETE /api/queue/{id}

**Out of Scope:** reorder drag&drop, pause individual items

**Edge Cases:**
- Queue пустая → "No items in queue"
- Processing item нельзя удалить — кнопка disabled с tooltip

---

## Implementation Plan

1. 🔴 **BLOCKER** `models.py` + `database.py` — `processing_queue` таблица + миграция + `app_settings` seed для `queue_default_pipeline`
2. 🔴 **BLOCKER** `queue_service.py` — CRUD для очереди + queue worker (`_queue_worker` asyncio loop, старт в `lifespan`)
3. 🟠 `api.py` — 4 новых endpoint
4. 🟠 `HomePage.tsx` — Bulk Add panel
5. 🟡 `QueuePage.tsx` — новая страница + nav link
6. 🟡 CSS — стили для панели и страницы

---

## Open Questions

- **Queue worker + текущий pipeline** — если пользователь вручную запускает summary пока идёт очередь: два Ollama вызова параллельно? Решение: queue worker проверяет `_SUMMARY_CANCEL_SET` или `summary_status == 'processing'` перед стартом — если занято, ждёт следующего polling tick.
