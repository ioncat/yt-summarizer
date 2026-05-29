# Epic 35: Playlist Import

**Status:** 🔵 Planned  
**Phase:** 2 — Summarization Quality  
**Depends on:** Epic 34 (Bulk URL Queue) ✅ required

---

## Strategic Context

YouTube плейлист — естественная единица контента: курс, подборка, серия лекций. Пользователь должен иметь возможность передать один URL плейлиста вместо того чтобы копировать десятки URL вручную. Вся обработка идёт через очередь Epic 34.

---

## Goal

Пользователь вставляет URL плейлиста → backend извлекает все видео → пользователь видит список и подтверждает → все URL добавляются в очередь Epic 34.

---

## User Stories

### US-3501: Backend — извлечение видео из плейлиста

**Given** передан URL вида `https://www.youtube.com/playlist?list=...`  
**When** `POST /api/queue/playlist` вызван  
**Then** backend возвращает список видео плейлиста: `{title, url, video_id, duration_seconds, thumbnail_url}`

**Notes for Engineering:**
- yt-dlp поддерживает flat-playlist extract: `yt-dlp --flat-playlist --dump-json PLAYLIST_URL`
- `--flat-playlist` — не скачивает ничего, только metadata. Быстро.
- Из JSON: `id` (video_id), `title`, `url`, `duration`
- Запускать через `asyncio.create_subprocess_exec` (тот же паттерн что subtitle_extractor)
- `cookies_path` читать из `app_settings` — YouTube может требовать auth для приватных плейлистов
- Endpoint возвращает preview, НЕ добавляет в очередь сразу — пользователь подтверждает

**Out of Scope:** частные плейлисты без cookies, Mix/Radio плейлисты (yt-dlp их поддерживает, но они бесконечные — ограничить лимитом 200 видео)

**Edge Cases:**
- Невалидный URL → 400
- Плейлист пустой → 200 с пустым списком
- yt-dlp ошибка (приватный, удалён) → 422 с сообщением
- Плейлист > 200 видео → вернуть первые 200, предупреждение в ответе: `"truncated": true`

---

### US-3502: API — подтверждение и постановка в очередь

**Given** пользователь получил preview плейлиста  
**When** подтверждает выбор (все или subset)  
**Then** выбранные URL передаются в `POST /api/queue/bulk` (Epic 34) — переиспользование существующего endpoint

**Notes for Engineering:**
- Отдельного endpoint для "import playlist to queue" не нужно — фронтенд берёт URL из preview и вызывает `POST /api/queue/bulk`
- Два endpoint: `POST /api/queue/playlist/preview` (получить список) и затем `POST /api/queue/bulk` (добавить)

---

### US-3503: Frontend — Playlist import UI

**Given** пользователь на HomePage  
**When** в Bulk Add панели (Epic 34) вводит URL плейлиста и нажимает "Import playlist"  
**Then**:
1. Кнопка переходит в состояние "Fetching..." (spinner)
2. Появляется список видео плейлиста: thumbnail / title / duration / checkbox
3. "Select all" / "Deselect all" controls
4. Показывает название плейлиста и общее число видео
5. Кнопка "Add N selected to queue"

**Notes for Engineering:**
- Playlist URL детектируется автоматически: если вставленный URL содержит `playlist?list=` или `&list=` — показывается кнопка "Import playlist" вместо обычного Add
- После добавления: панель закрывается, toast "N videos added to queue"
- Если `truncated: true` — показать предупреждение "Playlist has more than 200 videos. First 200 added."

**Out of Scope:** сохранение плейлиста для периодического обновления (sync), показ прогресса каждого видео внутри playlist view

**Edge Cases:**
- Плейлист пустой → "This playlist has no videos"
- Ошибка fetch → inline error под полем
- Пользователь не выбрал ни одного видео → кнопка "Add" disabled

---

## Implementation Plan

1. 🔴 **BLOCKER** Epic 34 полностью реализован
2. 🟠 `subtitle_extractor.py` — функция `fetch_playlist_videos(url, cookies_path)` → `list[dict]`
3. 🟠 `api.py` — `POST /api/queue/playlist/preview` endpoint
4. 🟡 `HomePage.tsx` — playlist detection + preview modal/panel
5. 🟡 CSS — стили playlist preview

---

## Complexity

~1–2 дня после Epic 34. Основная работа — yt-dlp flat-playlist call + UI preview. Логика очереди переиспользуется полностью.
