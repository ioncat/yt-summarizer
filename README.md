# YT Summarizer

Turn YouTube videos into scannable text so you can decide what to watch, save, or skip.

## Watch or Skip

Video is expensive to evaluate:

- A 10-minute video can take 10 minutes just to judge.
- Titles and thumbnails rarely show the real substance.
- Intros, delivery, pacing, filler, and repetition add cognitive load.

YT Summarizer extracts subtitles, cleans them into readable text, and helps you:

- understand the core idea quickly;
- decide whether the full video deserves your attention;
- skip low-value content without spending time on it.

The goal: turn a watch-or-skip guess into a fast, informed decision.

→ **[Quick Start Guide](docs/quick-start-guide.md)**

---

If you care about reducing cognitive load and saving time in the age of information overload, you might also find this useful:  
**[llm-onpage-summarizer](https://github.com/ioncat/llm-onpage-summarizer)** — summarize any web page with a local LLM, right in your browser.

---

## Pipeline

Each processed layer is stored separately in SQLite and shown as a dedicated tab in the UI.

```mermaid
flowchart TD
    URL[/"YouTube URL + language"/] --> EXT

    subgraph step1 ["① Extract"]
        EXT["yt-dlp\nsingle call — metadata + VTT"]
        EXT --> PARSE["VTT parser\ndeduplicate rolling-window entries"]
    end

    subgraph step2 ["② Format"]
        PARSE --> FMT["Text formatter\nremove overlap · split by time gaps → paragraphs"]
        FMT --> DB1[("SQLite\nformatted_text")]
    end

    subgraph step3 ["③ AI Cleanup · Phase 1.5"]
        DB1 --> LLM["Ollama · configurable model\nper paragraph:\nfix punctuation · remove fillers · merge fragments"]
        LLM --> DB2[("SQLite\ncleaned_text")]
    end

    subgraph step4 ["④ Summarize · Phase 2 🔵"]
        DB2 --> MAP["MAP — LLM summarizes each paragraph"]
        MAP --> RED["REDUCE — LLM combines into document summary"]
        RED --> DB3[("SQLite\nsummary")]
    end

    subgraph ui ["Frontend tabs"]
        DB1 --> T1["Subtitles"]
        DB2 --> T2["Cleaned"]
        DB3 --> T3["Summary 🔵"]
    end

    EXT -. "no subtitles" .-> STT
    STT["Phase 3 — Whisper STT 🔵\nfallback when no subtitles"] --> FMT
```

**Language**: if the requested language has no subtitles, the UI shows available languages with one-click retry.

**AI cleanup**: runs locally via Ollama — no data leaves the machine. If Ollama is offline, "Cleaned" tab is greyed-out with a tooltip.

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
│       ├── text_formatter.py       # VTT → clean text
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
    ├── quick-start-guide.md    # Setup and launch instructions
    ├── requirements.md         # Functional requirements
    └── phase2-architecture.md  # LLM summarization design
```

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/process` | Submit URL + language |
| GET | `/api/status/{task_id}` | Poll processing status |
| GET | `/api/result/{video_id}` | Get subtitle text + metadata |
| POST | `/api/result/{video_id}/cleanup` | Trigger AI cleanup |
| GET | `/api/health` | Backend + Ollama status |
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
