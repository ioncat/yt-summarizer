# YT Summarizer - Product Backlog

Navigation and overview of all epics and user stories for YT Summarizer, organized by development phase.

---

## Phase 1: MVP - Subtitle Extraction & Formatting ✅

### Epic 1: Core Subtitle Extraction
**Status**: ✅ Done | **Priority**: 🔴 P0  
[View Epic →](./epics/EPIC-1.md)

### Epic 2: Text Formatting & Presentation
**Status**: ✅ Done | **Priority**: 🔴 P0  
[View Epic →](./epics/EPIC-2.md)

### Epic 3: Data Persistence
**Status**: ✅ Done | **Priority**: 🔴 P0  
[View Epic →](./epics/EPIC-3.md)

### Epic 4: Error Handling & Edge Cases
**Status**: ✅ Done | **Priority**: 🟠 P1  
[View Epic →](./epics/EPIC-4.md)

### Epic 5: Web User Interface
**Status**: ✅ Done | **Priority**: 🔴 P0  
[View Epic →](./epics/EPIC-5.md)

---

## Phase 1.5: LLM Text Cleanup & UX Polish 🔄

Local LLM cleanup via Ollama. Runs on demand. No data leaves the machine.

### Epic 6: LLM Text Cleanup (Ollama)
**Description**: Manual AI cleanup trigger, spinner, polling, health check, Cleaned tab

**Status**: ✅ Done | **Priority**: 🟠 P1  
[View Epic →](./epics/EPIC-6.md)

---

### Epic 7: Markdown Output & Rendering
**Description**: Instruct LLM to output proper Markdown; render it in the UI with react-markdown

**Status**: 🟡 Next | **Priority**: 🟠 P1  
[View Epic →](./epics/EPIC-7.md)

---

### Epic 8: Per-Tab Character Count
**Description**: Show separate character counts for Subtitles tab and Cleaned tab

**Status**: 🟡 Next | **Priority**: 🟡 P2  
[View Epic →](./epics/EPIC-8.md)

---

### Epic 9: Auto-Pipeline Toggle
**Description**: Checkbox on Home page to automatically run cleanup after extraction (Summary skipped — not ready)

**Status**: 🔵 Planned | **Priority**: 🟡 P2  
[View Epic →](./epics/EPIC-9.md)

---

### Epic 10: Settings Page — Prompts & Models Per Stage
**Description**: Web UI for editing system/user prompts and selecting models separately for cleanup and summarization stages

**Status**: 🔵 Planned | **Priority**: 🟡 P2  
[View Epic →](./epics/EPIC-10.md)

---

### Epic 11: Model Selection in UI
**Description**: Select Ollama model per pipeline stage from the web interface; model list fetched live from Ollama

**Status**: 🔵 Planned | **Priority**: 🟡 P2  
**Note**: Superseded by Epic 10 (Settings page covers model selection per stage). Keep as standalone if Settings page is deferred.  
[View Epic →](./epics/EPIC-11.md)

---

## Phase 2: LLM Summarization 🔵

Map-reduce summarization: paragraph summaries → document summary. See `docs/phase2-architecture.md`.

| Epic | Description | Status |
|------|-------------|--------|
| Epic 12: LLM Summarization Pipeline | Map-reduce: paragraph → paragraph_summary → document_summary | 🔵 Planned |
| Epic 13: Prompt Management | Prompts per stage, language-aware (covered partly by Epic 10) | 🔵 Planned |
| Epic 14: Summary Display | Summary tab in UI alongside Subtitles and Cleaned | 🔵 Planned |

---

## Phase 3: Speech-to-Text Fallback 🔵

Whisper fallback when no subtitles are available. Language param from Phase 1 reused directly.

| Epic | Description | Status |
|------|-------------|--------|
| Epic 15: Audio Extraction | Extract audio via yt-dlp | 🔵 Planned |
| Epic 16: Whisper Transcription | Local Whisper model | 🔵 Planned |
| Epic 17: Fallback UX | One-click fallback offer when subtitles missing | 🔵 Planned |

---

## Summary Statistics

| Phase | Epics | Status |
|-------|-------|--------|
| Phase 1 — MVP | 1–5 | ✅ Done |
| Phase 1.5 — LLM Cleanup & UX | 6–11 | 🔄 In Progress (Epic 6 done) |
| Phase 2 — Summarization | 12–14 | 🔵 Planned |
| Phase 3 — STT Fallback | 15–17 | 🔵 Planned |

---

## Document Control

- **Version**: 1.3
- **Last Updated**: 2026-04-25
- **Status**: 🔄 Active Development
