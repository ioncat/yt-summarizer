-- YT Summarizer - Initial Schema
-- Migration: 001
-- Created: 2024-04-18

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    video_id TEXT NOT NULL,
    title TEXT,
    author TEXT,
    duration INTEGER,
    channel_id TEXT,
    channel_name TEXT,
    upload_date TEXT,
    view_count INTEGER,
    description TEXT,
    thumbnail_url TEXT,
    language_detected TEXT,
    has_subtitles BOOLEAN,
    subtitles_type TEXT,  -- 'manual' | 'auto' | 'speech-to-text'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subtitles_raw (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    language TEXT,
    original_subtitles TEXT,  -- JSON: [{timestamp, text}, ...]
    source_type TEXT,          -- 'manual' | 'auto' | 'speech-to-text'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS subtitles_formatted (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    language TEXT,
    formatted_text TEXT,       -- Markdown
    text_length INTEGER,
    processing_status TEXT,    -- 'success' | 'error' | 'pending'
    processing_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS processing_tasks (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',  -- 'pending' | 'processing' | 'completed' | 'failed'
    progress INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
);
