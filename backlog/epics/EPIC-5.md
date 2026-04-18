# Epic 5: Web User Interface

## Summary
User can interact with YT Summarizer through an intuitive, responsive web interface.

## Business Value
Provides accessible entry point to the application. Good UX reduces friction and encourages usage.

## Scope

### Included
- Home page with URL input form
- Real-time processing status display
- Results display with formatted text
- Processing history view with filtering and pagination
- Basic settings (language selection, preferences)
- Copy-to-clipboard functionality
- Responsive design
- Clear visual feedback for all states

### Not Included
- Mobile native app (future)
- Advanced settings/configuration (future)
- User authentication/accounts (future)
- Sharing/collaboration UI (future)
- Export to PDF/DOCX (future, handled in backend first)

---

## User Stories

### US-501: Create Home Page with URL Input

**Title**: Build home page with YouTube URL input form

**User Story**:
```
As a user
I want to see a clean, simple home page
So that I can easily submit a YouTube URL
```

**Acceptance Criteria**:

**Given**: User opens application

**When**: Home page loads

**Then**:
- Title/logo visible: "YT Summarizer"
- Clear tagline: "Extract YouTube subtitles quickly"
- URL input field prominent and ready for input
- "Process" button clearly visible
- Instructions visible (one sentence)
- Links to history and settings if applicable

**Visual Elements**:
- Clean, minimal design
- Input field has placeholder: "Paste YouTube URL..."
- Button is prominent (good contrast)
- Mobile responsive
- Good spacing and typography

**Edge Cases**:
1. Page loads slowly → Loading spinner
2. Autofill attempts → Handle gracefully
3. Mobile → Single column layout
4. Very narrow screens → Responsive stacking

**Out of Scope**: User authentication, branding/theming options

**Notes for Engineering**:
- React component: HomePage
- TypeScript for type safety
- Responsive CSS (mobile-first)
- Accessibility: proper labels, ARIA attributes
- Focus management
- No external dependencies for basic form

**Dependencies**: None (foundational UI)

**Analytics**: Track page_views, input_focus

---

### US-502: Display Processing Status and Progress

**Title**: Show user real-time processing status

**User Story**:
```
As a user
I want to see what's happening while processing
So that I know the app is working and what to expect
```

**Acceptance Criteria**:

**Given**: User submitted URL

**When**: Processing begins

**Then**:
- Status page shows immediately
- Shows: "Processing..." with spinner
- Task ID visible (for reference)
- Progress updates in real-time
- Estimated time shown if available
- User can see what's being done (extracting → formatting → saving)

**Status States**:
1. Pending → "Starting..."
2. Processing → "Extracting subtitles..." → "Formatting text..." → "Saving..."
3. Completed → Show results
4. Failed → Show error message

**Edge Cases**:
1. Processing takes 30+ seconds → Show realistic progress
2. User navigates away → State preserved (can return)
3. Status doesn't update → Show "Waiting..." with retry

**Out of Scope**: Detailed progress percentage (if not available), sound notifications

**Notes for Engineering**:
- Frontend polls `/api/status/{task_id}` every 1-2 seconds
- Or use WebSocket for real-time updates (future)
- Show spinner/loading animation
- Update status message based on backend response
- Cache task_id in localStorage
- Show estimated completion time

**Dependencies**: US-101 (URL submission)

**Analytics**: Track status_checks, processing_time, completion_rate

---

### US-503: Show Formatted Text Results

**Title**: Display extracted and formatted text to user

**User Story**:
```
As a user
I want to see the formatted text results
So that I can read and interact with the content
```

**Acceptance Criteria**:

**Given**: Processing completed successfully

**When**: Results page displays

**Then**:
- Formatted text displayed prominently
- Text is readable with good typography
- Video metadata shown (title, author, duration)
- Extraction timestamp shown
- Copy-to-clipboard button available
- Can select and copy text
- Responsive on all devices

**Layout**:
- Header: Video title, author
- Metadata: Duration, language, extraction time
- Content: Formatted text in readable format
- Actions: Copy, Share (if available), Delete, New Search

**Edge Cases**:
1. Very long text → Loads without lag, smooth scrolling
2. Special characters → Display correctly (emoji, Cyrillic, etc)
3. Mobile → Readable without zooming
4. Dark mode → Text still readable

**Out of Scope**: Text editing, comments, annotations

**Notes for Engineering**:
- React component: ResultsDisplay
- Use markdown renderer (react-markdown)
- Implement copy-to-clipboard (navigator.clipboard API)
- Show toast/notification on copy success
- Responsive CSS, mobile-optimized
- Lazy load for very long texts

**Dependencies**: US-102 (extraction), US-201 (formatting)

**Analytics**: Track results_viewed, copy_clicked, view_duration

---

### US-504: Show Processing History

**Title**: Display user's processing history with easy access

**User Story**:
```
As a user
I want to see all my previously processed videos
So that I can quickly re-access them
```

**Acceptance Criteria**:

**Given**: User navigates to History page

**When**: History loads

**Then**:
- List of all processed videos displayed
- Shows: title, author, language, processing date
- Sorted by date (newest first)
- Pagination if many items (10+ per page)
- Can click to view full results
- Can delete individual entries
- Can filter by language

**Layout**:
- Table or card view of videos
- Each item shows: Thumbnail (if available), Title, Author, Language, Date
- Actions: View, Delete
- Filter dropdown: All, Russian, English, Ukrainian
- Pagination controls

**Edge Cases**:
1. No history yet → "No videos processed yet. Get started!"
2. 1000+ items → Pagination works efficiently
3. Item title very long → Truncate with ellipsis
4. Slow loading → Show skeleton loaders

**Out of Scope**: Exporting history, sharing, advanced search

**Notes for Engineering**:
- React component: HistoryPage
- Fetch data from `/api/history?page=1&language=`
- Implement pagination component
- Show loading state
- Error handling if fetch fails
- Filter dropdown triggers new fetch
- Show total count of items

**Dependencies**: US-301 (data storage), US-302 (backend endpoint)

**Analytics**: Track history_viewed, filters_used, items_clicked

---

### US-505: Add Basic Settings (Language Selection)

**Title**: Allow user to configure language preferences

**User Story**:
```
As a user
I want to set my preferred language
So that the interface works in my preferred language
```

**Acceptance Criteria**:

**Given**: User navigates to Settings

**When**: Settings page loads

**Then**:
- Language selection dropdown available
- Options: Russian, English, Ukrainian
- Current selection highlighted
- Can change selection
- Preference saved locally
- Interface updates on change

**Settings Options**:
- Default subtitle language (if multiple available)
- UI language (for future multi-language UI)
- Theme (if applicable)

**Edge Cases**:
1. Browser language detected → Set as default
2. Settings reset → Restore defaults
3. Invalid setting → Fallback to English

**Out of Scope**: Advanced user accounts, syncing across devices, privacy settings

**Notes for Engineering**:
- React component: SettingsPage
- Use localStorage for preferences
- Update state globally when language changes
- Minimal settings for MVP
- Easy to expand later

**Dependencies**: None

**Analytics**: Track settings_changed, language_selections

---

## Acceptance Criteria (Epic Level)

- Homepage is clear and intuitive
- Users can submit URL with single click
- Processing status visible in real-time
- Results display cleanly and readably
- History is accessible and filterable
- All key actions discoverable without explanation
- Responsive on desktop/tablet browsers
- Error messages displayed prominently
- Loading states clear and informative
- No broken links or missing functionality

## Technical Notes

- Frontend: React + TypeScript
- Component structure defined in PROJECT_PLAN.md
- Use responsive design (Flexbox/Grid)
- Implement loading states, error states, success states
- Copy-to-clipboard for formatted text
- Consider accessibility (ARIA labels, keyboard navigation)
- Performance: page loads quickly, interactions responsive

## Dependencies

**Depends on**:
- Epic 1 (Core Subtitle Extraction)
- Epic 2 (Text Formatting)
- Epic 3 (Data Persistence)
- Epic 4 (Error Handling)

## Status

**Status**: 🟡 Ready for Implementation  
**Owner**: TBD  
**Priority**: 🔴 P0 (Critical)
