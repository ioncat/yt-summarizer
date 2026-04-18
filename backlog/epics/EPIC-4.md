# Epic 4: Error Handling & Edge Cases

## Summary
Application handles all error scenarios gracefully with clear, user-friendly messages.

## Business Value
Reduces user frustration and confusion when things go wrong. Clear error messages help users understand what happened and what to do next.

## Scope

### Included
- Invalid YouTube URL detection and messaging
- Missing subtitles handling
- Restricted/private video detection
- Network error handling and retry logic
- Processing timeout handling
- Malformed subtitle data handling
- Clear, actionable error messages for all scenarios
- Logging for debugging

### Not Included
- Email notifications (future)
- Automatic retry with exponential backoff (future)
- User support ticket creation (future)

---

## User Stories

### US-401: Handle Invalid YouTube URLs

**Title**: Detect and report invalid YouTube URLs clearly

**User Story**:
```
As a user
I want to know when I've entered an invalid URL
So that I can correct it and try again
```

**Acceptance Criteria**:

**Given**: User submits invalid URL

**When**: Backend validates URL

**Then**: Clear error message displayed
- "Please enter a valid YouTube URL"
- User can see what's wrong
- User can easily correct and retry

**Examples**:
- `google.com` → Error
- `https://youtube.com/invalid` → Error
- `hello world` → Error
- Empty string → Error
- Special characters → Error

**Valid Examples**:
- `https://www.youtube.com/watch?v=abc123`
- `https://youtu.be/abc123`
- `youtube.com/watch?v=abc123` (auto-add https)

**Edge Cases**:
1. Unicode characters in URL → Handle correctly
2. URL with query parameters → Extract video ID correctly
3. Very long URL → Validate without timeout
4. Redirect URL → Resolve and validate

**Out of Scope**: URL shortening services, playlist URLs

**Notes for Engineering**:
- Frontend validation using regex or URL parsing
- Backend validation as well (defense in depth)
- Extract video ID from URL
- Return specific error: "Invalid URL format"
- Log invalid URLs for analysis

**Dependencies**: None

**Analytics**: Track invalid_url_attempts

---

### US-402: Handle Videos with No Subtitles

**Title**: Gracefully handle videos without subtitles

**User Story**:
```
As a user
I want clear feedback when a video has no subtitles
So that I understand it's a video limitation, not app fault
```

**Acceptance Criteria**:

**Given**: Valid YouTube URL, video has no subtitles

**When**: Backend attempts extraction

**Then**:
- No error/crash occurs
- User sees message: "This video has no subtitles available."
- User can try another video
- Processing task marked as complete (not failed)

**Edge Cases**:
1. Auto-generated subtitles only, requested language unavailable → "Subtitles not available in [language]. Available: Russian, English"
2. Subtitles disabled by uploader → Same message
3. Video is private/restricted → Handled in US-403

**Out of Scope**: Speech-to-text fallback (Phase 3), requesting upload from user

**Notes for Engineering**:
- Detect missing subtitles explicitly in extraction
- Return status: "no_subtitles" not "error"
- Check for both auto and manual subtitles
- If auto available but not requested language, list available
- Log for analytics

**Dependencies**: US-102 (extraction)

**Analytics**: Track no_subtitles_count, languages_requested

---

### US-403: Handle Restricted/Private Videos

**Title**: Detect and report inaccessible videos

**User Story**:
```
As a user
I want to know when a video is unavailable
So that I can choose a different video
```

**Acceptance Criteria**:

**Given**: User submits URL for restricted video

**When**: Backend attempts to access

**Then**: Clear error message appears
- "This video is not available."
- User understands video is not accessible
- Can try another video

**Cases**:
1. Private video → "This video is private."
2. Deleted video → "This video has been deleted."
3. Age-restricted → "This video is age-restricted and cannot be processed."
4. Geographically blocked → "This video is not available in your region."
5. Copyright claim → "This video cannot be processed due to copyright restrictions."

**Edge Cases**:
1. Video became unavailable after URL submission → Handled gracefully
2. Video was available at submission time → Still fail gracefully

**Out of Scope**: Bypassing restrictions, alternative access methods

**Notes for Engineering**:
- yt-dlp returns specific error codes for each case
- Map error codes to user-friendly messages
- Log error type for analytics
- Don't expose technical details to user

**Dependencies**: US-101 (URL validation)

**Analytics**: Track video_unavailable_count, reason_breakdown

---

### US-404: Handle Network Errors

**Title**: Handle network issues gracefully

**User Story**:
```
As a user
I want the app to handle network problems gracefully
So that I can retry without losing my work
```

**Acceptance Criteria**:

**Given**: Network error occurs during processing

**When**: Error detected

**Then**:
- User sees message: "Network error. Please check connection and try again."
- Processing state preserved
- User can retry same URL
- No data loss

**Errors to handle**:
1. Connection timeout → Retry message
2. Connection refused → Network error message
3. Intermittent packet loss → Retry with backoff
4. DNS failure → Check internet connection message

**Edge Cases**:
1. Error mid-extraction → Allow restart
2. Error during save → Rollback transaction
3. Repeated failures → Increase retry interval

**Out of Scope**: VPN/proxy configuration, DNS configuration

**Notes for Engineering**:
- Implement exponential backoff (3 retries max)
- Set reasonable timeouts (30 sec for extraction, 10 sec for formatting)
- Catch socket errors, timeout errors, connection errors
- Preserve partial results if possible
- Log network errors with timestamps

**Dependencies**: US-101, US-102

**Analytics**: Track network_errors, retry_count, failure_rate

---

### US-405: Handle Processing Timeouts

**Title**: Gracefully handle processing that takes too long

**User Story**:
```
As a user
I want the app to tell me if processing takes too long
So that I'm not left waiting indefinitely
```

**Acceptance Criteria**:

**Given**: Processing takes longer than threshold

**When**: Timeout reached

**Then**:
- Processing stopped
- User sees message: "Processing took too long. Please try again later."
- Can retry immediately
- State cleaned up

**Timeouts**:
- Subtitle extraction: 30 seconds
- Text formatting: 10 seconds
- Database save: 5 seconds
- Total processing: 60 seconds

**Edge Cases**:
1. Timeout after partial completion → Cleanup gracefully
2. Video very long (3+ hours) → Increase timeout, not error
3. System under heavy load → Handle queue properly

**Out of Scope**: Async job queues (future enhancement)

**Notes for Engineering**:
- Use async timeout mechanisms
- Log timeout errors with context
- Consider adjusting timeouts for very long videos
- Return clear error code: "TIMEOUT"
- Cleanup resources after timeout

**Dependencies**: US-102, US-201

**Analytics**: Track timeout_count, processing_time_distribution

---

## Acceptance Criteria (Epic Level)

- Every error scenario has specific handling
- Error messages are clear and actionable
- User knows what went wrong and what to do
- System recovers gracefully from errors
- Errors are logged for debugging
- No empty/generic error messages
- User is never left in undefined state
- Response times acceptable even with errors

## Technical Notes

- Implement custom exception classes
- All error handling should preserve user state
- Log errors with sufficient context for debugging
- Consider retry logic for transient failures
- Rate limiting considerations for YouTube API/yt-dlp
- Timeout values: subtitle extraction ~30s, formatting ~10s

## Dependencies

**Depends on**:
- Epic 1 (Core Subtitle Extraction)
- Epic 2 (Text Formatting)
- Epic 3 (Data Persistence)

## Status

**Status**: 🟡 Ready for Implementation  
**Owner**: TBD  
**Priority**: 🟠 P1 (High)
