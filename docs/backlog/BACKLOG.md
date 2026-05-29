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

---

## UX Polish & Bug Fixes (не эпики)

Небольшие улучшения и фиксы, не тянущие на отдельный эпик.

| Дата | Описание |
|------|----------|
| 19.05.2026 | Re-extract subtitles: `POST /api/result/{video_id}/reextract` — повторное извлечение субтитров для существующего видео без удаления истории |
| 19.05.2026 | VTT parser fix: decode HTML entities (`&#39;` → `'`) + collapse whitespace |
| 21.05.2026 | Chat typing animation: 3-dot bounce + spinner на кнопке отправки (yt-summarizer + llm-onpage-summarizer) |
| 21.05.2026 | History page: stage checkmarks ✓ (grey = not run, green = done) для Cleanup и Summary; type badges унифицированы в нейтральный стиль |
| 21.05.2026 | Result meta: всегда отображает метод (Single Pass / Map-Reduce / Full Extract) рядом с моделью |
| 21.05.2026 | Settings → Summarization → Map-Reduce: Step 1 / Step 2 разделены на горизонтальные вкладки (убран скролл) |
| 21.05.2026 | Result meta redesign: два ряда (видео-инфо / stage-инфо), разделители `•`, hover tooltips; классы `.meta-row`, `.meta-chip`, `.meta-sep`, `.meta-label` |
| 21.05.2026 | Result meta: `cleanup_finished_at` и `summary_finished_at` из API — timestamp последнего запуска этапа отображается в конце stage row |
| 21.05.2026 | Date format: `DD.MM.YYYY, HH:MM` (locale-independent) вместо локализованного toLocaleString |
| 23.05.2026 | **Known issue: chapter titles language mismatch** — ~~yt-dlp извлекает `info["chapters"]` на языке YouTube-интерфейса пользователя (через cookies). Workaround: переключить YouTube-интерфейс на язык видео перед извлечением.~~ **Resolved 23.05.2026**: YouTube API переводит `info["chapters"]` на английский на стороне сервера независимо от кук, заголовков и client-type (подтверждено диагностикой). Фикс: `_parse_description_chapters()` — берём таймкоды из `info["description"]` (не переводится YouTube, всегда на языке автора). Fallback на `info["chapters"]` с `[CHAPTER_SOURCE]` warning в лог. Проверка скрипта заголовков vs языка субтитров — warning при расхождении. |

---

## Phase 3: Speech-to-Text Fallback 🔵

Whisper fallback when no subtitles are available. Language param from Phase 1 reused directly.

| Epic | Description | Status |
|------|-------------|--------|
| Epic 30: Audio Extraction | Extract audio via yt-dlp | 🔵 Planned |
| Epic 31: Whisper Transcription | Local Whisper model | 🔵 Planned |
| Epic 32: Fallback UX | One-click fallback offer when subtitles missing | 🔵 Planned |

---

## Ideas & Deferred Improvements

Мелкие идеи и технические улучшения, не тянущие на эпик. Могут быть реализованы по мере необходимости.

| Идея | Описание | Сложность |
|------|----------|-----------|
| Mindmap из summary (Markmap) | Визуальный mindmap из `summary_text`. **Вариант A (эксперимент, ~1-2ч)**: прогнать существующий `summary_text` с `## ` заголовками через `markmap-lib` + `markmap-view` — нулевой доп. LLM-вызов, проверить визуальную ценность. **Вариант B (~4-5ч)**: отдельный LLM-промпт для иерархии смыслов (`#` тема, `##` ветки, `###` детали), хранить в `mindmap_text` в DB, кнопка на Result page. Начать с A. **Мотивация**: `docs/saas-transition.md` → раздел 7.2 (конкурентная отстройка). | A: ~2ч / B: ~5ч |
| Suggested Questions (авто-вопросы к видео) | После summary LLM генерирует 5 вопросов, раскрывающих смысл видео (с учётом заголовка). Показываются как кликабельные chips в chat-зоне. Клик → отправляет как chat message. Снижает барьер входа в чат — пользователю не нужно придумывать вопрос. Ключевой инсайт: заголовок видео — это то, зачем пришёл пользователь, вопросы должны отвечать именно на это. 1 доп. LLM-вызов + `suggested_questions` JSON-колонка в DB. **Мотивация**: `docs/saas-transition.md` → раздел 7.3.1. | ~2–3 ч |
| Output format templates (Prompt Templates) | Набор готовых шаблонов вывода рядом с кнопкой Summarize: "Инструкция", "Action Plan", "Позиция автора", "Ключевые факты", "Pros & Cons". Пользователь выбирает формат — система подставляет соответствующий системный промпт. Каждый шаблон — отдельная `pipeline_settings`-запись в БД (или хардкод с возможностью кастомизации). **Мотивация**: см. `docs/saas-transition.md` → раздел 6 (use cases) и раздел 7 (конкурентные преимущества). Это ключевой вектор дифференциации от конкурентов. | ~3–4 ч |
| Chat: server-side save | Перенести сохранение истории чата на бэкенд — буферизовать ответ в `chat_proxy`, сохранять в DB после завершения стрима независимо от клиента. Нужно добавить `video_id` в `ChatRequest`. Текущая реализация теряет ответ если пользователь уходит со страницы до завершения генерации. | ~30 мин |
| README: обновить концепцию и позиционирование | Текущий README описывает инструмент как "watch or skip" — быстрое решение смотреть или нет. По мере реализации работы с большими текстами (длинные лекции, документальные видео, курсы) позиционирование должно сместиться: приложение становится инструментом глубокого извлечения знаний, а не просто фильтром контента. Обновить Introduction, Vision, раздел "Watch or Skip" → более широкую формулировку. **Триггер**: реализация Epic 18 (XL-тексты) или Phase 3 (STT). | ~1 ч |

---

## Summary Statistics

| Phase | Epics | Status |
|-------|-------|--------|
| Phase 1 — MVP | 1–5 | ✅ Done |
| Phase 1.5 — LLM Cleanup & UX | 6–16, 22–25 | ✅ Done (8 dropped) |
| Phase 2 — Summarization Quality | 17–21, 26–29 | 🔄 In Progress (17, 20, 22–27, 29 done; 21 deferred; 18, 19, 28 planned) |
| Phase 3 — STT Fallback | 30–32 | 🔵 Planned |

---

## Document Control

- **Version**: 1.6
- **Last Updated**: 23.05.2026
- **Status**: 🔄 Active Development
