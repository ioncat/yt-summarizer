# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**YT Summarizer** - Extract, format, and store YouTube video subtitles for quick content review.

**Vision**: Reduce cognitive load by allowing users to scan video content before deciding whether to watch in detail.

**Current Phase**: Phase 1.5 — LLM Text Cleanup (Phase 1 complete, Phase 2 summarization next)

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Frontend | React + TypeScript + Vite |
| Backend | Python + FastAPI |
| Video Processing | yt-dlp (no API keys required) + Node.js (JS runtime for yt-dlp) |
| Database | SQLite (aiosqlite + SQLAlchemy async) |
| Text Format | Markdown (stored in DB) |
| LLM (local) | Ollama — `cas/aya-expanse-8b` (text cleanup + future summarization) |

---

## Development Phases

### ✅ Phase 1: MVP - Subtitle Extraction & Formatting — COMPLETE

All 5 epics done. Full stack running:
- FastAPI backend: subtitle extraction, text formatting, 5 REST endpoints, async background tasks
- React frontend: 4 pages (Home, Processing, Result, History)
- Language UX: shows available languages when requested one is missing, one-click retry

### 🔄 Phase 1.5: LLM Text Cleanup — IN PROGRESS

Optional cleanup step via Ollama (local, no API key). Runs after `text_formatter`, before saving to DB.
- `text_cleaner.py` sends each paragraph to Ollama `/api/chat` with editing instructions
- Model: `cas/aya-expanse-8b` (configurable via `OLLAMA_MODEL` in `.env`)
- If Ollama is unreachable — pipeline continues, `cleaned_text = null`
- DB: `subtitles_formatted.cleaned_text` (nullable Text column, auto-migrated)
- API: `POST /api/process` accepts `enable_cleanup: bool`
- Frontend: checkbox on submit + toggle Original/Cleaned on result page

### 🔮 Phase 2: LLM Summarization
Map-reduce summarization pipeline. See `docs/phase2-architecture.md`. Uses same Ollama infra as Phase 1.5.

### 🔮 Phase 3: Speech-to-Text Fallback
Whisper fallback. Language parameter from Phase 1 carries over directly — no extra user input.

---

## Running Locally

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev        # → http://localhost:3000
```

### Docker (both services)
```bash
cp .env.example .env
docker compose up --build
```

### Required: YouTube cookies
Export from Chrome via "Get cookies.txt LOCALLY" extension → save to `data/www.youtube.com_cookies.txt`.
Set `COOKIES_PATH` in `.env`. Re-export if you get 429 or sign-in errors.

---

## Project Structure

```
yt-summarizer/
├── backend/
│   ├── main.py                      # App entry, DB init, router registration
│   ├── config.py                    # Settings via pydantic-settings (.env)
│   ├── models/
│   │   ├── database.py              # Async engine, session factory, init_db()
│   │   └── models.py                # ORM: Video, SubtitleRaw, SubtitleFormatted, ProcessingTask
│   ├── routers/api.py               # 5 REST endpoints
│   └── services/
│       ├── subtitle_extractor.py    # yt-dlp wrapper, VTT parser, error classification
│       ├── text_formatter.py        # Overlap dedup + time-gap paragraph splitting
│       ├── text_cleaner.py          # Ollama HTTP client, paragraph-by-paragraph LLM cleanup
│       └── video_service.py         # DB CRUD, task lifecycle
├── frontend/
│   ├── src/
│   │   ├── api.ts                   # Typed fetch wrappers for all endpoints
│   │   ├── App.tsx                  # Routes
│   │   ├── index.css                # All styles
│   │   └── pages/                   # HomePage, ProcessingPage, ResultPage, HistoryPage
│   ├── vite.config.ts               # Port 3000, proxy /api → localhost:8000
│   └── Dockerfile                   # Multi-stage: Node builder → nginx
├── data/
│   ├── db/yt_summarizer.sqlite      # SQLite DB (auto-created)
│   └── www.youtube.com_cookies.txt  # YouTube cookies (gitignored)
├── docs/
│   ├── requirements.md              # Functional requirements (all phases)
│   └── phase2-architecture.md       # LLM map-reduce design
└── backlog/
    ├── BACKLOG.md                   # Epic overview + phase roadmap
    └── epics/EPIC-1..5.md           # User stories per epic
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/process` | Submit URL + language + `enable_cleanup` → returns task_id, video_id |
| GET | `/api/status/{task_id}` | Poll status; returns `available_languages` on language error |
| GET | `/api/result/{video_id}` | Formatted subtitle text + metadata |
| GET | `/api/history?page=N` | Paginated history (20 per page) |
| DELETE | `/api/result/{video_id}` | Delete video + all related data |

---

## Key Implementation Details

**Single yt-dlp call**: `--print-json --write-subs --write-auto-subs --sub-lang {lang}` in one subprocess. Two separate calls trigger YouTube 429 rate limiting.

**VTT rolling window**: YouTube auto-captions repeat timestamps with growing text. Keep longest text per timestamp group.

**Overlap deduplication**: Sequential subtitle entries share text via suffix/prefix overlap — strip overlap before joining. Then group by ≥4 sec time gaps → paragraphs.

**Task lifecycle**: `create_pending_task` creates `__pending__{video_id}` placeholder Video + task. On completion, `complete_task` detects existing video by `video_id` (not URL — handles youtu.be vs youtube.com), reassigns task FK, deletes placeholder. Must flush reassignment before delete to avoid ORM cascade nulling FK.

**Language error UX**: When extraction fails with `LANGUAGE_NOT_AVAILABLE`, `available_languages` stored as JSON in `error_message`. Status endpoint parses and returns as separate field. Frontend shows quick-select buttons.

**DB note**: `scalar_one_or_none()` on SubtitleFormatted/Video queries crashes when a video is reprocessed. Always use `.scalars().first()` with `.order_by(created_at.desc())`.

**DB migrations**: No Alembic. `database.py` has `_migrate_db()` — checks `PRAGMA table_info` and runs `ALTER TABLE ... ADD COLUMN` for any new columns. Add entries there when extending the schema.

**Ollama integration**: `text_cleaner.py` calls `POST {OLLAMA_URL}/api/chat`. First does a lightweight `GET /api/tags` to check availability — returns `None` silently if Ollama is down. Model and URL configured via `OLLAMA_URL` / `OLLAMA_MODEL` in `.env`. Same client reused for Phase 2 summarization.

---

## References

- **Functional Requirements**: `docs/requirements.md`
- **Phase 2 LLM Architecture**: `docs/phase2-architecture.md`
- **Effort Log**: `docs/effort-log.md`
- **yt-dlp**: https://github.com/yt-dlp/yt-dlp
- **FastAPI**: https://fastapi.tiangolo.com/
