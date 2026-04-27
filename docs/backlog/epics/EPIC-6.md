# Epic 6: LLM Text Cleanup (Ollama)

## Summary
User can trigger AI-powered cleanup of the extracted transcript on demand. Cleanup fixes punctuation, capitalisation, removes filler words, and merges broken sentence fragments. Runs locally via Ollama — no data leaves the machine.

## Business Value
Auto-generated subtitles from YouTube are often noisy: missing punctuation, random capitalisation, filler words ("ну", "вот", "как бы"), broken sentences. A single click produces a significantly more readable text without the user having to edit it manually.

## Scope

### Included
- Manual trigger button "Clean with AI" on the Result page
- Progress indicator (spinner) while cleanup runs
- Ability to re-run cleanup (LLMs are non-deterministic — user may want a better result)
- Separate "Cleaned" tab alongside "Subtitles" tab
- Error state when Ollama is unreachable
- Health check indicators for backend and Ollama in nav bar
- Cleanup status persisted in DB (`cleanup_status`: null | processing | done | failed)

### Not Included
- Automatic cleanup without user action
- Streaming token-by-token output
- Per-paragraph progress counter (whole-text spinner only)
- Cleanup editing/feedback loop

---

## User Stories

### US-601: Trigger AI Cleanup Manually

**Title**: User triggers AI cleanup of transcript with a button

**User Story**:
```
As a user
I want to clean up the transcript with AI on demand
So that I get a more readable version without it running automatically
```

**Acceptance Criteria**:

**Given**: Result page is showing extracted subtitles

**When**: User clicks "✦ Clean with AI"

**Then**:
- Button immediately shows "⟳ Cleaning…" with spinner and becomes disabled
- "Cleaned" tab shows spinner
- Polling starts every 3 seconds against `GET /api/result/{video_id}`
- When `cleanup_status` = `done`: Cleaned tab activates, text appears, button changes to "↺ Re-run AI cleanup"
- When `cleanup_status` = `failed`: Error banner shown, button re-enabled

**Edge Cases**:
1. Ollama offline → `cleanup_status` = `failed`, error banner shown
2. User refreshes mid-cleanup → polling resumes from `cleanup_status = processing` in DB
3. Very long text (50+ paragraphs) → button stays disabled until done

**Notes for Engineering**:
- `POST /api/result/{video_id}/cleanup` — sets status to `processing`, starts background task
- `_run_cleanup` background task: calls `clean_text()`, writes result to `subtitles_formatted.cleaned_text`
- `cleanup_status` column (TEXT, nullable): null | processing | done | failed
- Migration: `ALTER TABLE subtitles_formatted ADD COLUMN cleanup_status TEXT`

**Dependencies**: US-503 (result page), Epic 3 (DB)

---

### US-602: View Cleaned Text in Separate Tab

**Title**: Cleaned text shown in dedicated tab alongside original subtitles

**User Story**:
```
As a user
I want to switch between the original subtitles and the cleaned version
So that I can compare and choose which to use
```

**Acceptance Criteria**:

**Given**: Cleanup has completed successfully

**When**: Result page is visible

**Then**:
- Two tabs: "Subtitles" and "Cleaned"
- Cleaned tab is active by default after cleanup finishes
- Subtitles tab always accessible
- Cleaned tab disabled (not clickable) when cleanup not yet run or failed
- Copy button copies the text of the currently active tab

**Edge Cases**:
1. Cleanup not yet run → Cleaned tab greyed out, not clickable
2. Cleanup failed → Cleaned tab greyed out with no text
3. User navigates away and back → tab state defaults to Subtitles, switches to Cleaned if status = done

---

### US-603: Re-run AI Cleanup

**Title**: User can re-run cleanup to get a different result

**User Story**:
```
As a user
I want to re-run the AI cleanup
So that I can get a different result if the first one wasn't satisfactory
```

**Acceptance Criteria**:

**Given**: Cleanup has already completed (`cleanup_status` = `done`)

**When**: User clicks "↺ Re-run AI cleanup"

**Then**:
- Same flow as US-601 (spinner, polling, result)
- Previous `cleaned_text` is overwritten in DB
- Cleaned tab clears while processing, then shows new result

**Notes for Engineering**:
- `set_cleanup_processing` resets `cleaned_text = null`, `cleanup_status = processing`
- Re-run is identical to first run from backend perspective

---

### US-604: Health Check Status in Nav Bar

**Title**: User sees backend and Ollama availability indicators at all times

**User Story**:
```
As a user
I want to see at a glance whether the backend and Ollama are running
So that I understand why cleanup might fail before I even try
```

**Acceptance Criteria**:

**Given**: Any page in the app

**When**: App is loaded

**Then**:
- Two dots in nav bar: "● API" and "● Ollama"
- Green = online, Red = offline, Grey = checking
- Updates every 15 seconds
- Tooltip on hover: "{service} — online / offline"

**Notes for Engineering**:
- `GET /api/health` → `{backend: true, ollama: true/false}`
- Ollama check: `GET {OLLAMA_URL}/api/tags` with 3s timeout
- `StatusBar` component in nav, polls via `setInterval(check, 15_000)`

---

## Technical Notes

- **Model**: `cas/aya-expanse-8b` (configurable via `OLLAMA_MODEL` in `.env`)
- **Prompt strategy**: per-paragraph (stays within context window)
- **Timeout**: 120s per HTTP request to Ollama (long videos have many paragraphs)
- **Availability check**: `GET /api/tags` with 3s timeout before processing
- **Failure mode**: graceful — returns `None`, sets `cleanup_status = failed`

## Status

**Status**: ✅ Done  
**Completed**: 2026-04-25  
**Priority**: 🟠 P1
