# Epic 12: Cancel Cleanup

Stop a running AI cleanup without waiting for it to finish.

---

## User Stories

### US-1201: Stop Button During Cleanup

**As a** user  
**I want to** stop a running AI cleanup at any time  
**So that** I don't have to wait for a long-running job to finish

**Acceptance Criteria**:
- "✦ Clean with AI" button is replaced by "✕ Stop" while `cleanup_status === 'processing'`
- Clicking Stop immediately resets status to `null` (no cleaned text shown)
- Next poll cycle reflects the cancelled state

---

## Implementation Notes

- **Backend**: `_CANCEL_SET: set[str]` in `api.py` — in-memory cancel flags
- **API**: `DELETE /api/result/{video_id}/cleanup` — adds video_id to `_CANCEL_SET`
- **text_cleaner.py**: `is_cancelled` callback checked before each paragraph in the Ollama loop
- **On finish**: if `video_id in _CANCEL_SET` → `reset_cleanup_status` + `discard`; else → `finish_cleanup`
- **Re-run safety**: `_CANCEL_SET.discard(video_id)` called in `trigger_cleanup` to clear stale flags
- **Frontend**: `handleCancel()` stops polling, calls `DELETE`, resets local state optimistically

---

## Status

**Status**: ✅ Done  
**Completed**: 26.04.2026  
**Priority**: 🔴 P0
