# Epic 3: Data Persistence

## Summary
User can save extracted and formatted subtitles to database and retrieve them later.

## Business Value
Allows users to build a library of processed videos, reducing need to re-process same videos and enabling future analysis.

## Scope

### Included
- Store video metadata (title, author, duration, upload date, etc)
- Store raw subtitles with timestamps
- Store formatted markdown text
- Store processing metadata (language, status, timestamp)
- Retrieve previously processed videos
- View processing history
- Delete records

### Not Included
- Full-text search (future enhancement)
- Export to other formats (future enhancement)
- Sharing/collaboration features (future enhancement)
- Analytics/metrics (future enhancement)

---

## User Stories

### US-301: Save Video Metadata and Subtitles to Database

**Title**: Store video and subtitle data persistently in database

**User Story**:
```
As a backend system
I want to save video metadata and subtitles to database
So that user can retrieve them later without reprocessing
```

**Acceptance Criteria**:

**Given**: Processing complete (US-102 and US-201)

**When**: Backend saves to database

**Then**:
- Video metadata stored in `videos` table
- Raw subtitles stored in `subtitles_raw` table
- Formatted text stored in `subtitles_formatted` table
- Task status recorded in `processing_tasks` table
- All data saved atomically (all or nothing)
- Unique video_id generated and returned

**Data Stored**:
- Video: title, author, duration, language, upload_date, view_count, description, thumbnail_url
- Raw: original subtitles with timestamps, language, source_type
- Formatted: markdown text, char_count, status
- Task: task_id, status, progress, timestamps

**Edge Cases**:
1. Duplicate video URL submitted → Use existing record, update timestamp
2. Database connection fails → Return error, don't lose data
3. Very large subtitle file → Handle efficiently, no truncation
4. Special characters in metadata → Store correctly (UTF-8)

**Out of Scope**: Data encryption, backup strategy, archiving old records

**Notes for Engineering**:
- Use SQLite schema from PROJECT_PLAN.md
- Implement transaction handling
- Create indexes for common queries
- Error handling for DB constraints
- Log all DB operations
- Connection pooling if needed later

**Dependencies**: US-102, US-201

**Analytics**: Track records_saved, storage_used, db_operation_time

---

### US-302: Display Processing History

**Title**: Show user list of previously processed videos

**User Story**:
```
As a user
I want to see my processing history
So that I can quickly find and re-access previous results
```

**Acceptance Criteria**:

**Given**: User navigates to history page

**When**: History is loaded

**Then**:
- List of all processed videos displayed
- Shows: title, author, language, processing date
- Sorted by date (newest first)
- Pagination if many items (10+ per page)
- Can click to view full results
- Can delete individual entries

**And When**: User filters by language

**Then**: Only videos in selected language displayed

**Edge Cases**:
1. No history yet → Show friendly message "No videos processed yet"
2. 1000+ items → Pagination works efficiently
3. Item deleted elsewhere → Removed from display
4. Very long titles → Truncated with ellipsis, full title on hover

**Out of Scope**: Exporting history, sharing history, advanced filtering

**Notes for Engineering**:
- Backend endpoint: `GET /api/history?page=1&language=ru`
- Frontend pagination component
- Lazy load for performance
- Show loading state while fetching
- Error handling for query failures

**Dependencies**: US-301

**Analytics**: Track history_viewed, items_per_page, filters_used

---

### US-303: Retrieve Previously Processed Videos

**Title**: Fetch full details of previously processed video

**User Story**:
```
As a user
I want to retrieve my previously processed videos
So that I can review the formatted text again
```

**Acceptance Criteria**:

**Given**: User clicks on history item

**When**: Video details fetched from database

**Then**:
- Full formatted text retrieved
- Video metadata displayed
- Extraction timestamp shown
- Can copy text
- Can delete record
- Information loads quickly

**Edge Cases**:
1. Record deleted by user → Show "Not found"
2. Multiple same URLs with different languages → Show all versions
3. Database connection fails → Retry with user notification
4. File too large → Load in chunks if needed

**Out of Scope**: Editing stored data, merging duplicates

**Notes for Engineering**:
- Backend endpoint: `GET /api/result/{video_id}`
- Query should include: videos, subtitles_raw, subtitles_formatted tables
- Caching strategy for frequently accessed items
- Error handling for missing records

**Dependencies**: US-301

**Analytics**: Track result_retrieved, result_view_time

---

### US-304: Delete Old Records from Database

**Title**: Allow user to delete records from database

**User Story**:
```
As a user
I want to delete old records
So that I can manage my storage and privacy
```

**Acceptance Criteria**:

**Given**: User views history or result page

**When**: User clicks delete button

**Then**:
- Confirmation dialog shown (prevent accidental deletion)
- Record deleted from all tables
- History updated
- User sees confirmation message

**Edge Cases**:
1. Delete fails → Show error message, allow retry
2. Record already deleted → Show "Already deleted"
3. Large deletion → Handle efficiently, no long loading

**Out of Scope**: Batch deletion, scheduled deletion, soft deletes

**Notes for Engineering**:
- Backend endpoint: `DELETE /api/result/{video_id}`
- Implement confirmation on frontend
- Delete from all related tables atomically
- Soft delete option for future compliance needs
- Log deletions for audit trail

**Dependencies**: US-301, US-303

**Analytics**: Track record_deleted, reason_if_available

---

## Acceptance Criteria (Epic Level)

- All relevant data stored in structured format (SQLite)
- Metadata includes: title, author, duration, language, URL, processing date
- Both raw and formatted subtitles stored
- User can retrieve any previously processed video
- User can view history with pagination
- User can delete records
- Database queries perform efficiently (< 1 second)
- Data integrity maintained (no corruption, loss)

## Technical Notes

- Database: SQLite (MVP)
- Schema defined in PROJECT_PLAN.md
- Tables: videos, subtitles_raw, subtitles_formatted, processing_tasks
- Consider future migration path to PostgreSQL
- Implement proper indexes for query performance
- Consider backup strategy for user data

## Dependencies

**Depends on**: 
- Epic 1 (Core Subtitle Extraction)
- Epic 2 (Text Formatting)

## Status

**Status**: 🟡 Ready for Implementation  
**Owner**: TBD  
**Priority**: 🔴 P0 (Critical)
