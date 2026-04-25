# Epic 11: Model Selection in UI (Standalone)

## Summary
User can select which Ollama model to use for cleanup directly from the Result page, without going to Settings. The model list is fetched live from the local Ollama instance.

**Note**: This epic is the lightweight standalone version of model selection. Epic 10 (Settings Page) covers per-stage model selection more fully. Epic 11 is relevant if the Settings page is deferred — it provides model selection as a self-contained feature on the Result page.

If Epic 10 is implemented first, Epic 11 may be partially or fully redundant. Review priority before starting.

## Business Value
Users who want to quickly try a different model for cleanup shouldn't need to go to a settings page. A dropdown next to the "Clean with AI" button is low friction.

## Scope

### Included
- Model dropdown on Result page, next to the "Clean with AI" button
- Model list from `GET /api/models` (proxied from Ollama `/api/tags`)
- Default = configured model or last selected (localStorage)
- Selected model sent with `POST /api/result/{video_id}/cleanup`
- Backend uses requested model for that run

### Not Included
- Per-stage model selection (covered by Epic 10)
- Model management (pulling, deleting models)

---

## User Stories

### US-1101: Model Dropdown on Result Page

**Title**: User selects Ollama model before running cleanup

**User Story**:
```
As a user
I want to pick a model from a dropdown next to the cleanup button
So that I can try different models without going to Settings
```

**Acceptance Criteria**:

**Given**: Result page is visible and Ollama is online

**When**: Page loads

**Then**:
- Compact model dropdown visible next to "✦ Clean with AI" button
- Shows all models from `GET /api/models`
- Default = `OLLAMA_MODEL` from config or `localStorage` last selection
- Disabled when Ollama is offline

**Notes for Engineering**:
- New endpoint: `GET /api/models` → `[{name: string, size: number}]` (proxied from Ollama `/api/tags`)
- `startCleanup(videoId, model?)` — sends `{model}` in request body
- `POST /api/result/{video_id}/cleanup` body: `{model?: string}`
- Backend: `set_cleanup_processing` unchanged; `_run_cleanup` receives model param, passes to `clean_text(text, model=model)`
- `localStorage` key: `yt_summarizer_model`

---

### US-1102: Persist Model Selection

**Title**: App remembers last selected model

**User Story**:
```
As a user
I want my model choice to be remembered
So that I don't re-select it every time
```

**Acceptance Criteria**:
- Model selection saved to `localStorage` on change
- On load: restore from `localStorage`, validate against current model list, fall back to default if not found

---

## Dependencies

- Epic 6 (cleanup endpoint)
- US-604 (Ollama health check)

## Relationship to Epic 10
- If Epic 10 (Settings) ships first: this epic can be skipped or reduced to just showing the currently configured model (read-only)
- If this epic ships first: Settings page inherits the `GET /api/models` endpoint

## Status

**Status**: 🔵 Planned  
**Priority**: 🟡 P2
