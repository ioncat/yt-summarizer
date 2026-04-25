# Epic 7: Settings Page — Prompts & Models Per Stage

## Summary
A dedicated Settings page in the web UI where the user can view and edit the system prompt, user prompt template, and model selection for each pipeline stage independently. 

**Key insight from product**: Cleanup and Summarization are different tasks that benefit from different models. For example:
- **Cleanup (Phase 1.5)** — short, fast, per-paragraph → AYA (`cas/aya-expanse-8b`) works well
- **Summarization (Phase 2)** — long context, complex reasoning → Qwen or a larger model may perform better

Prompts are also different: cleanup fixes punctuation and removes fillers; summarization condenses meaning.

## Business Value
Currently prompts are hardcoded in `text_cleaner.py` and `text_summarizer.py`. To tune output quality, the user must edit Python files and restart the backend — high friction for non-developers. A settings UI makes prompt iteration fast and accessible.

## Scope

### Included
- Settings page (new route `/settings`)
- Nav link to Settings
- Per-stage configuration: **Cleanup** and **Summarization** (Summary stage shown but locked until Phase 2)
- Per stage: system prompt (editable textarea), user prompt template (editable textarea), model selector (dropdown from Ollama)
- Default values = current hardcoded prompts from source
- Settings persisted in DB (new `pipeline_settings` table) so they survive restarts
- "Reset to defaults" button per stage
- Live model list from Ollama (same as Epic 11)

### Not Included
- Per-video prompt overrides
- Prompt versioning / history
- A/B testing prompts
- Prompt import/export (future)
- Authentication/access control

---

## User Stories

### US-1001: View Settings Page

**Title**: User can navigate to a Settings page

**User Story**:
```
As a user
I want a dedicated settings area
So that I can configure the pipeline without touching code
```

**Acceptance Criteria**:

**Given**: App is running

**When**: User clicks "Settings" in nav or navigates to `/settings`

**Then**:
- Settings page loads with two sections: "AI Cleanup" and "Summarization"
- Each section shows: current model, system prompt, user prompt template
- Summarization section is visually marked as "Phase 2 — coming soon" and fields are read-only until implemented
- "Save" and "Reset to defaults" buttons per section

---

### US-1002: Edit Cleanup Prompts

**Title**: User can edit the system and user prompt for the cleanup stage

**User Story**:
```
As a user
I want to edit the cleanup prompt
So that I can tune how the LLM fixes my transcripts
```

**Acceptance Criteria**:

**Given**: User is on Settings page, Cleanup section

**When**: User edits system prompt or user prompt textarea and clicks Save

**Then**:
- New prompts are saved to DB (`pipeline_settings` table, stage = `cleanup`)
- Next cleanup run uses the new prompts
- Toast confirmation: "Cleanup settings saved"
- "Reset to defaults" restores the original hardcoded prompts

**Prompt variables available in user prompt template**:
- `{text}` — the paragraph text to clean

**Notes for Engineering**:
- New DB table: `pipeline_settings(id, stage TEXT, system_prompt TEXT, user_prompt_template TEXT, model TEXT, updated_at)`
- Stage values: `cleanup`, `summarization`
- `text_cleaner.py`: load prompts from DB at call time (or cache with TTL)
- API: `GET /api/settings` → `{cleanup: {...}, summarization: {...}}`
- API: `PUT /api/settings/{stage}` → updates one stage
- Migration: `CREATE TABLE IF NOT EXISTS pipeline_settings (...)`

---

### US-1003: Select Model Per Stage

**Title**: User can choose a different Ollama model for cleanup vs summarization

**User Story**:
```
As a user
I want to use AYA for cleanup and Qwen for summarization
So that each stage uses the best model for its task
```

**Acceptance Criteria**:

**Given**: User is on Settings page

**When**: User opens the model dropdown for a stage and selects a model

**Then**:
- Model saved to `pipeline_settings` for that stage
- Next run of that stage uses the selected model
- Available models fetched live from Ollama (same `GET /api/models` endpoint as Epic 11)
- Default model = `OLLAMA_MODEL` from `.env` (for both stages initially)
- If Ollama is offline → dropdown disabled, tooltip "Ollama offline — cannot load models"

**Notes for Engineering**:
- `text_cleaner.py`: `clean_text(text, model=None)` — `model` param; if None, read from `pipeline_settings` table (stage=`cleanup`); if not in DB, fall back to `settings.ollama_model`
- `text_summarizer.py` (Phase 2): same pattern for `stage=summarization`

---

### US-1004: Reset Stage to Defaults

**Title**: User can reset a stage's settings to factory defaults

**User Story**:
```
As a user
I want a "Reset to defaults" button
So that I can recover if I've made the prompts worse
```

**Acceptance Criteria**:

**Given**: User has modified prompts or model for a stage

**When**: User clicks "Reset to defaults" and confirms

**Then**:
- DB row for that stage is deleted (fallback to hardcoded defaults)
- Fields in UI refresh to show default values
- Next run uses hardcoded defaults from source

---

## DB Schema

```sql
CREATE TABLE IF NOT EXISTS pipeline_settings (
    id          TEXT PRIMARY KEY,
    stage       TEXT NOT NULL UNIQUE,   -- 'cleanup' | 'summarization'
    system_prompt       TEXT,
    user_prompt_template TEXT,
    model               TEXT,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | All stage settings (cleanup + summarization) |
| PUT | `/api/settings/cleanup` | Save cleanup stage settings |
| PUT | `/api/settings/summarization` | Save summarization stage settings |
| DELETE | `/api/settings/{stage}` | Reset stage to defaults |
| GET | `/api/models` | Available Ollama models (live) |

## Dependencies

- Epic 6 (cleanup pipeline exists)
- US-604 (Ollama health check)
- Phase 2 Epic 12 (summarization stage — settings page prepares for it)

## Status

**Status**: ✅ Done  
**Priority**: 🟠 P1
