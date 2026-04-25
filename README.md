# YT Summarizer

Extract, format, and store YouTube video subtitles for quick content review. Paste a URL, pick a language — get clean, readable text without watching the video. Optionally clean up the transcript with a local LLM (Ollama) to fix punctuation and remove filler words.

---

## Quick Start (Docker)

> Requires: Docker, Docker Compose, YouTube cookies file

```bash
# 1. Clone the repo
git clone <repo-url>
cd yt-summarizer

# 2. Export YouTube cookies
#    Install "Get cookies.txt LOCALLY" in Chrome, open youtube.com, export.
#    Save the file as:
cp /path/to/exported-cookies.txt data/www.youtube.com_cookies.txt

# 3. Copy env config
cp .env.example .env

# 4. Build and start
docker compose up --build

# App is available at:
#   Frontend  → http://localhost:3000
#   API       → http://localhost:8000
```

To stop:
```bash
docker compose down
```

---

## Quick Start (Local Dev)

### Requirements

- Python 3.12+
- Node.js 18+ (required by yt-dlp for YouTube bot detection bypass)
- yt-dlp (`pip install yt-dlp` or system package)
- [Ollama](https://ollama.com) with `cas/aya-expanse-8b` *(optional — for AI text cleanup)*

### One-click launch

```bash
# Set up env once
cp .env.example .env
```

**Windows** — double-click `start.vbs`.
Opens Windows Terminal with two split panes (backend + frontend) and launches the browser automatically.

**Linux / macOS**:
```bash
chmod +x start.sh && ./start.sh
# Ctrl+C stops both services
```

### Manual launch (two terminals)

```bash
# Terminal 1 — Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

---

## Configuration (`.env`)

```env
# Path to SQLite database (created automatically)
DATABASE_PATH=../data/db/yt_summarizer.sqlite

# Path to YouTube cookies file (Netscape format)
# Required to bypass YouTube bot detection
COOKIES_PATH=../data/www.youtube.com_cookies.txt

# Debug mode (enables SQLAlchemy query logging)
DEBUG=false

# Ollama — local LLM for text cleanup (optional)
# Install Ollama, then: ollama pull cas/aya-expanse-8b
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=cas/aya-expanse-8b
```

### Ollama setup (AI text cleanup)

Text cleanup runs locally via [Ollama](https://ollama.com) — no API keys, no data leaves the machine.

**1. Install Ollama**
Download and run the installer from [ollama.com](https://ollama.com/download).

**2. Pull a model**
```bash
ollama pull cas/aya-expanse-8b        # recommended — multilingual, 5 GB
```

**3. Set the model in `.env`**
```env
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=cas/aya-expanse-8b
```

To switch models — change one line and restart the backend:
```env
OLLAMA_MODEL=hf.co/CohereLabs/tiny-aya-water-GGUF:F16
```

**Tested models**

| Model | Size | Languages | Notes |
|-------|------|-----------|-------|
| `cas/aya-expanse-8b` | 5 GB | 23 | Recommended. Strong instruction following, good Russian |
| `hf.co/CohereLabs/tiny-aya-water-GGUF:F16` | 6.7 GB | 67 | Newer Cohere model, experimental |
| `hf.co/CohereLabs/tiny-aya-water-GGUF:Q8_0` | ~3.5 GB | 67 | Quantized, faster |

**If Ollama is not running** — the pipeline completes normally, the "Cleaned" tab is shown as greyed-out with a tooltip explaining why.

---

### Cookies setup

YouTube blocks yt-dlp without valid cookies. To export:
1. Install **"Get cookies.txt LOCALLY"** extension in Chrome
2. Open [youtube.com](https://www.youtube.com) and log in
3. Click the extension → Export cookies → Save as `data/www.youtube.com_cookies.txt`

Re-export if you start getting 429 or "sign in required" errors.

---

## How It Works

1. User submits a YouTube URL, selects subtitle language, optionally enables AI cleanup
2. Backend spawns an async background task
3. yt-dlp downloads subtitle metadata + VTT file in a single call (avoids rate limiting)
4. Text formatter deduplicates rolling-window VTT cues, splits into paragraphs by time gaps
5. *(Optional)* Each paragraph is sent to Ollama — punctuation fixed, filler words removed, fragments merged
6. Result stored in SQLite (both original and cleaned versions), displayed in browser with a toggle

**Language behavior**: if the selected language has no subtitles, the UI shows which languages are available with one-click retry buttons. The language parameter carries forward to Phase 3 (Speech-to-Text) — no extra input needed.

**AI cleanup**: runs locally via Ollama — no data leaves the machine. If Ollama is not running, the pipeline completes normally and the toggle simply doesn't appear.

---

## Architecture

```
yt-summarizer/
├── backend/                 # FastAPI + Python
│   ├── main.py              # App entry point, DB init
│   ├── config.py            # Settings (pydantic-settings)
│   ├── models/              # SQLAlchemy ORM + async engine
│   ├── routers/api.py       # REST endpoints
│   └── services/
│       ├── subtitle_extractor.py   # yt-dlp wrapper
│       ├── text_formatter.py       # VTT → clean markdown
│       ├── text_cleaner.py         # Ollama LLM cleanup (paragraph-by-paragraph)
│       └── video_service.py        # DB CRUD
├── frontend/                # React + TypeScript + Vite
│   └── src/
│       ├── api.ts           # Typed fetch wrappers
│       └── pages/           # Home, Processing, Result, History
├── data/
│   ├── db/                  # SQLite database
│   └── www.youtube.com_cookies.txt  # YouTube cookies (gitignored)
└── docs/
    ├── requirements.md      # Functional requirements
    └── phase2-architecture.md  # LLM summarization design
```

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/process` | Submit URL + language + `enable_cleanup` flag |
| GET | `/api/status/{task_id}` | Poll processing status |
| GET | `/api/result/{video_id}` | Get formatted subtitle text |
| GET | `/api/history` | Paginated processing history |
| DELETE | `/api/result/{video_id}` | Delete video and all its data |

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 — Subtitle Extraction | ✅ Done | Extract, format, store, display subtitles |
| Phase 1.5 — LLM Text Cleanup | ✅ Done | Local Ollama cleans up auto-generated transcripts |
| Phase 2 — LLM Summarization | 🔵 Planned | Map-reduce summarization (paragraph → document summary) |
| Phase 3 — Speech-to-Text | 🔵 Planned | Whisper fallback when subtitles unavailable |

See [backlog/BACKLOG.md](backlog/BACKLOG.md) for detailed epic breakdown.
