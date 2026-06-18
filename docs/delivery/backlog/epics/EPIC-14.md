# Epic 14: Cleanup Timer

Show how long AI cleanup took after it completes.

---

## User Stories

### US-1401: Show Cleanup Duration in Meta

**As a** user  
**I want to** see how long the AI cleanup took  
**So that** I can estimate future runs and compare models

**Acceptance Criteria**:
- After cleanup completes, meta block shows "Cleaned in M:SS"
- Duration is not shown while cleanup is running or before it has been run
- Duration persists across page reloads (stored in DB)

---

## Implementation Notes

- **DB**: `cleanup_started_at` and `cleanup_finished_at` columns on `subtitles_formatted`
- **Migration**: added in `_migrate_db()` in `database.py` via `ALTER TABLE ... ADD COLUMN`
- **Timestamps**: written via raw SQL using `strftime("%Y-%m-%d %H:%M:%S.%f")` — space separator required for SQLAlchemy DateTime parsing (not `.isoformat()` which uses `T`)
- **Duration**: computed server-side in `get_result()` as `int((finished - started).total_seconds())`
- **API**: `cleanup_duration_seconds` field added to `GET /api/result/{video_id}` response
- **Frontend**: `formatDuration()` reused; shown as `"Cleaned in: X:XX"` in meta block

---

## Status

**Status**: ✅ Done  
**Completed**: 26.04.2026  
**Priority**: 🟡 P2
