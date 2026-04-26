# Epic 15: LLM Summarization (Single-pass)

## Summary
A Summary tab on the Result page. Sends the cleaned text (or formatted text if no cleanup) to Ollama in a single request and displays the result. Model selector per-tab, cancel button, timer, and "Summarized in X:XX · model" in meta. Settings → Summarization tab unlocked.

## Business Value
Users who want a quick digest instead of reading the full cleaned transcript can get a short summary in one click without leaving the page.

## Scope

### Included
- Summary tab on Result page (alongside Subtitles and Cleaned)
- "✦ Summarize" button (becomes "↺ Re-run summary" after first run)
- "✕ Stop" cancel button while running
- Inline model selector for summarization (auto-saves on change)
- "Summarized in X:XX · model" shown in meta block when on Summary tab
- Live elapsed timer while running ("Summarizing: X:XX" in meta)
- DB persistence: `summary_text`, `summary_status`, `summary_model`, `summary_started_at`, `summary_finished_at`
- Settings → Summarization tab unlocked (was showing "Phase 2 — coming soon")
- Input: `cleaned_text` if available, else `formatted_text`
- Single Ollama request (not map-reduce) — 180s timeout, temperature 0.2

### Not Included
- Map-reduce / chunked summarization for very long texts (Epic 17)
- Streaming output
- Per-language prompt variants

---

## User Stories

### US-1501: Generate Summary from Result Page

**As a** user  
**I want to** click "Summarize" on the Result page  
**So that** I get a concise digest of the video without reading the full cleaned text

**Acceptance Criteria**:
- Summary tab available alongside Subtitles and Cleaned
- "✦ Summarize" triggers background job, shows spinner in tab label
- After completion → Summary tab becomes active, text is displayed
- "Summarized in X:XX · model" shown in meta when Summary tab is active
- On error → error message shown in-tab, "↺ Re-run summary" available

### US-1502: Cancel Running Summarization

**As a** user  
**I want to** stop a running summarization  
**So that** I can switch models or abort a slow request

**Acceptance Criteria**:
- "✕ Stop" button appears in actions bar while summary_status = processing
- Click cancels the job; status resets to null
- No partial text stored

### US-1503: Per-Stage Model Selector for Summary

**As a** user  
**I want to** choose which model to use for summarization  
**So that** I can experiment without going to Settings

**Acceptance Criteria**:
- Inline `<select>` in actions bar when on Summary tab
- Auto-saves on change (no Save button)
- Disabled with tooltip when Ollama offline

---

## Implementation Notes

- **Service**: `text_summarizer.py` — single `POST {ollama_url}/api/chat`, `stream: false`, 180s timeout
- **DB columns**: `summary_text`, `summary_status`, `summary_model`, `summary_started_at`, `summary_finished_at` on `subtitles_formatted`
- **Cancel**: `_SUMMARY_CANCEL_SET: set[str]` in `api.py`; `is_cancelled` lambda checked after response
- **API**: `POST /api/result/{video_id}/summary`, `DELETE /api/result/{video_id}/summary`
- **Defaults**: `DEFAULT_SYSTEM_PROMPT` and `DEFAULT_USER_PROMPT_TEMPLATE` in `text_summarizer.py`; seeded into `pipeline_settings` via `STAGE_DEFAULTS`
- **Frontend**: tab-aware actions bar — summary controls only visible on Summary tab; same pattern as cleanup

---

## Dependencies

- Epic 6 (Ollama client, cleanup polling pattern)
- Epic 7 (Settings page, pipeline_settings table)
- Epic 13 (ollama_url from DB)
- Epic 14 (timer pattern reused for summary)

## Status

**Status**: ✅ Done  
**Completed**: 2026-04-26  
**Priority**: 🟠 P1
