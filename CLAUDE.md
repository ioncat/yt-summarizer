# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠️ Backlog & Epics Convention

**Every epic and user story MUST follow `docs/product-delivery-conventions.md`.**  
Read it before creating or editing any epic file.

Key requirements:
- Acceptance Criteria in **Given / When / Then** format (not bullet points)
- **Edge Cases** as a separate section per user story
- **Out of Scope** explicit in each user story
- **Notes for Engineering** (not "Implementation Notes")
- Definition of Ready must be met before starting implementation

---

## Project Overview

**YT Summarizer** - Extract, format, and store YouTube video subtitles for quick content review.

**Vision**: Reduce cognitive load by allowing users to scan video content before deciding whether to watch in detail.

**Current Phase**: Phase 1.5 — Complete ✅ (Epics 6–16 done; 8 dropped)

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Frontend | React + TypeScript + Vite |
| Backend | Python + FastAPI |
| Video Processing | yt-dlp (no API keys required) + Node.js (JS runtime for yt-dlp) |
| Database | SQLite (aiosqlite + SQLAlchemy async) |
| Text Format | Markdown (stored in DB) |
| LLM (local) | Ollama — `cas/aya-expanse-8b` (text cleanup + summarization) |

---

## Development Phases

### ✅ Phase 1: MVP - Subtitle Extraction & Formatting — COMPLETE

All 5 epics done. Full stack running:
- FastAPI backend: subtitle extraction, text formatting, 5 REST endpoints, async background tasks
- React frontend: 4 pages (Home, Processing, Result, History)
- Language UX: shows available languages when requested one is missing, one-click retry

### 🔄 Phase 1.5: LLM Text Cleanup — IN PROGRESS

#### Epic 6 ✅ — Manual AI Cleanup
- `text_cleaner.py` sends each paragraph to Ollama `/api/chat` with editing instructions
- Model configurable via `config.py` (`ollama_model`), overridable per-stage via Settings
- If Ollama unreachable — `cleaned_text = null`, `cleanup_status = null`
- DB: `subtitles_formatted.cleaned_text` + `cleanup_status` (null | processing | done | failed)
- API: `POST /api/result/{video_id}/cleanup` — triggers background cleanup
- API: `GET /api/health` — returns `{backend, ollama}` status
- Frontend: "✦ Clean with AI" button → polling → Cleaned tab; StatusBar in nav (two dots)

#### Epic 7 ✅ — Settings Page
- `pipeline_settings` DB table: per-stage system_prompt, user_prompt_template, model
- Service layer: `get_all_settings`, `save_stage_settings`, `reset_stage_settings`
- API: `GET /api/settings`, `PUT /api/settings/{stage}`, `DELETE /api/settings/{stage}`, `GET /api/models`
- Frontend: `/settings` page — tabs (General, AI Cleanup, Summarization locked)
- `text_cleaner.py` reads prompts/model from DB via `_run_cleanup`; falls back to `DEFAULT_*` constants

#### Epic 8 ❌ — Markdown Rendering (Dropped)
- Tested react-markdown + Markdown prompt rule — LLM output inconsistent. Reverted to plain text.

#### Epic 9 ✅ — Per-Tab Character Count
- Result page shows separate character counts per tab
- Subtitles tab: `result.char_count` (from DB) with fallback to `result.formatted_text?.length`
- Cleaned tab: computed from `result.cleaned_text?.length` on the frontend
- Shows `—` on Cleaned tab when no cleaned text available

#### Epic 11 ✅ — Inline Model Selector on Result Page
- Dropdown next to cleanup button on `/result/:videoId` — auto-saves on change, no Save button
- Preserves existing prompts via `cleanupPromptsRef` (only model changes)
- Disabled with tooltip when Ollama is offline
- Style: `.model-select-inline` in `index.css`

#### Epic 12 ✅ — Cancel Cleanup
- In-memory `_CANCEL_SET` in `api.py` tracks active cancel signals
- `is_cancelled` lambda passed to `clean_text()` — checked before each paragraph
- API: `DELETE /api/result/{video_id}/cleanup` — adds video_id to cancel set
- On cleanup finish: if cancelled → `reset_cleanup_status`; else → `finish_cleanup`
- `_CANCEL_SET.discard(video_id)` called in `trigger_cleanup` to clear stale flags on re-run

#### Epic 13 ✅ — Settings 2.0 (All Config via Web UI)
- `app_settings` DB table: key-value store (`ollama_url`, `ytdlp_path`, `cookies_path`)
- Seeded from config.py defaults on first launch (`_seed_app_settings`)
- `config.py` now infrastructure-only (host, port, DB path, CORS) — no user-facing settings
- `subtitle_extractor.py` accepts `ytdlp_path` as parameter (no module-level constant)
- `text_cleaner.py` accepts `ollama_url` as parameter; no model default — must be set by user
- `api.py` reads `cookies_path`, `ytdlp_path`, `ollama_url` from DB before each operation
- API: `PUT /api/settings/app`, `POST /api/settings/upload-cookies`
- `GET /api/settings` now returns `{app, cleanup, summarization}`
- Frontend: Settings page redesigned with tabs (General / AI Cleanup / Summarization)
- Notifications: warning banners for missing required fields on Settings, Home, Result pages
- Cookie upload via web (multipart, saved to `data/www.youtube.com_cookies.txt`)
- History page: char_count added to each item

#### Epic 14 ✅ — Cleanup Timer
- `cleanup_started_at` and `cleanup_finished_at` columns on `subtitles_formatted` (added via `_migrate_db`)
- Written via raw SQL (`strftime("%Y-%m-%d %H:%M:%S.%f")` — space separator required for SQLAlchemy DateTime parsing)
- `get_result()` computes `cleanup_duration_seconds` from ORM datetime subtraction
- Frontend: "Cleaned in X:XX" shown in meta section when `cleanup_duration_seconds != null`

#### Epic 10 ✅ — Auto-Pipeline Toggle
- Checkbox "Run AI cleanup automatically" on Home page (localStorage, persisted)
- Pre-flight validation in `handleSubmit`: checks `ollama_url`, `cleanup.model`, `summarization.model` — shows bullet list of issues, blocks submit
- ProcessingPage: three stages ① Extracting → ② Cleaning → ③ Summarizing; spinner on active, ✓ on done
- After all stages → navigate to `/result/{videoId}`

#### Epic 15 ✅ — LLM Summarization (Single-pass)
- `text_summarizer.py`: single Ollama request, 180s timeout, temperature 0.2, cancel support
- DB columns: `summary_text`, `summary_status`, `summary_model`, `summary_started_at`, `summary_finished_at` on `subtitles_formatted`
- `_SUMMARY_CANCEL_SET` in `api.py` — same pattern as `_CANCEL_SET`
- API: `POST /api/result/{video_id}/summary`, `DELETE /api/result/{video_id}/summary`
- Result page: Summary tab, tab-aware actions bar (controls change with active tab), "Summarized in X:XX · model" in meta
- Input: `cleaned_text` if available, else `formatted_text`

#### Epic 16 ✅ — Cancel for Auto-Pipeline
- "✕ Stop pipeline" button on ProcessingPage during stages ② and ③
- Stage ②: calls `cancelCleanup(videoId)`; Stage ③: calls `cancelSummary(videoId)`
- Clears `cleanupIntervalRef`, navigates to `/result/{videoId}` immediately
- Button not shown during stage ① (no cancel endpoint for task extraction)

#### Epic 22 ✅ — Auto Language Detection
- `_detect_language(info)` in `subtitle_extractor.py`: checks `-orig` key in `automatic_captions` → manual subs → first auto-caption key → `language` field → fallback `"ru"`
- `_fetch_metadata()`: lightweight `--skip-download --print-json` call (no subtitle download)
- `extract_subtitles()`: when `language == "auto"`, calls `_fetch_metadata()` + `_detect_language()`, then proceeds with detected language
- Two-call yt-dlp flow; first call has no download so 429 risk is low
- Frontend: `HomePage.tsx` — `"auto"` as first option and default in language selector

#### Epic 23 ✅ — Chapter-Aware Subtitle Formatting
- `VideoMetadata.chapters: list[dict] | None` — parsed from `info["chapters"]` in `_build_metadata()`
- `Video.chapters` JSON column in DB (migration in `_migrate_db()`)
- `text_formatter.py`: two branches — `_format_with_chapters()` groups subtitles by chapter time boundaries; `_format_with_gaps()` is existing 4s gap logic
- `format_subtitles(entries, chapters=None)` selects branch; returns `has_chapters: bool`
- Output with chapters: `## Chapter Title\n\nsubtitle text...` per chapter
- Segments outside chapter boundaries assigned to nearest preceding chapter
- Empty chapters (no subtitles) skipped — no empty headings
- Fallback: if `chapters` is None or empty → existing gap-based formatting

#### Epic 24 ✅ — Completion Notifications
- `notify(title, body?)` in `ResultPage.tsx`: sets `document.title = "✓ {title}"`, reverts after 10s; fires `new Notification()` only when `document.hidden`
- `requestNotifyPermission()`: calls `Notification.requestPermission()` if `permission === "default"` — called lazily from `handleCleanup()` / `handleSummarize()`
- Triggers on `processing → done` transition in `loadResult()` (same place tab auto-switching happens)
- `originalTitleRef` stores original title on mount; restored on unmount and on `visibilitychange`

### 🔮 Phase 2: Summarization Quality
Map-reduce / chunked summarization for long texts. See `docs/phase2-architecture.md`.

### 🔮 Phase 3: Speech-to-Text Fallback
Whisper fallback. Language parameter from Phase 1 carries over directly — no extra user input.

---

## Running Locally

### Backend
```bash
cd app/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd app/frontend
npm install
npm run dev        # → http://localhost:3000
```

### Docker (both services)
```bash
cp .env.example .env
docker compose up --build
```

### Required: YouTube cookies
Export from Chrome via "Get cookies.txt LOCALLY" extension → save to `app/data/www.youtube.com_cookies.txt`.
Set `COOKIES_PATH` in `.env`. Re-export if you get 429 or sign-in errors.

---

## Project Structure

```
yt-summarizer/
├── app/
│   ├── backend/
│   │   ├── main.py                      # App entry, DB init, router registration
│   │   ├── config.py                    # Settings via pydantic-settings (.env)
│   │   ├── models/
│   │   │   ├── database.py              # Async engine, session factory, init_db()
│   │   │   └── models.py                # ORM: Video, SubtitleRaw, SubtitleFormatted, PipelineSettings, AppSetting, ProcessingTask
│   │   ├── routers/api.py               # REST endpoints
│   │   └── services/
│   │       ├── subtitle_extractor.py    # yt-dlp wrapper, VTT parser, error classification
│   │       ├── text_formatter.py        # Overlap dedup + time-gap paragraph splitting
│   │       ├── text_cleaner.py          # Ollama HTTP client, paragraph-by-paragraph LLM cleanup
│   │       ├── text_summarizer.py       # Ollama HTTP client, single-pass LLM summarization
│   │       └── video_service.py         # DB CRUD, task lifecycle, pipeline settings CRUD
│   ├── frontend/
│   │   ├── src/
│   │   │   ├── api.ts                   # Typed fetch wrappers for all endpoints
│   │   │   ├── App.tsx                  # Routes
│   │   │   ├── index.css                # All styles
│   │   │   ├── components/StatusBar.tsx # Backend + Ollama health dots in nav
│   │   │   └── pages/                   # HomePage, ProcessingPage, ResultPage, HistoryPage, SettingsPage
│   │   ├── vite.config.ts               # Port 3000, proxy /api → localhost:8000
│   │   └── Dockerfile                   # Multi-stage: Node builder → nginx
│   └── data/
│       ├── db/yt_summarizer.sqlite      # SQLite DB (auto-created, gitignored)
│       └── www.youtube.com_cookies.txt  # YouTube cookies (gitignored)
├── docs/
│   ├── backlog/                         # Epics and user stories
│   │   ├── BACKLOG.md
│   │   └── epics/
│   ├── requirements.md                  # Functional requirements (all phases)
│   ├── effort-log.md                    # Session time log
│   └── phase2-architecture.md           # LLM map-reduce design
├── .env.example
├── .gitignore
├── CLAUDE.md
├── docker-compose.yml
├── docker-compose.dev.yml
├── Makefile
└── README.md
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/process` | Submit URL + language → returns task_id, video_id |
| GET | `/api/status/{task_id}` | Poll status; returns `available_languages` on language error |
| GET | `/api/result/{video_id}` | Formatted subtitle text + metadata + cleanup_status |
| GET | `/api/history?page=N` | Paginated history (20 per page) |
| DELETE | `/api/result/{video_id}` | Delete video + all related data |
| POST | `/api/result/{video_id}/cleanup` | Trigger background AI cleanup |
| DELETE | `/api/result/{video_id}/cleanup` | Cancel running cleanup |
| POST | `/api/result/{video_id}/summary` | Trigger background summarization |
| DELETE | `/api/result/{video_id}/summary` | Cancel running summarization |
| GET | `/api/health` | `{backend: true, ollama: true/false}` |
| GET | `/api/settings` | All settings: `{app, cleanup, summarization}` |
| PUT | `/api/settings/app` | Save app settings (ollama_url, ytdlp_path, cookies_path) |
| PUT | `/api/settings/{stage}` | Save pipeline settings for a stage |
| DELETE | `/api/settings/{stage}` | Reset stage to hardcoded defaults |
| GET | `/api/models` | Available Ollama models (live from Ollama) |
| POST | `/api/settings/upload-cookies` | Upload cookies.txt file |

---

## Key Implementation Details

**Single yt-dlp call**: `--print-json --write-subs --write-auto-subs --sub-lang {lang}` in one subprocess. Two separate calls trigger YouTube 429 rate limiting.

**VTT rolling window**: YouTube auto-captions repeat timestamps with growing text. Keep longest text per timestamp group.

**Overlap deduplication**: Sequential subtitle entries share text via suffix/prefix overlap — strip overlap before joining. Then group by ≥4 sec time gaps → paragraphs.

**Task lifecycle**: `create_pending_task` creates `__pending__{video_id}` placeholder Video + task. On completion, `complete_task` detects existing video by `video_id` (not URL — handles youtu.be vs youtube.com), reassigns task FK, deletes placeholder. Must flush reassignment before delete to avoid ORM cascade nulling FK.

**Language error UX**: When extraction fails with `LANGUAGE_NOT_AVAILABLE`, `available_languages` stored as JSON in `error_message`. Status endpoint parses and returns as separate field. Frontend shows quick-select buttons.

**DB note**: `scalar_one_or_none()` on SubtitleFormatted/Video queries crashes when a video is reprocessed. Always use `.scalars().first()` with `.order_by(created_at.desc())`.

**DB migrations**: No Alembic. `database.py` has `_migrate_db()` — checks `PRAGMA table_info` and runs `ALTER TABLE ... ADD COLUMN` for any new columns. Add entries there when extending the schema.

**⚠️ DB backup rule**: Before ANY schema change (new column, new table, model change) — back up the database first:
```bash
copy data\db\yt_summarizer.sqlite data\db\yt_summarizer.sqlite.bak
```
Do this BEFORE restarting the backend with new model/migration code. No exceptions.

**Ollama integration**: `text_cleaner.py` calls `POST {ollama_url}/api/chat`. First does a lightweight `GET /api/tags` to check availability — returns `None` silently if Ollama is down. `ollama_url` and model read from DB (`app_settings` + `pipeline_settings`) at request time — never from config. Same client reused for Phase 2 summarization.

**App settings (single source of truth)**: `app_settings` table stores `ollama_url`, `ytdlp_path`, `cookies_path`. Seeded from `config.py` on first launch. After that, managed exclusively via web UI (Settings → General). `config.py` is infrastructure-only.

**No model default**: `text_cleaner.py` has no fallback model. If model is null → cleanup returns None → status `failed`. User must select a model in Settings → AI Cleanup.

---

## Pre-release Checklist

Before shipping to production, remove all debug `console.error` calls added across the frontend pages. They were added intentionally during development to surface API errors in the browser console. Search for `console.error` in `frontend/src/pages/` and `frontend/src/api.ts` and remove or replace with proper error reporting.

---

## References

- **Functional Requirements**: `docs/requirements.md`
- **Phase 2 LLM Architecture**: `docs/phase2-architecture.md`
- **Effort Log**: `docs/effort-log.md`
- **yt-dlp**: https://github.com/yt-dlp/yt-dlp
- **FastAPI**: https://fastapi.tiangolo.com/
