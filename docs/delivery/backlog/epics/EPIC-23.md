# Epic 23: Chapter-Aware Subtitle Formatting

**Phase**: 2 — Summarization Quality  
**Status**: ✅ Done  
**Priority**: 🟠 P1

## Goal

When a YouTube video has creator-defined chapters, use those chapters as semantic
boundaries for subtitle grouping instead of generic time-gap splitting. Each chapter
becomes a `##` heading in `formatted_text`, preserving the author's original structure.
Falls back to 4-second gap grouping when no chapters are present.

---

## User Stories

---

### US-2301: Chapter-based text grouping

**As a** user processing a structured YouTube video  
**I want** the extracted text to follow the creator's chapter structure  
**So that** each section is semantically meaningful and correctly named

#### Acceptance Criteria

**Given** a video has creator-defined chapters in yt-dlp metadata  
**When** subtitles are extracted and formatted  
**Then** `formatted_text` contains `## Chapter Title` headings at chapter boundaries

**Given** a video has no chapters  
**When** subtitles are extracted and formatted  
**Then** formatting falls back to 4-second time-gap paragraph splitting (existing behavior)

**Given** a subtitle entry falls between chapter boundaries (gap in chapters)  
**When** assigned to a chapter  
**Then** it is assigned to the nearest preceding chapter

#### Edge Cases

- Empty chapter (no subtitles in its time range) → chapter is skipped, no empty `##` heading
- Subtitles before first chapter start → assigned to the first chapter
- `chapters` field absent or empty list → gap-based fallback
- Chapters out of order in metadata → sorted by `start_time` before processing

#### Out of Scope

- Displaying chapters as a clickable table of contents in UI
- Detecting chapters from audio or description parsing
- User-editable chapters

#### Notes for Engineering

yt-dlp `info["chapters"]` structure:
```json
[{"start_time": 0.0, "end_time": 120.5, "title": "Introduction"}, ...]
```

`_build_metadata()` in `subtitle_extractor.py` parses chapters into
`VideoMetadata.chapters: list[dict] | None` (start_time/end_time cast to int).

`text_formatter.py` has two branches:
- `_format_with_chapters(segments, chapters)` — chapter-boundary grouping
- `_format_with_gaps(segments, paragraph_gap)` — existing 4s gap logic

`format_subtitles(entries, chapters=None)` selects branch based on `chapters` arg.
Returns `has_chapters: bool` in result dict.

`Video.chapters` JSON column added to DB (migration in `_migrate_db()`).
`get_result()` returns `chapters` field in API response.

---

## Implementation

| File | Change |
|------|--------|
| `subtitle_extractor.py` | `VideoMetadata.chapters` field; `_build_metadata()` parses `info["chapters"]` |
| `models.py` | `Video.chapters: JSON` column |
| `database.py` | Migration: `ALTER TABLE videos ADD COLUMN chapters TEXT` |
| `text_formatter.py` | `_format_with_chapters()`, `_format_with_gaps()`, updated `format_subtitles()` |
| `video_service.py` | Saves `video.chapters`; returns `chapters` in `get_result()` |
| `api.py` | Passes `chapters=extraction.metadata.chapters` to `format_subtitles()` |
