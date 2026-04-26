# Epic 10: Auto-Pipeline Toggle

## Summary
A checkbox on the Home page — "Run full pipeline automatically" — that, when checked, automatically triggers AI cleanup immediately after subtitle extraction completes. The user submits the URL once and gets the cleaned result without manually pressing "Clean with AI" on the result page.

**Important constraint**: The Summary stage (Phase 2) is not yet implemented. Auto-pipeline covers only Extract → Format → Cleanup. Summary will be added to the auto-pipeline when Phase 2 is ready.

## Business Value
For users who always want the cleaned version, the current two-step flow (submit → wait → go to result → click "Clean with AI" → wait again) is tedious. The checkbox collapses this into a single submit action.

## Scope

### Included
- Checkbox on Home page: "Run full pipeline automatically (Extract + AI Cleanup)"
- Checkbox state persisted in `localStorage`
- Processing page shows extended status: "Extracting… → Formatting… → Cleaning with AI…"
- Auto-cleanup triggered from frontend when extraction completes (Processing page polls, detects completion, fires cleanup POST)
- Result page opens on Cleaned tab when auto-pipeline was used

### Not Included
- Auto-summary (Phase 2 not ready)
- Server-side pipeline chaining (frontend orchestrates for now — simpler, no backend changes)
- Background processing without the Processing page (requires push notifications)

---

## User Stories

### US-901: Auto-Pipeline Checkbox on Home Page

**Title**: User opts into automatic cleanup at submission time

**User Story**:
```
As a user
I want to check a box before submitting
So that cleanup runs automatically without extra steps
```

**Acceptance Criteria**:

**Given**: User is on the Home page

**When**: Page loads

**Then**:
- Checkbox below language selector: "☐ Run AI cleanup automatically"
- Default: unchecked (current behaviour preserved)
- State saved in `localStorage` (remembered across sessions)
- Small hint text: "Runs after extraction. Requires Ollama."
- Checkbox disabled with tooltip if Ollama is offline (health check)

**Notes for Engineering**:
- `localStorage` key: `yt_summarizer_auto_pipeline`
- Pass `autoPipeline: boolean` to ProcessingPage via router state or encode in URL query param
- Ollama online/offline: read from health check (already available via StatusBar)

---

### US-902: Processing Page Shows Extended Pipeline Status

**Title**: Processing page reflects cleanup phase when auto-pipeline is active

**User Story**:
```
As a user
I want to see the pipeline progressing through all stages
So that I know what's happening at each step
```

**Acceptance Criteria**:

**Given**: Auto-pipeline was enabled at submission

**When**: Processing page is showing

**Then**:
- Stage indicators visible: "① Extracting subtitles" → "② Formatting text" → "③ Cleaning with AI…"
- Active stage highlighted
- Completed stages shown with ✓
- If cleanup fails → warning shown, user still redirected to result with Subtitles tab

**Edge Cases**:
1. Ollama goes offline between extraction and cleanup → show warning, open Subtitles tab
2. User navigates away during cleanup → cleanup continues in background (existing polling mechanism)

**Notes for Engineering**:
- Processing page currently polls `/api/status/{task_id}`
- When status = `completed` AND `autoPipeline = true`:
  1. POST `/api/result/{video_id}/cleanup`
  2. Show "③ Cleaning with AI…"
  3. Poll `/api/result/{video_id}` every 3s until `cleanup_status !== 'processing'`
  4. Navigate to result page (Cleaned tab if done, Subtitles tab if failed)
- No backend changes needed

---

### US-903: Result Page Opens on Correct Tab After Auto-Pipeline

**Title**: Result page defaults to Cleaned tab when auto-pipeline completed successfully

**User Story**:
```
As a user
I want to land on the Cleaned tab automatically
So that I immediately see the result I asked for
```

**Acceptance Criteria**:

**Given**: Auto-pipeline ran and cleanup succeeded

**When**: Result page opens

**Then**:
- Cleaned tab is active by default (not Subtitles)
- This already works via existing logic (`cleanup_status === 'done'` → default to Cleaned tab)

**Notes for Engineering**:
- No additional changes needed — `setActiveTab` logic in ResultPage already handles this
- Verify: `data.cleanup_status === 'done' ? 'cleaned' : 'subtitles'` in `loadResult(switchTab=true)`

---

## Dependencies

- Epic 6 (cleanup endpoint + polling)
- US-604 (health check for Ollama status)

## What's Not Done (Phase 2 hook)

Stage ③ "Summarizing…" is intentionally omitted — summarization (Epic 15) is not yet implemented.
When Phase 2 ships, add the third stage to `ProcessingPage.tsx`:
- Extend `Stage` type: `'extracting' | 'cleaning' | 'summarizing'`
- After cleanup polling completes → POST `/api/result/{video_id}/summary`, poll until done
- Add `③ Summarizing…` indicator to `pipeline-stages` UI

## Status

**Status**: ✅ Done (Extract + Cleanup stages only)  
**Completed**: 2026-04-26  
**Priority**: 🟡 P2
