# Epic 16: Cancel for Auto-Pipeline

## Summary
A "✕ Stop pipeline" button on the Processing page when auto-pipeline is running (stage ② Cleaning or ③ Summarizing). Cancels the active background job and navigates to the Result page with whatever data is already available.

## Business Value
Users who start the full pipeline and change their mind (wrong video, takes too long) currently have no way to abort — they must wait or navigate away manually, leaving a zombie job running in the background.

## Scope

### Included
- "✕ Stop pipeline" button visible on ProcessingPage during stages ② and ③
- Stage ②: calls `DELETE /api/result/{video_id}/cleanup`
- Stage ③: calls `DELETE /api/result/{video_id}/summary`
- After cancel → navigate to `/result/{videoId}` immediately
- Button not shown during stage ① (extraction) — no cancel endpoint for task processing

### Not Included
- Cancel during stage ① (subtitle extraction) — would require task cancellation in FastAPI background tasks
- Cancel on the Result page (already exists — Epic 12 for cleanup, built into Epic 15 for summary)

---

## User Stories

### US-1601: Stop Auto-Pipeline During Cleanup

**As a** user  
**I want to** stop the pipeline while AI cleanup is running  
**So that** I can see the extracted subtitles without waiting for cleanup

**Acceptance Criteria**:
- "✕ Stop pipeline" button visible during stage ②
- Click calls `DELETE /api/result/{video_id}/cleanup`
- Navigate to result page (Subtitles tab, cleanup_status reset to null)

### US-1602: Stop Auto-Pipeline During Summarization

**As a** user  
**I want to** stop the pipeline while summarization is running  
**So that** I can read the cleaned text without waiting for summary

**Acceptance Criteria**:
- "✕ Stop pipeline" button visible during stage ③
- Click calls `DELETE /api/result/{video_id}/summary`
- Navigate to result page (Cleaned tab if available, else Subtitles)

---

## Implementation Notes

- Backend cancel endpoints already exist (`DELETE /cleanup` from Epic 12, `DELETE /summary` from Epic 15)
- `ProcessingPage.tsx` needs: state tracking current stage, Stop button rendered during stages ② and ③
- On Stop: call appropriate cancel endpoint → `navigate(`/result/${videoId}`)`
- Cleanup intervals must be cleared before navigate

---

## Dependencies

- Epic 10 (ProcessingPage auto-pipeline stages)
- Epic 12 (cancel cleanup endpoint)
- Epic 15 (cancel summary endpoint)

## Status

**Status**: ✅ Done  
**Completed**: 2026-04-26  
**Priority**: 🟡 P2
