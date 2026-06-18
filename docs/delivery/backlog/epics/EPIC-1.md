# Epic 1: Core Subtitle Extraction

## Summary
User can submit a YouTube video URL and receive extracted subtitles in a structured format.

## Business Value
Enables the foundation of the application - extracting raw subtitle data from YouTube videos without manual intervention.

## Scope

### Included
- YouTube URL validation
- Subtitle extraction using yt-dlp
- Support for multiple languages (ru, en, uk)
- Language selection when multiple subtitles available
- Error handling for missing/unavailable subtitles
- Return raw subtitle data (with timestamps)

### Not Included
- Text formatting (Epic 2)
- Saving to database (Epic 3)
- UI presentation (Epic 5)
- LLM integration (Phase 2)

---

## User Stories

### US-101: Submit YouTube URL for Processing

**Title**: User submits YouTube video URL for subtitle extraction

**User Story**:
```
As a user
I want to submit a YouTube video URL
So that I can extract subtitles from that video
```

**Acceptance Criteria**:

**Given**: User is on the home page with URL input field

**When**: User enters valid YouTube URL (https://www.youtube.com/watch?v=...) and clicks "Process"

**Then**:
- URL is validated
- Request sent to backend
- User sees processing confirmation
- User sees processing status indicator with task ID

**And When**: User enters invalid URL

**Then**: Error message "Please enter a valid YouTube URL" and no backend request

**Edge Cases**:
1. Empty input → "Please enter a YouTube URL"
2. URL without protocol → Accept and auto-add https://
3. Short YouTube URL (youtu.be/abc123) → Accept
4. YouTube playlist URL → Error "Please enter a single video URL"
5. Non-YouTube URL → Error "Please enter a valid YouTube URL"
6. URL with timestamps/extra parameters → Accept and extract correctly

**Out of Scope**: User auth, URL bookmarking, batch processing, metadata pre-validation

**Notes for Engineering**:
- Frontend URL validation (regex or URL parsing library)
- Extract video ID from various YouTube URL formats
- Async request to backend `/api/process` endpoint
- Backend returns task ID
- Frontend stores task ID and shows status page
- Use axios/fetch for HTTP

**Dependencies**: None

**Analytics**: Track "user_submitted_url" events

---

### US-102: Extract Subtitles from Video

**Title**: Backend extracts subtitles from YouTube video using yt-dlp

**User Story**:
```
As a backend system
I want to extract subtitles from a YouTube video
So that they can be formatted and stored for the user
```

**Acceptance Criteria**:

**Given**: Valid YouTube URL received, video has subtitles

**When**: Backend calls yt-dlp with video URL

**Then**: Subtitles returned in format: `[{timestamp: "00:00:10", text: "Hello"}, ...]`
- All text preserved exactly
- Timestamps accurate in HH:MM:SS format
- Language detected/specified

**And When**: Video has multiple subtitle tracks, user selected language

**Then**: Only selected language extracted

**And When**: Processing takes longer than expected

**Then**: No timeout before completion, user sees progress updates

**Edge Cases**:
1. Video with no subtitles → Return empty array, flag "no_subtitles"
2. Multiple languages available → Extract only requested
3. Auto-generated only → Extract if available, mark "auto_generated"
4. Very long video (3+ hours) → Still extract all subtitles
5. Special characters/non-ASCII → Preserve exactly (emoji, Cyrillic, etc)
6. Duplicate consecutive subtitles → Preserve as-is
7. Deleted or private video → Return error, don't hang

**Out of Scope**: Translating subtitles, summarizing, filtering text, downloading video, age restrictions

**Notes for Engineering**:
- Use yt-dlp Python library
- Implement as async function
- Handle yt-dlp errors with meaningful messages
- Log extraction details
- Return structure:
```json
{
  "subtitles": [{timestamp, text}, ...],
  "language": "ru",
  "source_type": "auto_generated" | "manual",
  "raw_count": 150
}
```
- Timeout: max 30 seconds
- Retry logic for transient errors

**Dependencies**: US-101, US-103

**Analytics**: Track "subtitle_extraction_started", "subtitle_extraction_completed", log extraction_time, subtitle_count, language

---

### US-103: Select Subtitle Language

**Title**: User selects preferred subtitle language when video has multiple options

**User Story**:
```
As a user
I want to select a subtitle language
So that I can extract subtitles in my preferred language
```

**Acceptance Criteria**:

**Given**: User submitted URL, backend detected multiple languages

**When**: User sees language dropdown, selects language

**Then**: Selected language sent to backend, subtitles extracted in that language

**And When**: Video has only one language

**Then**: Language selection skipped, subtitles extracted automatically

**And When**: Video has no subtitles

**Then**: Language selection not shown, error displayed

**Edge Cases**:
1. Video with 5+ languages → Show all in dropdown
2. Chinese Simplified vs Traditional → Show clear distinction
3. Auto-generated vs manual same language → Show both options
4. User selects unavailable language → Error with available list
5. Language availability changes → Handle gracefully

**Out of Scope**: Language translation, forcing selection if only one, language auto-detection

**Notes for Engineering**:
- Show dropdown after URL submission
- Backend returns available languages: `["ru", "en", "uk", ...]`
- Display language names not codes: "Russian" not "ru"
- Default: first available or user's last selection
- Send language code with extraction request
- Cache language list per video

**Dependencies**: US-101, US-102

---

### US-104: Handle Missing Subtitles Gracefully

**Title**: Application handles videos with no subtitles with clear error messaging

**User Story**:
```
As a user
I want to understand why subtitle extraction failed
So that I can decide what to do next
```

**Acceptance Criteria**:

**Given**: User submitted URL, video has no subtitles

**When**: Backend attempts extraction, finds no subtitles

**Then**: Processing completes without crash, user sees "This video has no subtitles available."

**And When**: User sees error for missing subtitles

**Then**: Message is helpful and not technical, user knows it's video limitation not app fault, can easily try another video

**Edge Cases**:
1. Closed captions disabled → Same error "This video has no subtitles available."
2. Auto-generated only, language not available → "Subtitles not available in [language]. Available: [list]"
3. Unexpected subtitle format → "Unable to extract subtitles. Try another."
4. Video was available, now deleted → "Video is no longer available."
5. Subtitles temporarily unavailable → "Subtitles temporarily unavailable. Try again later."

**Out of Scope**: Auto speech-to-text fallback (Phase 3), suggesting alternatives, manual subtitle upload, notifying YouTube

**Notes for Engineering**:
- Detect "no subtitles" explicitly in US-102
- Return clear status code/flag in response
- Frontend displays appropriate message per error type
- Log error reason for analytics
- Provide actionable next steps

Error types:
- `no_subtitles` - No captions at all
- `language_not_available` - Captions exist but not selected language
- `video_unavailable` - Deleted, private, age-restricted
- `extraction_failed` - Unexpected error

**Dependencies**: US-102

**Analytics**: Track "subtitle_extraction_failed", log failure_reason, video_id, requested_language

---

## Acceptance Criteria (Epic Level)

- User can submit any valid YouTube URL
- Backend successfully extracts subtitles using yt-dlp
- Multiple languages handled correctly
- Raw subtitle data includes timestamps
- Clear error messages for edge cases
- Processing completes within 30 seconds for typical videos

## Technical Notes

- Use yt-dlp for extraction (no YouTube API key required)
- Support ru, en, uk languages initially
- Return subtitle format: array of {timestamp, text} objects
- Implement async processing for responsiveness

## Dependencies

None (foundational epic)

## Status

**Status**: ✅ Done  
**Priority**: 🔴 P0 (Critical)
