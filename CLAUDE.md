# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**YT Summarizer** - Extract, format, and store YouTube video subtitles for quick content review.

**Vision**: Reduce cognitive load by allowing users to scan video content before deciding whether to watch in detail.

**Current Phase**: MVP - Subtitle Extraction & Formatting (Phase 1)

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Frontend | React + TypeScript |
| Backend | Python + FastAPI |
| Video Processing | yt-dlp (no API keys required) |
| Database | SQLite |
| Text Format | Markdown (stored in DB) |

---

## Project Structure

```
yt-summarizer/
├── PROJECT_PLAN.md          # Complete project plan, architecture, schema, API design
├── CLAUDE.md                # This file
├── README.md
├── docs/
│   └── requirements.md      # Functional requirements for all phases
├── frontend/                # React + TypeScript web UI
│   ├── src/
│   ├── package.json
│   └── ...
├── backend/                 # FastAPI backend (Python)
│   ├── main.py
│   ├── requirements.txt
│   └── ...
└── DATABASE.md              # Database schema and migrations (when created)
```

---

## Development Phases

### ✅ Phase 1: MVP - Subtitle Extraction & Formatting
**Current**: Requirements gathering and planning complete. Ready for implementation.

**Core Features**:
1. Submit YouTube URL via web form
2. Extract subtitles using yt-dlp (ru, en, uk)
3. Format into clean, readable markdown text (100% accurate, no alterations)
4. Store in SQLite database
5. Display results in web UI
6. Show processing history

**Success Criteria**:
- Subtitles extracted accurately
- Text formatted properly (capitals, punctuation, structure)
- Database storage working
- Web UI functional
- Error handling clear and helpful

### 🔮 Phase 2: LLM Integration & Self-Raising
Dependencies on Phase 1. Create summaries and key points using LLM.

### 🔮 Phase 3: Speech-to-Text Fallback
Dependencies on Phase 1+2. Architecture-ready in Phase 1.

---

## Key Requirements

### Functional
1. **100% Content Accuracy**: No alterations, additions, or omissions to original subtitles
2. **Proper Formatting**: Correct capitalization, punctuation, paragraph structure
3. **Multi-Language**: Russian, English, Ukrainian support
4. **Error Handling**: Clear messages for invalid URLs, missing subtitles
5. **No API Keys**: Use yt-dlp without YouTube API authentication

### Architecture
- **Modular Design**: Easy to add speech-to-text processing later
- **Async Processing**: Handle long-running subtitle extraction
- **Loose Coupling**: Frontend/backend independent

---

## API Endpoints (Backend)

See `PROJECT_PLAN.md` section 6 for complete API design.

Quick reference:
- `POST /api/process` - Submit video for processing
- `GET /api/status/{task_id}` - Check processing progress
- `GET /api/result/{video_id}` - Retrieve formatted text
- `GET /api/history` - Get processing history
- `DELETE /api/result/{video_id}` - Delete result

---

## Database Schema

See `PROJECT_PLAN.md` section 5 for complete schema.

Key tables:
- `videos` - Video metadata
- `subtitles_raw` - Original subtitles with timestamps
- `subtitles_formatted` - Formatted markdown text
- `processing_tasks` - Task status tracking

---

## Before Starting Development

1. ✅ Read `PROJECT_PLAN.md` for complete architecture
2. ✅ Review `docs/requirements.md` for functional requirements
3. ✅ Understand database schema and API design
4. 🔄 Set up frontend repo (React + TypeScript)
5. 🔄 Set up backend repo (Python + FastAPI + yt-dlp)
6. 🔄 Initialize SQLite database with schema
7. 🔄 Start with backend subtitle extraction service (core MVP)

---

## Important Notes for Development

1. **Test with real YouTube videos** throughout development
2. **Preserve 100% of original content** - this is non-negotiable
3. **Handle edge cases**: Videos with multiple languages, no subtitles, restricted videos
4. **Use async/await** for long-running operations
5. **Log all processing steps** for debugging
6. **Keep services loosely coupled** for extensibility

---

## Common Development Tasks

*(To be added as development begins)*

---

## References

- **Project Plan**: See `PROJECT_PLAN.md` for architecture, schema, API design, and development phases
- **Functional Requirements**: See `docs/requirements.md` for detailed requirements per feature
- **yt-dlp Documentation**: https://github.com/yt-dlp/yt-dlp
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **React Documentation**: https://react.dev/
