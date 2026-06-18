# YT Summarizer

AI tool for YouTube: extract, clean, summarize video content — and chat with the content.

## Watch or Skip

Video is expensive to evaluate:

- A 10-minute video can take 10 minutes just to judge.
- Titles and thumbnails rarely show the real substance.
- Intros, delivery, pacing, filler, and repetition add cognitive load.

YT Summarizer gives you a short AI summary of any YouTube video, so you can:

- understand the core idea quickly;
- decide whether the full video deserves your attention;
- skip low-value content without spending time on it.

The goal: turn a watch-or-skip guess into a fast, informed decision.

→ **[Quick Start Guide](docs/quick-start-guide.md)** — minimal setup to try it out  
→ **[User Guide](docs/USER_GUIDE.md)** — features, settings, troubleshooting, FAQ  
→ **[System Behavior](docs/system-behavior.md)** — pipeline activity diagram + state diagrams (Mermaid)

---

If you care about reducing cognitive load and saving time in the age of information overload, you might also find this useful:  
**[llm-onpage-summarizer](https://github.com/ioncat/llm-onpage-summarizer)** — summarize any web page with a local LLM, right in your browser.

---

## Pipeline

```
YouTube URL → Extract → Format → AI Cleanup → Summarize → Chat Q&A
                  ↓         ↓          ↓            ↓
              metadata    paragraphs  cleaned    summary
              + VTT       + chapters  text       (Single / Map-Reduce / Full Extract)
```

Each stage's output is stored separately in SQLite and shown as its own tab: **Subtitles · Cleaned · Summary**.

**Key features:**
- **Local LLM via Ollama** — no data leaves your machine
- **Auto language detection** — picks original video language from yt-dlp metadata
- **Chapter-aware formatting** — preserves YouTube creator's chapter structure
- **Multiple processing modes** — Single-pass / Map-Reduce / Full Extract, auto-selected
- **Benchmark page** — compare 2–4 models side by side
- **Chat Q&A** — ask follow-up questions with full context
- **Completion notifications** — tab title + browser notification

See the [User Guide](docs/USER_GUIDE.md) for details on each feature.

---

## Tech Stack

| Component | Technology |
|---|---|
| Frontend | React + TypeScript + Vite |
| Backend | Python + FastAPI |
| LLM | Ollama (local) |
| Subtitle extraction | yt-dlp |
| Database | SQLite (async via aiosqlite) |

```
yt-summarizer/
├── app/
│   ├── backend/             # FastAPI + Python
│   ├── frontend/            # React + TypeScript + Vite
│   └── data/                # SQLite DB + cookies (gitignored)
├── docs/
│   ├── USER_GUIDE.md        # Full user guide
│   ├── quick-start-guide.md # Minimal setup
│   ├── backlog/             # Epics and user stories
│   └── ...
├── CLAUDE.md                # Internal/development docs
├── docker-compose.yml
└── README.md
```

---

## Quick install

```bash
# Backend
cd app/backend && pip install -r requirements.txt && uvicorn main:app --port 8001

# Frontend (in another terminal)
cd app/frontend && npm install && npm run dev
```

Then open <http://localhost:3001> and configure Ollama URL, yt-dlp path, and cookies in Settings → General.

For Docker: `docker compose up --build`.

Full setup walkthrough: [Quick Start](docs/quick-start-guide.md). Detailed feature reference: [User Guide](docs/USER_GUIDE.md).

---

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/process` | Submit URL + language |
| GET | `/api/status/{task_id}` | Poll processing status |
| GET | `/api/result/{video_id}` | Get all data for a video |
| POST | `/api/result/{video_id}/cleanup` | Trigger AI cleanup |
| POST | `/api/result/{video_id}/summary` | Trigger AI summarization |
| POST | `/api/benchmark/run` | Run N-model benchmark |
| GET | `/api/history` | Paginated history |
| GET | `/api/settings` | All settings |
| GET | `/api/models` | Available Ollama models |

Cancel endpoints: `DELETE /api/result/{video_id}/cleanup` and `/summary`. Full API reference in [CLAUDE.md](CLAUDE.md).

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 — Subtitle Extraction | ✅ Done | Extract, format, store, display |
| Phase 1.5 — LLM Cleanup & UX | ✅ Done | Cleanup, summarization, Settings, auto-pipeline, cancel, chapter-aware, notifications |
| Phase 2 — Summarization Quality | 🔄 In Progress | Map-Reduce, Full Extract, Benchmark, Parallel MAP |
| Phase 3 — Speech-to-Text | 🔵 Planned | Whisper fallback when no subtitles |

See [docs/backlog/BACKLOG.md](docs/backlog/BACKLOG.md) for detailed epic breakdown.
