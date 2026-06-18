# Epic 35: Playlist Import

**Status:** 🔵 Planned  
**Phase:** 2 — Summarization Quality  
**Depends on:** Epic 34 (Bulk URL Queue) ✅ required

---

## Strategic Context

A YouTube playlist is a natural unit of content: a course, a curated collection, a lecture series. The user should be able to paste a single playlist URL instead of copying dozens of URLs manually. All processing goes through the Epic 34 queue.

---

## Goal

User pastes a playlist URL → backend extracts all videos → user sees the list and confirms → all URLs are added to the Epic 34 queue.

---

## User Stories

### US-3501: Backend — playlist video extraction

**Given** a URL of the form `https://www.youtube.com/playlist?list=...`  
**When** `POST /api/queue/playlist` is called  
**Then** backend returns the list of playlist videos: `{title, url, video_id, duration_seconds, thumbnail_url}`

**Notes for Engineering:**
- yt-dlp supports flat-playlist extract: `yt-dlp --flat-playlist --dump-json PLAYLIST_URL`
- `--flat-playlist` — downloads nothing, metadata only. Fast.
- From JSON: `id` (video_id), `title`, `url`, `duration`
- Run via `asyncio.create_subprocess_exec` (same pattern as subtitle_extractor)
- Read `cookies_path` from `app_settings` — YouTube may require auth for private playlists
- Endpoint returns a preview, does NOT add to queue immediately — user confirms first

**Out of Scope:** private playlists without cookies, Mix/Radio playlists (yt-dlp supports them but they are infinite — cap at 200 videos)

**Edge Cases:**
- Invalid URL → 400
- Empty playlist → 200 with empty list
- yt-dlp error (private, deleted) → 422 with message
- Playlist > 200 videos → return first 200, warning in response: `"truncated": true`

---

### US-3502: API — confirmation and queue submission

**Given** user received the playlist preview  
**When** user confirms the selection (all or a subset)  
**Then** the selected URLs are passed to `POST /api/queue/bulk` (Epic 34) — reusing the existing endpoint

**Notes for Engineering:**
- No separate "import playlist to queue" endpoint needed — frontend takes URLs from the preview and calls `POST /api/queue/bulk`
- Two endpoints: `POST /api/queue/playlist/preview` (get list) then `POST /api/queue/bulk` (add)

---

### US-3503: Frontend — Playlist import UI

**Given** user is on the HomePage  
**When** in the Bulk Add panel (Epic 34) they enter a playlist URL and click "Import playlist"  
**Then**:
1. Button enters "Fetching..." state (spinner)
2. Playlist video list appears: thumbnail / title / duration / checkbox
3. "Select all" / "Deselect all" controls
4. Shows playlist name and total video count
5. "Add N selected to queue" button

**Notes for Engineering:**
- Playlist URL is auto-detected: if the pasted URL contains `playlist?list=` or `&list=` — show "Import playlist" button instead of the regular Add
- After adding: panel closes, toast "N videos added to queue"
- If `truncated: true` — show warning "Playlist has more than 200 videos. First 200 added."

**Out of Scope:** saving the playlist for periodic sync updates, showing per-video progress inside the playlist view

**Edge Cases:**
- Empty playlist → "This playlist has no videos"
- Fetch error → inline error below the field
- User selected no videos → "Add" button disabled

---

## Implementation Plan

1. 🔴 **BLOCKER** Epic 34 fully implemented
2. 🟠 `subtitle_extractor.py` — `fetch_playlist_videos(url, cookies_path)` → `list[dict]`
3. 🟠 `api.py` — `POST /api/queue/playlist/preview` endpoint
4. 🟡 `HomePage.tsx` — playlist detection + preview modal/panel
5. 🟡 CSS — playlist preview styles

---

## Complexity

~1–2 days after Epic 34. Main work is the yt-dlp flat-playlist call + UI preview. Queue logic is fully reused.
