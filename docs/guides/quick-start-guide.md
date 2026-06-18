# Quick Start Guide

---

## Docker

> Requires: Docker, Docker Compose, YouTube cookies file

```bash
# 1. Clone the repo
git clone <repo-url>
cd yt-summarizer

# 2. Export YouTube cookies (see Cookies setup below)
cp /path/to/exported-cookies.txt data/www.youtube.com_cookies.txt

# 3. Copy env config
cp .env.example .env

# 4. Build and start
docker compose up --build

# Frontend  → http://localhost:3000
# API       → http://localhost:8000
```

```bash
# Stop
docker compose down
```

---

## Local Dev

### Requirements

- Python 3.12+
- Node.js 18+ (required by yt-dlp for YouTube bot detection bypass)
- yt-dlp (`pip install yt-dlp` or system package)
- [Ollama](https://ollama.com) *(optional — for AI text cleanup)*

### One-click launch

```bash
cp .env.example .env
```

**Windows** — double-click `start.vbs`.  
Opens Windows Terminal with two split panes (backend + frontend) and launches the browser automatically. Clears any stale processes on ports 8000 and 3000 before starting.

**Linux / macOS**:
```bash
chmod +x start.sh && ./start.sh
# Ctrl+C stops both services
```

### Manual launch

```bash
# Terminal 1 — Backend
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

---

## Configuration

Main config is in **`backend/config.py`** — defaults work out of the box for local dev.

Environment-specific overrides go in **`.env`** (copy from `.env.example`):

```env
# Paths
DATABASE_PATH=../data/db/yt_summarizer.sqlite
COOKIES_PATH=../data/www.youtube.com_cookies.txt

# Debug mode (enables SQLAlchemy query logging)
DEBUG=false

# Ollama — local LLM for AI text cleanup (optional)
OLLAMA_URL=http://localhost:11434
```

Model selection and prompt configuration are managed in `backend/config.py` and (upcoming) via the Settings page in the UI.

---

## Ollama setup (AI text cleanup)

Text cleanup runs locally via [Ollama](https://ollama.com) — no API keys, no data leaves the machine.

**1. Install Ollama**  
Download and run the installer from [ollama.com](https://ollama.com/download).

**2. Pull a model of your choice**
```bash
ollama pull <model-name>
```

Browse available models at [ollama.com/library](https://ollama.com/library). Any instruction-following model works; multilingual models perform better on non-English transcripts. Set the model name in `backend/config.py`.

**3. Set the Ollama URL in `.env`** if Ollama runs on a non-default host:
```env
OLLAMA_URL=http://localhost:11434
```

**If Ollama is not running** — the pipeline completes normally. The "Cleaned" tab shows as greyed-out. The nav bar shows a red `● Ollama` indicator.

---

## Cookies setup

YouTube blocks yt-dlp without valid cookies.

1. Install **"Get cookies.txt LOCALLY"** extension in Chrome
2. Open [youtube.com](https://www.youtube.com) and log in
3. Click the extension → Export cookies → Save as `data/www.youtube.com_cookies.txt`

Re-export if you start getting 429 or "sign in required" errors.
