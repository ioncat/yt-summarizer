from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Video, SubtitleRaw, SubtitleFormatted, ProcessingTask, PipelineSettings, AppSetting
from models.models import generate_id
from services.text_cleaner import DEFAULT_SYSTEM_PROMPT, DEFAULT_USER_PROMPT_TEMPLATE
from services.text_summarizer import (
    DEFAULT_SYSTEM_PROMPT as DEFAULT_SUMMARY_SYSTEM_PROMPT,
    DEFAULT_USER_PROMPT_TEMPLATE as DEFAULT_SUMMARY_USER_PROMPT_TEMPLATE,
    DEFAULT_MAP_SYSTEM_PROMPT,
    DEFAULT_MAP_USER_PROMPT,
    DEFAULT_REDUCE_SYSTEM_PROMPT,
    DEFAULT_REDUCE_USER_PROMPT,
)

# ---------------------------------------------------------------------------
# Pipeline settings — defaults (source of truth is text_cleaner/text_summarizer constants)
# Model has no default: user must select one via the web Settings page.
# ---------------------------------------------------------------------------

STAGE_DEFAULTS: dict[str, dict] = {
    "cleanup": {
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "user_prompt_template": DEFAULT_USER_PROMPT_TEMPLATE,
        "model": None,
    },
    "summarization": {
        "system_prompt": DEFAULT_SUMMARY_SYSTEM_PROMPT,
        "user_prompt_template": DEFAULT_SUMMARY_USER_PROMPT_TEMPLATE,
        "model": None,
    },
    "summarization_extract": {
        "system_prompt": DEFAULT_MAP_SYSTEM_PROMPT,
        "user_prompt_template": DEFAULT_MAP_USER_PROMPT,
        "model": None,
    },
    "summarization_combine": {
        "system_prompt": DEFAULT_REDUCE_SYSTEM_PROMPT,
        "user_prompt_template": DEFAULT_REDUCE_USER_PROMPT,
        "model": None,
    },
}
from services.subtitle_extractor import ExtractionResult, subtitles_to_json


async def create_pending_task(db: AsyncSession, url: str, video_id: str) -> ProcessingTask:
    # Return existing in-progress task to avoid double-processing
    stmt = (
        select(ProcessingTask)
        .join(Video, ProcessingTask.video_id == Video.id)
        .where(Video.video_id == video_id, ProcessingTask.status == "pending")
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing

    # Clean up stale __pending__ video left over from a previous failed task
    stale_stmt = select(Video).where(Video.url == f"__pending__{video_id}")
    stale_video = (await db.execute(stale_stmt)).scalar_one_or_none()
    if stale_video:
        await db.execute(delete(ProcessingTask).where(ProcessingTask.video_id == stale_video.id))
        await db.delete(stale_video)
        await db.flush()

    video = Video(
        id=generate_id(),
        url=f"__pending__{video_id}",
        video_id=video_id,
    )
    db.add(video)
    await db.flush()

    task = ProcessingTask(
        id=generate_id(),
        video_id=video.id,
        status="pending",
        progress=0,
        started_at=datetime.utcnow(),
    )
    db.add(task)
    await db.commit()
    return task


async def complete_task(
    db: AsyncSession,
    task_id: str,
    url: str,
    extraction_result: ExtractionResult,
    formatted: dict,
) -> None:
    # Find pending task and its placeholder video
    task_stmt = select(ProcessingTask).where(ProcessingTask.id == task_id)
    task = (await db.execute(task_stmt)).scalar_one_or_none()
    if not task:
        return

    video_stmt = select(Video).where(Video.id == task.video_id)
    video = (await db.execute(video_stmt)).scalar_one_or_none()
    if not video:
        return

    # If a completed video with same video_id exists, reuse it and discard the placeholder
    dup_stmt = select(Video).where(Video.video_id == extraction_result.metadata.video_id, Video.id != video.id)
    dup = (await db.execute(dup_stmt)).scalars().first()
    if dup and dup.id != video.id:
        # Reassign task to existing video first, flush so FK points away from placeholder
        task.video_id = dup.id
        await db.flush()
        # Now safe to delete the placeholder
        await db.delete(video)
        await db.flush()
        video = dup

    # Update placeholder video with real metadata
    m = extraction_result.metadata
    video.url = url
    video.video_id = m.video_id
    video.title = m.title
    video.author = m.author
    video.duration = m.duration
    video.channel_id = m.channel_id
    video.channel_name = m.channel_name
    video.upload_date = m.upload_date
    video.view_count = m.view_count
    video.description = m.description
    video.thumbnail_url = m.thumbnail_url
    video.language_detected = extraction_result.language
    video.has_subtitles = True
    video.subtitles_type = extraction_result.source_type.value if extraction_result.source_type else None
    video.chapters = extraction_result.metadata.chapters

    db.add(SubtitleRaw(
        id=generate_id(),
        video_id=video.id,
        language=extraction_result.language,
        original_subtitles=subtitles_to_json(extraction_result.subtitles),
        source_type=extraction_result.source_type.value if extraction_result.source_type else None,
    ))

    db.add(SubtitleFormatted(
        id=generate_id(),
        video_id=video.id,
        language=extraction_result.language,
        formatted_text=formatted["formatted_text"],
        text_length=formatted["char_count"],
        processing_status="success",
    ))

    task.status = "completed"
    task.progress = 100
    task.completed_at = datetime.utcnow()

    await db.commit()


async def update_task_failed(
    db: AsyncSession, task_id: str, error: str, available_languages: list[str] | None = None
) -> None:
    stmt = select(ProcessingTask).where(ProcessingTask.id == task_id)
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task:
        task.status = "failed"
        task.error_message = (
            json.dumps({"message": error, "available_languages": available_languages})
            if available_languages is not None
            else error
        )
        task.completed_at = datetime.utcnow()
        await db.commit()


async def get_task(db: AsyncSession, task_id: str) -> ProcessingTask | None:
    stmt = select(ProcessingTask).where(ProcessingTask.id == task_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_result(db: AsyncSession, video_id: str) -> dict | None:
    stmt = select(Video).where(Video.video_id == video_id, ~Video.url.startswith("__pending__"))
    video = (await db.execute(stmt)).scalars().first()
    if not video:
        return None

    fmt_stmt = (
        select(SubtitleFormatted)
        .where(SubtitleFormatted.video_id == video.id)
        .order_by(SubtitleFormatted.created_at.desc())
    )
    fmt = (await db.execute(fmt_stmt)).scalars().first()

    def _duration(finished, started):
        if finished and started:
            return int((finished - started).total_seconds())
        return None

    return {
        "video_id": video.video_id,
        "url": video.url,
        "title": video.title,
        "author": video.author,
        "duration": video.duration,
        "language": fmt.language if fmt else None,
        "formatted_text": fmt.formatted_text if fmt else None,
        "cleaned_text": fmt.cleaned_text if fmt else None,
        "cleanup_status": fmt.cleanup_status if fmt else None,
        "cleanup_model": fmt.cleanup_model if fmt else None,
        "cleanup_duration_seconds": _duration(
            fmt.cleanup_finished_at if fmt else None,
            fmt.cleanup_started_at if fmt else None,
        ),
        "summary_text": fmt.summary_text if fmt else None,
        "summary_status": fmt.summary_status if fmt else None,
        "summary_model": fmt.summary_model if fmt else None,
        "summary_mode": fmt.summary_mode if fmt else None,
        "summary_chunks_count": fmt.summary_chunks_count if fmt else None,
        "summary_duration_seconds": _duration(
            fmt.summary_finished_at if fmt else None,
            fmt.summary_started_at if fmt else None,
        ),
        "char_count": fmt.text_length if fmt else None,
        "chapters": video.chapters,
        "created_at": video.created_at.isoformat(),
    }


async def get_history(db: AsyncSession, page: int = 1, page_size: int = 20) -> dict:
    offset = (page - 1) * page_size
    stmt = (
        select(Video)
        .where(~Video.url.startswith("__pending__"))
        .order_by(Video.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items = []
    for v in rows:
        fmt_stmt = (
            select(SubtitleFormatted)
            .where(SubtitleFormatted.video_id == v.id)
            .order_by(SubtitleFormatted.created_at.desc())
        )
        fmt = (await db.execute(fmt_stmt)).scalars().first()
        items.append({
            "video_id": v.video_id,
            "title": v.title,
            "author": v.author,
            "language": v.language_detected,
            "char_count": fmt.text_length if fmt else None,
            "created_at": v.created_at.isoformat(),
        })

    return {"page": page, "items": items}


async def get_formatted_subtitle(db: AsyncSession, video_id: str) -> SubtitleFormatted | None:
    """Return the latest SubtitleFormatted row for a video_id."""
    stmt = (
        select(Video)
        .where(Video.video_id == video_id, ~Video.url.startswith("__pending__"))
    )
    video = (await db.execute(stmt)).scalars().first()
    if not video:
        return None
    fmt_stmt = (
        select(SubtitleFormatted)
        .where(SubtitleFormatted.video_id == video.id)
        .order_by(SubtitleFormatted.created_at.desc())
    )
    return (await db.execute(fmt_stmt)).scalars().first()


async def _get_fmt_id(db: AsyncSession, video_id: str) -> str | None:
    """Return the subtitles_formatted.id for a video_id, or None."""
    result = await db.execute(
        text("""
            SELECT sf.id FROM subtitles_formatted sf
            JOIN videos v ON sf.video_id = v.id
            WHERE v.video_id = :vid AND v.url NOT LIKE '__pending__%'
            ORDER BY sf.created_at DESC LIMIT 1
        """),
        {"vid": video_id},
    )
    row = result.first()
    return row[0] if row else None


async def set_cleanup_processing(db: AsyncSession, video_id: str, model: str | None = None) -> bool:
    """Mark cleanup as in progress. Returns False if record not found."""
    fmt_id = await _get_fmt_id(db, video_id)
    if not fmt_id:
        return False
    await db.execute(
        text("""
            UPDATE subtitles_formatted
            SET cleanup_status = 'processing',
                cleanup_model = :model,
                cleanup_started_at = :ts,
                cleanup_finished_at = NULL
            WHERE id = :id
        """),
        {"model": model, "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"), "id": fmt_id},
    )
    await db.commit()
    return True


async def finish_cleanup(db: AsyncSession, video_id: str, cleaned_text: str | None) -> None:
    """Store cleanup result and update status."""
    fmt_id = await _get_fmt_id(db, video_id)
    if not fmt_id:
        return
    status = "done" if cleaned_text else "failed"
    await db.execute(
        text("""
            UPDATE subtitles_formatted
            SET cleanup_status = :status,
                cleaned_text = :cleaned,
                cleanup_finished_at = :ts
            WHERE id = :id
        """),
        {"status": status, "cleaned": cleaned_text, "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"), "id": fmt_id},
    )
    await db.commit()


async def reset_cleanup_status(db: AsyncSession, video_id: str) -> None:
    """Reset cleanup status to null (used after cancellation)."""
    fmt_id = await _get_fmt_id(db, video_id)
    if not fmt_id:
        return
    await db.execute(
        text("""
            UPDATE subtitles_formatted
            SET cleanup_status = NULL,
                cleanup_started_at = NULL,
                cleanup_finished_at = NULL
            WHERE id = :id
        """),
        {"id": fmt_id},
    )
    await db.commit()


async def set_summary_processing(db: AsyncSession, video_id: str, model: str | None = None) -> bool:
    """Mark summarization as in progress. Returns False if record not found."""
    fmt_id = await _get_fmt_id(db, video_id)
    if not fmt_id:
        return False
    await db.execute(
        text("""
            UPDATE subtitles_formatted
            SET summary_status = 'processing',
                summary_text = NULL,
                summary_model = :model,
                summary_started_at = :ts,
                summary_finished_at = NULL
            WHERE id = :id
        """),
        {"model": model, "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"), "id": fmt_id},
    )
    await db.commit()
    return True


async def finish_summary(
    db: AsyncSession,
    video_id: str,
    summary_text: str | None,
    mode: str = "single",
    chunks_count: int = 1,
) -> None:
    """Store summarization result and update status."""
    fmt_id = await _get_fmt_id(db, video_id)
    if not fmt_id:
        return
    status = "done" if summary_text else "failed"
    await db.execute(
        text("""
            UPDATE subtitles_formatted
            SET summary_status = :status,
                summary_text = :summary,
                summary_mode = :mode,
                summary_chunks_count = :chunks,
                summary_finished_at = :ts
            WHERE id = :id
        """),
        {
            "status": status,
            "summary": summary_text,
            "mode": mode,
            "chunks": chunks_count,
            "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "id": fmt_id,
        },
    )
    await db.commit()


async def reset_summary_status(db: AsyncSession, video_id: str) -> None:
    """Reset summary status to null (used after cancellation)."""
    fmt_id = await _get_fmt_id(db, video_id)
    if not fmt_id:
        return
    await db.execute(
        text("""
            UPDATE subtitles_formatted
            SET summary_status = NULL,
                summary_started_at = NULL,
                summary_finished_at = NULL
            WHERE id = :id
        """),
        {"id": fmt_id},
    )
    await db.commit()


async def delete_video(db: AsyncSession, video_id: str) -> bool:
    stmt = select(Video).where(Video.video_id == video_id)
    video = (await db.execute(stmt)).scalar_one_or_none()
    if not video:
        return False
    await db.execute(delete(SubtitleRaw).where(SubtitleRaw.video_id == video.id))
    await db.execute(delete(SubtitleFormatted).where(SubtitleFormatted.video_id == video.id))
    await db.execute(delete(ProcessingTask).where(ProcessingTask.video_id == video.id))
    await db.delete(video)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Pipeline settings CRUD
# ---------------------------------------------------------------------------

def _stage_to_dict(row: PipelineSettings | None, stage: str) -> dict:
    """Merge DB row with defaults. Missing fields fall back to STAGE_DEFAULTS."""
    defaults = STAGE_DEFAULTS.get(stage, {})
    if row is None:
        return {
            "stage": stage,
            "system_prompt": defaults.get("system_prompt"),
            "user_prompt_template": defaults.get("user_prompt_template"),
            "model": defaults.get("model"),
            "is_default": True,
        }
    return {
        "stage": stage,
        "system_prompt": row.system_prompt if row.system_prompt is not None else defaults.get("system_prompt"),
        "user_prompt_template": row.user_prompt_template if row.user_prompt_template is not None else defaults.get("user_prompt_template"),
        "model": row.model if row.model is not None else defaults.get("model"),
        "is_default": False,
    }


async def _get_stage_row(db: AsyncSession, stage: str) -> PipelineSettings | None:
    stmt = select(PipelineSettings).where(PipelineSettings.stage == stage)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_all_settings(db: AsyncSession) -> dict:
    """Return settings for all stages, merged with defaults."""
    cleanup_row = await _get_stage_row(db, "cleanup")
    summ_row = await _get_stage_row(db, "summarization")
    extract_row = await _get_stage_row(db, "summarization_extract")
    combine_row = await _get_stage_row(db, "summarization_combine")
    return {
        "cleanup": _stage_to_dict(cleanup_row, "cleanup"),
        "summarization": _stage_to_dict(summ_row, "summarization"),
        "summarization_extract": _stage_to_dict(extract_row, "summarization_extract"),
        "summarization_combine": _stage_to_dict(combine_row, "summarization_combine"),
    }


async def get_stage_settings(db: AsyncSession, stage: str) -> dict:
    """Return settings for a single stage, merged with defaults."""
    row = await _get_stage_row(db, stage)
    return _stage_to_dict(row, stage)


async def save_stage_settings(
    db: AsyncSession,
    stage: str,
    system_prompt: str | None,
    user_prompt_template: str | None,
    model: str | None,
) -> dict:
    """Upsert settings for a stage. Returns the saved state."""
    row = await _get_stage_row(db, stage)
    if row is None:
        row = PipelineSettings(id=generate_id(), stage=stage)
        db.add(row)
    row.system_prompt = system_prompt
    row.user_prompt_template = user_prompt_template
    row.model = model
    await db.commit()
    await db.refresh(row)
    return _stage_to_dict(row, stage)


async def reset_stage_settings(db: AsyncSession, stage: str) -> dict:
    """Delete the DB row for a stage, reverting to hardcoded defaults."""
    row = await _get_stage_row(db, stage)
    if row is not None:
        await db.delete(row)
        await db.commit()
    return _stage_to_dict(None, stage)


# ---------------------------------------------------------------------------
# App settings CRUD (key-value: ollama_url, ytdlp_path, cookies_path)
# ---------------------------------------------------------------------------

APP_SETTING_KEYS = ("ollama_url", "ytdlp_path", "cookies_path", "force_map_reduce")


async def get_all_app_settings(db: AsyncSession) -> dict:
    stmt = select(AppSetting).where(AppSetting.key.in_(APP_SETTING_KEYS))
    rows = (await db.execute(stmt)).scalars().all()
    result = {k: None for k in APP_SETTING_KEYS}
    for row in rows:
        result[row.key] = row.value
    return result


async def save_app_settings(db: AsyncSession, updates: dict) -> dict:
    for key, value in updates.items():
        if key not in APP_SETTING_KEYS:
            continue
        stmt = select(AppSetting).where(AppSetting.key == key)
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = AppSetting(key=key, value=value)
            db.add(row)
        else:
            row.value = value
    await db.commit()
    return await get_all_app_settings(db)


async def get_app_setting(db: AsyncSession, key: str) -> str | None:
    stmt = select(AppSetting).where(AppSetting.key == key)
    row = (await db.execute(stmt)).scalar_one_or_none()
    return row.value if row else None
