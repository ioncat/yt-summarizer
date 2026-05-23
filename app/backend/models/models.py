import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base


def generate_id() -> str:
    return str(uuid.uuid4())


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    url: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    video_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String)
    author: Mapped[str | None] = mapped_column(String)
    duration: Mapped[int | None] = mapped_column(Integer)
    channel_id: Mapped[str | None] = mapped_column(String)
    channel_name: Mapped[str | None] = mapped_column(String)
    upload_date: Mapped[str | None] = mapped_column(String)
    view_count: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(String)
    chapters: Mapped[list | None] = mapped_column(JSON)  # [{start_time, end_time, title}, ...]
    language_detected: Mapped[str | None] = mapped_column(String)
    has_subtitles: Mapped[bool | None] = mapped_column(Boolean)
    subtitles_type: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    subtitles_raw: Mapped[list["SubtitleRaw"]] = relationship(back_populates="video")
    subtitles_formatted: Mapped[list["SubtitleFormatted"]] = relationship(
        back_populates="video"
    )
    tasks: Mapped[list["ProcessingTask"]] = relationship(back_populates="video")


class SubtitleRaw(Base):
    __tablename__ = "subtitles_raw"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), nullable=False)
    language: Mapped[str | None] = mapped_column(String)
    original_subtitles: Mapped[str | None] = mapped_column(Text)  # JSON array
    source_type: Mapped[str | None] = mapped_column(String)  # manual | auto | speech-to-text
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    video: Mapped["Video"] = relationship(back_populates="subtitles_raw")


class SubtitleFormatted(Base):
    __tablename__ = "subtitles_formatted"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), nullable=False)
    language: Mapped[str | None] = mapped_column(String)
    formatted_text: Mapped[str | None] = mapped_column(Text)  # Markdown
    cleaned_text: Mapped[str | None] = mapped_column(Text)    # LLM-cleaned version
    cleanup_status: Mapped[str | None] = mapped_column(String(20))  # null | processing | done | failed
    cleanup_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    cleanup_finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    cleanup_model: Mapped[str | None] = mapped_column(String)
    summary_text: Mapped[str | None] = mapped_column(Text)
    summary_status: Mapped[str | None] = mapped_column(String(20))
    summary_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    summary_finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    summary_model: Mapped[str | None] = mapped_column(String)
    summary_mode: Mapped[str | None] = mapped_column(String(20))   # single | map_reduce
    summary_chunks_count: Mapped[int | None] = mapped_column(Integer)
    text_length: Mapped[int | None] = mapped_column(Integer)
    mindmap_text: Mapped[str | None] = mapped_column(Text)    # LLM-generated compact mindmap markdown
    mindmap_status: Mapped[str | None] = mapped_column(String(20))  # null | processing | done | failed
    chat_history: Mapped[list | None] = mapped_column(JSON)  # [{role, content}, ...]
    processing_status: Mapped[str | None] = mapped_column(String)  # success | error | pending
    processing_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    video: Mapped["Video"] = relationship(back_populates="subtitles_formatted")


class PipelineSettings(Base):
    __tablename__ = "pipeline_settings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # cleanup | summarization
    system_prompt: Mapped[str | None] = mapped_column(Text)
    user_prompt_template: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AppSetting(Base):
    """Key-value store for application-level settings (Ollama URL, paths, etc.)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ProcessingTask(Base):
    __tablename__ = "processing_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | processing | completed | failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    video: Mapped["Video"] = relationship(back_populates="tasks")


class BenchmarkRun(Base):
    """One model's result in a benchmark comparison run."""
    __tablename__ = "benchmark_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)   # 'summary'
    mode: Mapped[str] = mapped_column(String(20), nullable=False)    # 'single' | 'map_reduce' | 'full_extract'
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    output_text: Mapped[str | None] = mapped_column(Text)
    output_chars: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing | done | failed
    # 'main' = mirrored from primary cleanup/summary pipeline (Result page action)
    # 'benchmark' = created by an explicit Benchmark run
    triggered_by: Mapped[str] = mapped_column(String(20), default="benchmark")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
