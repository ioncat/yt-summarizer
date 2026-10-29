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

### Epic 7: Settings Page — Prompts & Models Per Stage
**Description**: Web UI for editing system/user prompts and selecting models separately for cleanup and summarization stages

**Status**: ✅ Done | **Priority**: 🟠 P1  
[View Epic →](./epics/EPIC-7.md)

---

### Epic 8: Markdown Rendering (frontend only)
**Description**: Add react-markdown renderer to the Result page. Prompt part configured via Settings page (Epic 7).

**Status**: ❌ Dropped | **Priority**: 🟠 P1  
**Note**: Tested — LLM output quality inconsistent. Plain text rendering retained.

---

### Epic 9: Per-Tab Character Count
**Description**: Show separate character counts for Subtitles tab and Cleaned tab

**Status**: ✅ Done | **Priority**: 🟡 P2  
[View Epic →](./epics/EPIC-9.md)

---

### Epic 10: Auto-Pipeline Toggle
**Description**: Checkbox on Home page to automatically run all three stages (Extract → Cleanup → Summarize) in sequence. Pre-flight validation checks all stages are configured before starting.

**Status**: ✅ Done | **Priority**: 🟡 P2  
[View Epic →](./epics/EPIC-10.md)

---

### Epic 11: Model Selection in UI
**Description**: Covered by Epic 7 (Settings page). Inline model selector added to Result page for quick experimentation — auto-saves on change, no Save button needed.

**Status**: ✅ Done (partial — inline selector on Result page) | **Priority**: 🟡 P2  
[View Epic →](./epics/EPIC-11.md)

---

### Epic 12: Cancel Cleanup
**Description**: Stop button in UI to interrupt a running AI cleanup. In-memory cancel flag checked before each paragraph in Ollama loop. Status resets to null on cancel. Backend: `DELETE /api/result/{video_id}/cleanup`. Frontend: "✕ Stop" button while cleanup_status === 'processing'.

**Status**: ✅ Done | **Priority**: 🔴 P0

---

### Epic 13: Settings 2.0 — All Config via Web UI
**Description**: Move all user-facing settings out of config files into the DB, configurable exclusively via web. Includes: Ollama URL, cookies path, yt-dlp path. Settings page redesign with tabs (no scroll). Notification if model or prompt is missing before cleanup. Upload cookies via web. Single source of truth = DB.

**Status**: ✅ Done | **Priority**: 🟠 P1

---

### Epic 14: Cleanup Timer
**Description**: Show how long AI cleanup took. After completion — "Cleaned in X:XX" displayed in the result meta. DB-based: `cleanup_started_at` and `cleanup_finished_at` columns on `subtitles_formatted`. Written via raw SQL in `video_service.py`. Duration computed server-side in `get_result()`.

**Status**: ✅ Done | **Priority**: 🟡 P2

---

### Epic 15: LLM Summarization (Single-pass)
**Description**: Summary tab on Result page. Sends cleaned_text (or formatted_text) to Ollama in a single request. Cancel button, model selector per-tab, "Summarized in X:XX · model" in meta. Settings → Summarization unlocked.

**Status**: ✅ Done | **Priority**: 🟠 P1

---

### Epic 16: Cancel for Auto-Pipeline
**Description**: "✕ Stop pipeline" button on ProcessingPage when auto-pipeline is running (stage ② Cleaning or ③ Summarizing). Should cancel the active background job and navigate to result page with whatever is available.
- Cleanup cancel: `DELETE /api/result/{video_id}/cleanup` (already exists)
- Summary cancel: `DELETE /api/result/{video_id}/summary` (already exists)
- ProcessingPage needs to track which stage is active and call the right cancel endpoint on Stop

**Status**: ✅ Done | **Priority**: 🟡 P2

---

## Phase 2: LLM Summarization Quality 🔄

Improve summarization quality beyond single-pass. Map-reduce or chunked approach for long texts. See `docs/phase2-architecture.md`.

| Epic | Description | Status |
|------|-------------|--------|
| Epic 17: Map-Reduce Summarization | Auto-select single-pass vs map-reduce by text length; MAP (extract per chunk) + REDUCE (combine); live chunk counter in UI; force_map_reduce toggle for testing; Settings step tabs (Step 1 Extract / Step 2 Combine); always-visible method label in Result meta | ✅ Done |
| Epic 18: Hierarchical Map-Reduce | 3-level pipeline for texts > 50K chars: MAP → intermediate REDUCE per batch → final REDUCE. Fixes REDUCE overload on large inputs | 🔵 Planned |
| Epic 19: Prompt Management v2 | Language-aware prompts, per-stage templates | 🔵 Planned |
| Epic 20: Summary Quality Metrics | Show compression ratio, char count diff input/output | ✅ Done — "86% compressed" shown in Summary meta |
| Epic 21: Multi-Version Summaries | Store one summary per (video, model); view and switch between saved versions for model comparison | ⏸ Deferred — duplicates Benchmark (Epic 26) functionality. Re-evaluate if frequent model-switching on long Full Extract jobs becomes a real need. |
| Epic 22: Auto Language Detection | Detect original video language from yt-dlp metadata; "Auto (detect)" as default in Home page dropdown; manual override kept during testing | ✅ Done |
| Epic 23: Chapter-Aware Formatting | Use creator-defined YouTube chapters as semantic boundaries for subtitle grouping; `## Chapter Title` headings in formatted_text; fallback to 4s gap when no chapters | ✅ Done |
| Epic 24: Completion Notifications | Tab title changes to "✓ Done" when cleanup/summary finishes; Browser Notification when tab is hidden; permission requested lazily on first run | ✅ Done |
| Epic 25: Chapter Heading Preservation & Rendering | `## Chapter Title` headings pass through cleanup and summarization unchanged; rendered as visual subheadings in UI across all tabs. Post-fix (21.05): `normalize_chapter_headings()` in `text_utils.py` fixes inline `## ` markers without `\n\n`; applied server-side (all summarizer outputs) + client-side in `renderText.tsx` for legacy DB rows | ✅ Done |
| [Epic 26: Benchmark](./epics/EPIC-26.md) | Side-by-side N-model comparison; same mode logic as production pipeline; DB table `benchmark_runs`; `/benchmark` page + `/benchmarks` index; N-column layout; synchronized scroll; HTML export; stage selector (summary/cleanup); "📌 Original" badge for main-triggered runs; delete-run button | ✅ Done |
| [Epic 27: Full Extract (No-Reduce)](./epics/EPIC-27.md) | Lossless processing mode for long structured content: MAP per chapter (no REDUCE); auto-selected for chapter videos ≥ 24K chars; chapter progress in UI | ✅ Done |
| Epic 28: Processing Mode Management | Mode picker UI (auto-detect + manual override); unified mode selection across single-pass / map-reduce / full-extract / hierarchical | 🔵 Planned |
| [Epic 29: Parallel MAP Processing](./epics/EPIC-29.md) | Parallel paragraph/chunk/section processing via asyncio.gather() + Semaphore; preserves order via index; configurable workers matching OLLAMA_NUM_PARALLEL | ✅ Done |
| [Epic 33: Benchmark Metrics Enhancement](./epics/EPIC-33.md) | Capture real token counts and tok/s from Ollama done-message; add `prompt_tokens`, `completion_tokens`, `tokens_per_second`, `chunks_count` to BenchmarkRun; compute `compression_ratio` from existing chars; display all metrics per model column in BenchmarkPage | 🔵 Planned |
| [Epic 34: Bulk URL Queue](./epics/EPIC-34.md) | Bulk URL input on HomePage (textarea, one per line); `processing_queue` DB table; asyncio queue worker (sequential, one video at a time); configurable pipeline stages per batch (extract / +cleanup / full); Queue status page `/queue` with per-item status | ✅ Done |
| [Epic 35: Playlist Import](./epics/EPIC-35.md) | Paste YouTube playlist URL → yt-dlp flat-playlist extract → preview list with checkboxes → add selected to queue (Epic 34); auto-detect playlist URL in Bulk Add panel; 200-video limit | 🔵 Planned — depends on Epic 34 |
| [Epic 37: Suggested Questions](./epics/EPIC-37.md) | After summary is ready, LLM generates 3–5 short content-specific questions shown as clickable chips near the chat bar. Click → sends as chat message. Lazy trigger (on first Summary tab open). `suggested_questions` JSON column in DB. Lowers cold-start barrier to chat. | 🔵 Planned — depends on Epic 15 |
| [Epic 38: pytest API Tests](./epics/EPIC-38.md) | Full pytest suite for all API endpoints. In-process via `httpx.AsyncClient + ASGITransport`, in-memory SQLite DB, mocked yt-dlp (subprocess) + Ollama (respx). 8 test files: health, settings, process/status, result, cleanup, summary, queue, history. ~4–5h. | 🔵 Planned |
| [Epic 39: Chat Model Selector](./epics/EPIC-39.md) | Dedicated model selector for chat — separate from summary model. Inline dropdown in floating chat bar. Persisted in `pipeline_settings` under stage `chat`. Falls back to summary model if not set. | ✅ Done |
| Epic 40: Retry Failed Queue Item | Re-queue a failed item directly from the Queue page without going back to the Home page. "Retry" button per failed row; re-inserts original URL + pipeline stages + language into the queue. | 🔵 Planned — depends on Epic 34 |

---

## UX Polish & Bug Fixes (non-epic)

Small improvements and fixes that don't warrant a standalone epic.

| Date | Description |
|------|-------------|
| 19.05.2026 | Re-extract subtitles: `POST /api/result/{video_id}/reextract` — re-run extraction for an existing video without deleting its history |
| 19.05.2026 | VTT parser fix: decode HTML entities (`&#39;` → `'`) + collapse whitespace |
| 21.05.2026 | Chat typing animation: 3-dot bounce + spinner on the send button (yt-summarizer + llm-onpage-summarizer) |
| 21.05.2026 | History page: stage checkmarks ✓ (grey = not run, green = done) for Cleanup and Summary; type badges unified to a neutral style |
| 21.05.2026 | Result meta: always shows mode (Single Pass / Map-Reduce / Full Extract) next to model name |
| 21.05.2026 | Settings → Summarization → Map-Reduce: Step 1 / Step 2 split into horizontal tabs (scroll removed) |
| 21.05.2026 | Result meta redesign: two rows (video-info / stage-info), `•` separators, hover tooltips; classes `.meta-row`, `.meta-chip`, `.meta-sep`, `.meta-label` |
| 21.05.2026 | Result meta: `cleanup_finished_at` and `summary_finished_at` from API — finish timestamp shown at the end of each stage row |
| 21.05.2026 | Date format: `DD.MM.YYYY, HH:MM` (locale-independent) instead of `toLocaleString` |
| 04.06.2026 | **Favicon** — SVG red circle with white "YTS" (`public/favicon.svg`), wired up in `index.html` |
| 04.06.2026 | **Queue progress display** — `on_progress` callbacks connected in worker for cleanup/summary/mindmap; progress text ("paragraph 3/12", "chunk 5/20") in the banner and QueuePage table row with active-stage highlighting |
| 04.06.2026 | **Queue as sole LLM path** — HomePage autoPipeline → queue; ResultPage buttons (Clean with AI / Summarize / Mind Map / pipeline guard) → queue; `_run_mindmap_stage` in worker |
| 04.06.2026 | **Queue UX**: constant 3s polling; sort order processing→pending→failed→done, newest first within each group; QueueBadge polling 4s (was 8s) |
| 04.06.2026 | **History search** — search field by title+author, server-side `ILIKE` filtering, 350ms debounce |
| 04.06.2026 | **Favorites** — `is_favorite BOOLEAN` in `videos` (migration); `POST /api/result/{id}/favorite` toggle; `?favorites_only=true` on `/history`; ★/☆ button in ResultPage + HistoryPage rows + "☆ Favorites" filter |
| 23.05.2026 | **Known issue: chapter titles language mismatch** — ~~yt-dlp extracts `info["chapters"]` in the language of the user's YouTube interface (via cookies). Workaround: switch YouTube interface to the video's language before extracting.~~ **Resolved 23.05.2026**: YouTube API translates `info["chapters"]` to English server-side regardless of cookies, headers, or client-type (confirmed by diagnostics). Fix: `_parse_description_chapters()` — takes timecodes from `info["description"]` (never auto-translated by YouTube, always in the author's language). Fallback to `info["chapters"]` with `[CHAPTER_SOURCE]` warning in log. Script check: heading script vs subtitle language — warning on mismatch. |
| 20.06.2026 | **Queue `force=true` bug fix** — ResultPage `queueBulkAdd` calls used `force=false` (default) → existing videos silently skipped as duplicates, nothing queued. All 4 calls (`handleCleanup`, `handleSummarize` ×2, `handleMindmap`) now pass `force=true`. |
| 20.06.2026 | **Chat bar redesign** — floating centered bar: `fixed bottom-6 left-0 md:left-64 right-0` + inner `max-w-[1200px] mx-auto flex justify-center max-w-2xl`. Aligns with content card in both normal and Boxed Layout modes. `rounded-2xl shadow-2xl backdrop-blur-md`. |
| 20.06.2026 | **Mind Map tab** — `'mindmap'` added to `Tab` type; full tab in ResultPage (`subtitles \| cleaned \| summary \| mind map \| chat`); `Generate mind map` / `Regenerate mind map` button in actions bar (`account_tree` icon); empty state with large icon; `mindmapEnabled` toggle removed. |
| 20.06.2026 | **MD toggle relocated** — removed from shared tab toolbar; now lives as small pill inside content area of Summary and Cleaned tabs only. Chat assistant messages always use ReactMarkdown (no toggle). |

| Epic 36: Frontend Redesign | Tailwind CSS v4.3.1 + Material Design 3 tokens + Material Symbols Outlined icons. All 8 pages rebuilt from Stitch design files. Boxed Layout feature (floating centered container, toggle in Settings → General → Display). Dark/light mode via `.dark` class. | ✅ Done — 20.06.2026 |

---

## Phase 3: Speech-to-Text ✅

Whisper-based transcription for YouTube audio and local files. Language param from Phase 1 reused directly.

| Epic | Description | Status |
|------|-------------|--------|
| Epic 30: STT Service Layer | `services/transcriber.py` engine-agnostic API, faster-whisper, device auto-detect, model catalog + download/delete UI in Settings → STT | ✅ Done — 24.10.2026 |
| Epic 31: YouTube/URL Audio Transcription | `extract_audio()` via yt-dlp, queue worker `_run_transcribe()`, `subtitle_source='transcript'` in DB, STT checkbox on HomePage | ✅ Done — 24.10.2026 |
| Epic 32: Local File Upload | `POST /api/process/file` multipart endpoint, `data/uploads/` storage, `local_video_id="file-{uuid8}"`, drag-and-drop on HomePage Local File tab | ✅ Done — 24.10.2026 |
| Epic 41: STT Configuration & File Management | yt-dlp bundled mode toggle + version/update UI; File Storage tab (stats, clear, auto-delete policy); CUDA detection fix (`ctranslate2`); graceful CUDA→CPU fallback; `av<19` pin | ✅ Done — 25.10.2026 |
| Epic 42: STT Progress, Timing & Source Badges | Live segment progress on ProcessingPage; transcription timing columns + "Transcribed in X:XX" in ResultPage meta; STT source badge (movie/audio icon) in History | ✅ Done — 25.10.2026 |
| Epic 43: Local File Result Page | Inline Whisper model selector; Re-transcribe button with live segment progress; hide irrelevant Open video / Benchmark buttons for local files; backend re-transcribe path via `_run_reextract` | ✅ Done — 25.10.2026 |

---

## Phase 4: Integrations 🔵

Превратить YT Summarizer из браузерного инструмента в сервис, которым пользуются AI-агенты и внешние клиенты.

### Epic 44: MCP Server
**Description**: Stdio MCP Server для Claude Desktop и AI-агентов. Инструменты: `process_video`, `get_result`, `search_history`, `run_cleanup`, `run_summary`. HTTP-прокси к FastAPI — без дублирования логики. Установка за 5 минут через `claude_desktop_config.json`.

**Status**: ✅ Done — 28.10.2026 | **Priority**: 🟡 P2  
**Files**: `app/mcp_server.py`, `docs/guides/MCP_SETUP.md`  
[View Epic →](./epics/EPIC-44.md)

---

### Epic 45: Claude Desktop Connection UI

**Description**: Кнопка "Connect Claude Desktop" в Settings → Connections. Приложение само находит `claude_desktop_config.json`, добавляет запись `yt-summarizer`, делает бэкап старого файла. Пользователь не редактирует JSON вручную. Показывает статус подключения (Connected / Not connected). Обязательно для продуктового/SaaS сценария — пользователи не должны знать про конфиги.

**Status**: ✅ Done (29.10.2026) | **Priority**: 🟡 P2  
**Estimate**: ~2–3 часа  
**Depends on**: Epic 44 (MCP Server) ✅  
[View Epic →](./epics/EPIC-45.md)

---

### Epic 46: Video Download

**Description**: Скачать видео или аудио с YouTube (и других 1000+ сайтов через yt-dlp) прямо из интерфейса. Кнопка на Result page рядом с "Open video". Форматы: MP4 (видео), MP3/AAC (аудио). Файл отдаётся через браузер как скачивание. Полезно когда нужно видео офлайн или для обработки — особенно в связке с STT pipeline.

**Status**: 🔵 Planned | **Priority**: 🟢 P3  
**Estimate**: ~3–4 часа  
**Note**: yt-dlp уже интегрирован в проект, audio extraction уже работает для STT. Video download — логичное расширение.

---

## Ideas & Deferred Improvements

Small ideas and technical improvements that don't warrant an epic. Can be implemented as needed.

| Idea | Description | Complexity |
|------|-------------|------------|
| **[Testing] pytest API** | Promoted to **[Epic 38](./epics/EPIC-38.md)**. | — |
| **[Testing] Playwright E2E** | Critical-path automation: (1) submit URL → queue → view result, (2) History page load + search + favorite, (3) Queue page with active item. Covers both frontend and backend integration in one shot. Most valuable during redesign phase — catches regressions per page. Run against dev server (`localhost:3001` + `localhost:8000`). Baseline: `npx playwright test`. | ~3–4h setup + ~1h per critical path |
| **[Testing] Visual regression (Playwright screenshots)** | After each redesign page is done — capture baseline screenshots with `toHaveScreenshot()`. Future changes auto-compare vs baseline. Especially useful after redesign branch merges to catch unintended CSS drift. Store baselines in `tests/screenshots/`. | ~1h after Playwright is wired up |
| **[Testing] pytest API tests** | FastAPI endpoint contract tests: submit URL, get result, settings CRUD, queue endpoints. Validates JSON shape, status codes, error responses. Runs without browser — fast CI step. Use `httpx.AsyncClient` with `ASGITransport`. Requires test DB (separate SQLite file). | ~3h |
| **[Testing] Vitest + React Testing Library** | Component unit tests: `TypeBadge`, `renderText()`, theme toggle, pipeline preset logic. Lowest priority — most logic lives in API calls and state. Worth adding only for pure util functions (`videoType.ts`, `renderText.tsx`). | ~1–2h, low ROI vs E2E |
| Mindmap from summary (Markmap) | Visual mindmap from `summary_text`. **Option A (experiment, ~1–2h)**: pipe existing `summary_text` with `## ` headings through `markmap-lib` + `markmap-view` — zero extra LLM call, test visual value. **Option B (~4–5h)**: dedicated LLM prompt for semantic hierarchy (`#` topic, `##` branches, `###` details), store in `mindmap_text` in DB, button on Result page. Start with A. | A: ~2h / B: ~5h |
| Suggested Questions | Promoted to **[Epic 37](./epics/EPIC-37.md)**. | — |
| Output format templates (Prompt Templates) | A set of ready-made output templates next to the Summarize button: "How-to", "Action Plan", "Author's position", "Key facts", "Pros & Cons". User picks a format — system substitutes the corresponding system prompt. Each template is a separate `pipeline_settings` entry in DB (or hardcoded with customization support). Key differentiator from competitors. | ~3–4h |
| Chat: server-side save | Move chat history saving to the backend — buffer the response in `chat_proxy`, save to DB after stream finishes regardless of client state. Requires adding `video_id` to `ChatRequest`. Current implementation loses the response if user navigates away before generation completes. | ~30 min |
| **[Hypothesis] LLM context window overflow protection** | When running the full pipeline (Extract → Cleanup → Summary) Ollama or the model may hang/crash due to context window overflow on large texts. Current mitigations: map-reduce (24K threshold), 3K chunks, 180s timeout. **Explored solutions**: (1) explicitly pass `"num_ctx": N` in every Ollama request — hard window cap, predictable truncation; (2) `GET {ollama_url}/api/ps` — check loaded model before queue start (detect OOM/unload); (3) retry with smaller chunk on 500/timeout. **Requires**: load testing on large videos (>50K chars) with different models. Do not start without tests. | ~4–6h + tests |
| README: update concept and positioning | Current README frames the tool as "watch or skip" — a quick filter for video content. As support for large texts grows (long lectures, documentaries, courses), positioning should shift: the app becomes a deep knowledge extraction tool, not just a content filter. Update Introduction, Vision, "Watch or Skip" section → broader framing. **Trigger**: Epic 18 (XL texts) or Phase 3 (STT). | ~1h |

---

## Summary Statistics

| Phase | Epics | Status |
|-------|-------|--------|
| Phase 1 — MVP | 1–5 | ✅ Done |
| Phase 1.5 — LLM Cleanup & UX | 6–16, 22–25 | ✅ Done (8 dropped) |
| Phase 2 — Summarization Quality | 17–21, 26–29, 33–34, 36–40 | 🔄 In Progress (17, 20, 22–27, 29, 34, 36, 39, 40 done; 21 deferred; 18, 19, 28, 33, 35, 37, 38 planned) |
| Phase 3 — Speech-to-Text | 30–32, 41–43 | ✅ Done |
| Phase 4 — Integrations | 44–46 | 🔄 In Progress (44–45 done; 46 planned) |

---

## Document Control

- **Version**: 1.9
- **Last Updated**: 29.10.2026
- **Status**: 🔄 Active Development
