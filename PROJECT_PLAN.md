# YT Summarizer - Project Plan

## 1. Vision & Motivation

**Problem**: Users waste time on YouTube videos that might not be relevant to them. They need a way to quickly understand what a video contains without watching it entirely.

**Solution**: YT Summarizer extracts and formats video subtitles into clean, readable text, allowing users to:
- Scan video content quickly before committing to watching
- Reduce cognitive load and save time
- Have properly formatted transcript for reference
- Later analyze key points using AI/LLM (future phase)

**Goal**: Create a tool that respects the original content completely while making it accessible and readable.

---

## 2. Product Goals

### Phase 1: MVP - Subtitle Extraction & Formatting
1. Extract subtitles from YouTube videos via URL
2. Format subtitles into clean, properly-punctuated text
3. Preserve 100% of original content (no alterations, additions, or omissions)
4. Store in database with metadata
5. Display results in web interface

### Phase 2: Self-Raising / LLM Integration
- Extract key points and summaries using LLM
- Create customizable prompts for different summarization styles
- Help users decide if video is worth watching in detail

### Phase 3: Speech-to-Text Fallback (Architecture-ready)
- Extract audio when subtitles unavailable
- Process through local speech-to-text model
- Fallback when manual subtitles don't exist

---

## 3. Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React + TypeScript |
| **Backend** | Python + FastAPI |
| **Video Processing** | yt-dlp |
| **Database** | SQLite |
| **Text Storage Format** | Markdown (in DB) |
| **LLM Integration** | (TBD - Phase 2) |

---

## 4. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│              React Web UI (TypeScript)              │
│  - URL Input Form                                   │
│  - Results Display                                  │
│  - History/Database Browser                         │
│  - Settings (Language Selection, etc)               │
└────────────────────┬────────────────────────────────┘
                     │ HTTP/JSON
                     ↓
┌─────────────────────────────────────────────────────┐
│            FastAPI Backend (Python)                 │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │ API Routes                                  │   │
│  │ - POST /api/process (submit YouTube URL)    │   │
│  │ - GET /api/results/{id}                     │   │
│  │ - GET /api/history                          │   │
│  │ - GET /api/status/{task_id}                 │   │
│  └─────────────────────────────────────────────┘   │
│                      ↓                              │
│  ┌─────────────────────────────────────────────┐   │
│  │ Subtitle Extraction Service                 │   │
│  │ - yt-dlp integration                        │   │
│  │ - Language selection                        │   │
│  │ - Error handling                            │   │
│  └─────────────────────────────────────────────┘   │
│                      ↓                              │
│  ┌─────────────────────────────────────────────┐   │
│  │ Text Formatting Service                     │   │
│  │ - Remove timestamps/formatting              │   │
│  │ - Proper capitalization & punctuation       │   │
│  │ - Structure as readable paragraphs          │   │
│  │ - Export as Markdown                        │   │
│  └─────────────────────────────────────────────┘   │
│                      ↓                              │
│  ┌─────────────────────────────────────────────┐   │
│  │ Database Service                            │   │
│  │ - Store original subtitles                  │   │
│  │ - Store formatted text                      │   │
│  │ - Manage metadata                           │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────┐
│            SQLite Database                          │
│  - Videos table                                     │
│  - Subtitles table                                  │
│  - Processed results table                          │
└─────────────────────────────────────────────────────┘
```

**Design Principle**: Loose coupling between services allows easy addition of speech-to-text processor later without major refactoring.

---

## 5. Database Schema

### videos
```sql
CREATE TABLE videos (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    video_id TEXT NOT NULL,
    title TEXT,
    author TEXT,
    duration INTEGER,  -- seconds
    channel_id TEXT,
    channel_name TEXT,
    upload_date TEXT,  -- ISO format
    view_count INTEGER,
    description TEXT,
    thumbnail_url TEXT,
    language_detected TEXT,
    has_subtitles BOOLEAN,
    subtitles_type TEXT,  -- 'manual', 'auto', 'speech-to-text'
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### subtitles_raw
```sql
CREATE TABLE subtitles_raw (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    language TEXT,  -- 'ru', 'en', 'uk'
    original_subtitles TEXT,  -- JSON array of {timestamp, text}
    source_type TEXT,  -- 'manual', 'auto', 'speech-to-text'
    created_at TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
```

### subtitles_formatted
```sql
CREATE TABLE subtitles_formatted (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    language TEXT,
    formatted_text TEXT,  -- Markdown format
    text_length INTEGER,  -- character count
    processing_status TEXT,  -- 'success', 'error', 'pending'
    processing_error TEXT,  -- error message if failed
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
```

### processing_tasks
```sql
CREATE TABLE processing_tasks (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    status TEXT,  -- 'pending', 'processing', 'completed', 'failed'
    progress INTEGER,  -- 0-100
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
```

---

## 6. API Design (FastAPI)

### Base URL
```
http://localhost:8000/api
```

### Endpoints

#### POST /process
**Submit YouTube video for processing**
```json
Request:
{
  "url": "https://www.youtube.com/watch?v=...",
  "language": "ru"  // or "en", "uk"
}

Response (202 Accepted):
{
  "task_id": "task_123abc",
  "video_id": "vid_456def",
  "status": "processing",
  "message": "Processing started"
}
```

#### GET /status/{task_id}
**Check processing status**
```json
Response:
{
  "task_id": "task_123abc",
  "status": "processing",  // or "completed", "failed"
  "progress": 75,
  "video_id": "vid_456def",
  "message": "Extracting and formatting subtitles..."
}
```

#### GET /result/{video_id}
**Retrieve processed result**
```json
Response (200 OK):
{
  "video_id": "vid_456def",
  "title": "Video Title",
  "author": "Author Name",
  "language": "ru",
  "formatted_text": "# Markdown formatted text...",
  "original_subtitles": [{"timestamp": "00:00:10", "text": "..."}, ...],
  "created_at": "2024-04-18T10:30:00Z"
}
```

#### GET /history
**Get processing history**
```json
Response:
{
  "items": [
    {
      "video_id": "vid_123",
      "url": "https://...",
      "title": "Video Title",
      "status": "completed",
      "language": "ru",
      "created_at": "2024-04-18T10:30:00Z"
    }
  ],
  "total": 15,
  "page": 1,
  "per_page": 10
}
```

#### DELETE /result/{video_id}
**Delete processing result from database**
```json
Response:
{
  "status": "deleted",
  "video_id": "vid_456def"
}
```

---

## 7. Frontend Structure (React + TypeScript)

```
src/
├── components/
│   ├── UrlInput/
│   │   └── UrlInput.tsx
│   ├── ProcessingStatus/
│   │   └── ProcessingStatus.tsx
│   ├── ResultDisplay/
│   │   └── ResultDisplay.tsx
│   ├── History/
│   │   └── History.tsx
│   └── Settings/
│       └── Settings.tsx
├── pages/
│   ├── Home.tsx
│   └── History.tsx
├── services/
│   ├── api.ts
│   └── storage.ts
├── types/
│   └── index.ts
├── hooks/
│   ├── useProcessing.ts
│   └── useHistory.ts
├── App.tsx
└── index.tsx
```

---

## 8. Backend Structure (FastAPI + Python)

```
backend/
├── main.py
├── requirements.txt
├── config.py
├── models/
│   ├── __init__.py
│   └── database.py
├── routes/
│   ├── __init__.py
│   ├── process.py
│   ├── status.py
│   └── history.py
├── services/
│   ├── __init__.py
│   ├── subtitle_extractor.py
│   ├── text_formatter.py
│   ├── database_service.py
│   └── task_manager.py
├── utils/
│   ├── __init__.py
│   ├── validation.py
│   ├── error_handlers.py
│   └── logging.py
├── db/
│   ├── __init__.py
│   ├── database.py
│   └── migrations/
└── tests/
    ├── __init__.py
    ├── test_subtitle_extractor.py
    ├── test_text_formatter.py
    └── test_api.py
```

---

## 9. Development Phases

### Phase 1: MVP - Subtitle Extraction & Formatting
**Duration**: 2-3 weeks (estimated)

**Milestones**:
1. ✅ Backend setup (FastAPI, SQLite)
   - Initialize project structure
   - Database schema creation
   - Basic API endpoints

2. ✅ Subtitle extraction (yt-dlp integration)
   - Extract subtitles from YouTube URLs
   - Support multiple languages (ru, en, uk)
   - Error handling for invalid URLs and missing subtitles

3. ✅ Text formatting service
   - Remove timestamps and formatting elements
   - Proper capitalization and punctuation
   - Structure as readable markdown
   - Preserve 100% of original content

4. ✅ Database integration
   - Store raw subtitles
   - Store formatted text with metadata
   - Query and retrieve results

5. ✅ Frontend UI
   - URL input form
   - Processing status display
   - Results display (formatted text)
   - History view

6. ✅ Error handling
   - Invalid URLs
   - Missing subtitles
   - Network errors
   - Clear error messages to user

**Definition of Done**:
- Can submit YouTube URL
- Subtitles extracted and formatted correctly
- Text stored in database
- Results displayed in UI
- Error messages are clear and helpful
- Manual testing successful

---

### Phase 2: Self-Raising / LLM Integration
**Duration**: TBD
**Depends on**: Phase 1 completion

**Features**:
- LLM integration (local or external)
- Prompt customization
- Summary generation
- Key points extraction
- Testing and prompt optimization

---

### Phase 3: Speech-to-Text Fallback
**Duration**: TBD
**Depends on**: Phase 1 + 2 completion

**Features**:
- Audio extraction from video
- Local speech-to-text processing
- Fallback when subtitles unavailable
- Unified processing pipeline

---

## 10. Critical Success Criteria

### Phase 1 (MVP)
- [ ] Subtitle extraction works for ru, en, uk languages
- [ ] Formatted text matches 100% of subtitle content
- [ ] No content distortion, alteration, or loss
- [ ] Proper markdown formatting (capitals, punctuation, structure)
- [ ] Database stores and retrieves data correctly
- [ ] Web UI functional and user-friendly
- [ ] Clear error messages for edge cases
- [ ] Code is modular (easy to extend for Phase 3)

### General
- [ ] All code in Git with meaningful commits
- [ ] Documentation updated throughout
- [ ] Manual testing for golden path and edge cases

---

## 11. Future Considerations

- **Batch processing**: Process multiple URLs at once
- **Export formats**: PDF, DOCX, plain text (not just markdown)
- **Search**: Full-text search in processed subtitles
- **Sharing**: Generate shareable links for results
- **Quality metrics**: Track accuracy of formatting
- **Performance**: Caching, async processing, queue system
- **Scalability**: Move from SQLite to PostgreSQL if needed

---

## 12. Notes for Development

1. **Test with real YouTube videos** throughout development
2. **Preserve original spacing and line breaks** where possible
3. **Document any edge cases** found during development
4. **Keep frontend/backend loosely coupled** for flexibility
5. **Log all processing steps** for debugging
6. **Use async processing** for long-running subtitle extraction
