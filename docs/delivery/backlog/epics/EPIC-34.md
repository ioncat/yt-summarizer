# Epic 34: Bulk URL Queue

**Status:** ✅ Done  
**Phase:** 2 — Summarization Quality  
**Depends on:** —  
**Blocks:** Epic 35 (Playlist Import)

---

## Strategic Context

Processing one video at a time is a manual workflow. A user with a large content list (a course, a channel, a research topic) has to add videos one by one and wait for each. A batch queue removes this barrier and enables unattended background processing scenarios.

---

## Goal

User pastes multiple URLs, one per line → all enter the queue → backend processes them sequentially through the selected pipeline → user sees the status of each item.

---

## User Stories

### US-3401: DB schema and queue worker

**Given** the backend starts  
**When** `_migrate_db()` runs  
**Then** the `processing_queue` table exists with columns:
`id`, `url`, `video_id`, `status`, `pipeline_stages`, `error_message`, `added_at`, `started_at`, `finished_at`, `sort_order`

**Notes for Engineering:**
- `status` ∈ `pending | processing | done | failed | skipped`
- `pipeline_stages` — JSON array: `["extract"]` / `["extract","cleanup"]` / `["extract","cleanup","summary"]`
- `video_id` — populated after extraction completes (foreign key to `videos` table)
- Queue worker: asyncio background task, started in `lifespan()`, polling every 5 seconds
- Worker picks one `pending` item, sets it to `processing`, runs pipeline stages sequentially
- On error: `status = failed`, `error_message` filled in, moves to the next item
- **Strictly one item processed at a time** — Ollama does not support parallel heavy requests
- DB backup before migration

**Out of Scope:** priority ordering within the queue, pause/resume of the entire queue

**Edge Cases:**
- Backend restarts mid-processing → items with `processing` status at startup are reset to `pending`
- Duplicate URL in queue → added (user may have wanted reprocessing), not blocked
- URL unreachable → `status = failed`, message from subtitle_extractor error classification

---

### US-3402: API endpoints

**Given** the queue is implemented  
**When** client calls the API  
**Then** the following endpoints are available:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/queue/bulk` | Accepts `{urls: string[], pipeline_stages: string[]}` → adds to queue → returns list of added ids |
| GET | `/api/queue` | Returns all items, sorted by `sort_order` + `added_at` |
| DELETE | `/api/queue/{id}` | Deletes a pending item. Cannot delete a processing item |
| DELETE | `/api/queue` | Clears only `pending` items (does not touch processing/done/failed) |

**Notes for Engineering:**
- Validation: each URL is run through `extract_video_id()` on add — invalid ones are rejected immediately
- Dedup: a URL is considered a duplicate if its `video_id` already exists in `videos` (previously processed) or in `processing_queue` with status `pending`/`processing` (already queued). Duplicates are skipped, not added.
- `pipeline_stages` default if not provided: read from `app_settings` (`queue_default_pipeline`, seed = `["extract"]`)
- `GET /api/queue` includes UI fields: `id`, `url`, `video_id`, `status`, `error_message`, `added_at`, `started_at`, `finished_at`
- `POST /api/queue/bulk` response: `{added, ids, invalid: [url], duplicates: [url]}`

**Out of Scope:** pagination for GET /api/queue (not needed for a reasonable number of videos)

**Edge Cases:**
- POST with empty URL array → 400
- All URLs invalid → 400
- All URLs are duplicates → 200, `added: 0`, `duplicates: [...]` (not an error — user sees why nothing was added)
- Mix of duplicates and new URLs → add only new ones, show `duplicates: [...]` in UI
- DELETE on processing item → 409 Conflict

---

### US-3403: Frontend — Bulk Add panel on HomePage

**Given** user is on the HomePage  
**When** clicks "Bulk add" (button next to the main URL field)  
**Then** a panel expands with:
- `<textarea>` — "Paste URLs, one per line"
- Pipeline stage selector: "Extract only" / "Extract + Cleanup" / "Full pipeline"
- "Add to queue (N URLs)" button — N updates live as user types
- Cancel button — hides the panel

**Notes for Engineering:**
- Textarea parsing: split by `\n`, trim each line, filter empty lines
- Frontend validation: simple regex for youtube.com/watch or youtu.be — everything else is rejected by the backend
- After submit: panel closes, toast "N videos added to queue" shown
- Does not navigate away — user stays on the page

**Out of Scope:** drag & drop file with URL list, import via clipboard API

**Edge Cases:**
- All URLs invalid → show errors inline below the textarea
- Mix of valid and invalid → add valid ones, show list of invalid
- All URLs are duplicates → `added: 0`, show "All N URLs already processed" + list
- Mix of duplicates → add unique ones, show "N added, M duplicates skipped" + duplicate list

---

### US-3404: Frontend — Queue status view

**Given** there are items in the queue  
**When** user opens the Queue page (`/queue`) or panel  
**Then** sees a list of items with columns: order / URL (short) / status / pipeline / time

**Notes for Engineering:**
- New nav link "⏱ Queue" next to History (shown only when there are pending/processing items — badge with count)
- Poll GET /api/queue every 3 seconds while there are processing/pending items
- Status icons: ⏸ pending / ⏳ processing / ✓ done / ❌ failed / — skipped
- `done` items — clickable → navigate to `/result/{video_id}`
- `failed` items — show error_message on hover/expand
- "Clear completed" button — DELETE /api/queue (pending only) + removes done/failed from UI
- "✕" button on pending item — DELETE /api/queue/{id}

**Out of Scope:** reorder via drag & drop, pause individual items

**Edge Cases:**
- Queue empty → "No items in queue"
- Processing item cannot be deleted — button disabled with tooltip

---

## Implementation Plan

1. 🔴 **BLOCKER** `models.py` + `database.py` — `processing_queue` table + migration + `app_settings` seed for `queue_default_pipeline`
2. 🔴 **BLOCKER** `queue_service.py` — queue CRUD + queue worker (`_queue_worker` asyncio loop, started in `lifespan`)
3. 🟠 `api.py` — 4 new endpoints
4. 🟠 `HomePage.tsx` — Bulk Add panel
5. 🟡 `QueuePage.tsx` — new page + nav link
6. 🟡 CSS — styles for the panel and page

---

## Open Questions

- **Queue worker + manual pipeline conflict** — if the user manually triggers a summary while the queue is running: two Ollama calls in parallel? Resolution: queue worker checks `_SUMMARY_CANCEL_SET` or `summary_status == 'processing'` before starting — if busy, waits for the next polling tick.
