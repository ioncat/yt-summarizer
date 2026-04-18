# Functional Requirements

## YT Summarizer - Functional Requirements

### Overview
YT Summarizer is a web application that extracts YouTube video subtitles, formats them into clean, readable text, and stores them for future analysis.

---

## Phase 1: MVP - Subtitle Extraction & Formatting

### FR-1: YouTube URL Input
**As a** user  
**I want to** submit a YouTube video URL  
**So that** I can extract its subtitles

**Acceptance Criteria**:
- Accept full YouTube URLs (https://www.youtube.com/watch?v=...)
- Validate URL format before processing
- Show clear error message for invalid URLs
- Support various YouTube URL formats (youtube.com, youtu.be, etc)

---

### FR-2: Subtitle Extraction
**As a** user  
**I want to** automatically extract subtitles from YouTube videos  
**So that** I don't have to manually copy them

**Acceptance Criteria**:
- Extract subtitles using yt-dlp without API keys
- Support multiple languages: Russian, English, Ukrainian
- Allow user to select language if multiple available
- Handle videos with no subtitles gracefully
- Show clear error message when subtitles unavailable
- Preserve 100% of original subtitle content (no omissions)

---

### FR-3: Text Formatting
**As a** user  
**I want to** receive properly formatted, readable text  
**So that** I can easily scan and understand video content

**Acceptance Criteria**:
- Remove all timestamps and formatting elements
- Convert to clean markdown format
- Proper capitalization (sentence starts with uppercase)
- Preserve all punctuation (periods, commas, exclamation marks, quotes)
- Structure text in logical paragraphs
- Preserve speaker names if available
- Handle different punctuation styles (direct/indirect speech)
- Final text reads naturally, as if typed in Word document
- NO content alterations, additions, or distortions

---

### FR-4: Database Storage
**As a** user  
**I want to** save processed subtitles  
**So that** I can access them later without re-processing

**Acceptance Criteria**:
- Store original subtitles with timestamps
- Store formatted text in markdown
- Store video metadata (title, author, duration, etc)
- Store processing metadata (language, status, timestamp)
- Allow viewing processing history
- Support deleting old records

---

### FR-5: Results Display
**As a** user  
**I want to** view extracted and formatted text  
**So that** I can quickly understand video content

**Acceptance Criteria**:
- Display formatted text in readable format
- Show video metadata (title, author, duration)
- Display extraction status
- Allow copy-to-clipboard functionality
- Show original URL and extraction timestamp
- Support different text sizes/viewing modes (if applicable)

---

### FR-6: Processing Status
**As a** user  
**I want to** see real-time processing status  
**So that** I know if my request is being processed

**Acceptance Criteria**:
- Show "Processing..." status with progress indicator
- Update UI in real-time as processing progresses
- Show "Completed" when done
- Show "Failed" with error message if something goes wrong
- Estimated time to completion (if possible)

---

### FR-7: Processing History
**As a** user  
**I want to** see all my previously processed videos  
**So that** I can quickly re-access results

**Acceptance Criteria**:
- Display list of all processed videos
- Show video title, author, processing date
- Sort by date (newest first)
- Filter by language
- Quick access to view/download results
- Pagination for large lists
- Delete individual records

---

### FR-8: Error Handling
**As a** user  
**I want to** receive clear error messages  
**So that** I understand what went wrong

**Acceptance Criteria**:
- Invalid YouTube URL → "Invalid YouTube URL. Please check and try again."
- Video has no subtitles → "This video has no subtitles available."
- Network error → "Network error. Please check your connection and try again."
- Video restricted/private → "This video is not accessible."
- Processing timeout → "Processing took too long. Please try again."
- All error messages are user-friendly and actionable

---

## Phase 2: LLM Integration & Self-Raising
*(To be detailed after Phase 1 completion)*

- Extract key points from formatted text
- Generate summaries
- Create customizable prompts
- Help users decide if video is worth watching

---

## Phase 3: Speech-to-Text Fallback
*(Architecture-ready, detailed after Phase 1+2 completion)*

- Extract audio when subtitles unavailable
- Process through local speech-to-text
- Fallback mechanism when manual subtitles missing

---

## Non-Functional Requirements

### Performance
- Subtitle extraction should complete within 30 seconds for typical videos
- UI should remain responsive during processing
- Database queries should complete within 1 second

### Reliability
- Handle network interruptions gracefully
- Automatic retry on transient failures
- Clear logging of all operations

### Usability
- Intuitive UI with clear call-to-action
- Helpful error messages
- Responsive design (works on desktop, tablet if web)

### Security
- No storage of user credentials
- No external API keys required
- Safe handling of URLs and data

### Maintainability
- Modular code structure
- Clear separation of concerns
- Comprehensive logging
- Testable components
