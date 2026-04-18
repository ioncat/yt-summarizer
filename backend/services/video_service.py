from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Video, SubtitleRaw, SubtitleFormatted, ProcessingTask
from models.models import generate_id
from services.subtitle_extractor import ExtractionResult, subtitles_to_json


async def create_pending_task(db: AsyncSession, url: str, video_id: str) -> ProcessingTask:
    # Return existing pending task if already submitted
    stmt = (
        select(ProcessingTask)
        .join(Video, ProcessingTask.video_id == Video.id)
        .where(Video.video_id == video_id, ProcessingTask.status == "pending")
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing

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

    # If real URL already exists (e.g. duplicate submit), remove the pending placeholder
    dup_stmt = select(Video).where(Video.url == url)
    dup = (await db.execute(dup_stmt)).scalar_one_or_none()
    if dup and dup.id != video.id:
        await db.execute(delete(ProcessingTask).where(ProcessingTask.video_id == video.id))
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


async def update_task_failed(db: AsyncSession, task_id: str, error: str) -> None:
    stmt = select(ProcessingTask).where(ProcessingTask.id == task_id)
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task:
        task.status = "failed"
        task.error_message = error
        task.completed_at = datetime.utcnow()
        await db.commit()


async def get_task(db: AsyncSession, task_id: str) -> ProcessingTask | None:
    stmt = select(ProcessingTask).where(ProcessingTask.id == task_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_result(db: AsyncSession, video_id: str) -> dict | None:
    stmt = select(Video).where(Video.video_id == video_id, ~Video.url.startswith("__pending__"))
    video = (await db.execute(stmt)).scalar_one_or_none()
    if not video:
        return None

    fmt_stmt = (
        select(SubtitleFormatted)
        .where(SubtitleFormatted.video_id == video.id)
        .order_by(SubtitleFormatted.created_at.desc())
    )
    fmt = (await db.execute(fmt_stmt)).scalar_one_or_none()

    return {
        "video_id": video.video_id,
        "url": video.url,
        "title": video.title,
        "author": video.author,
        "duration": video.duration,
        "language": fmt.language if fmt else None,
        "formatted_text": fmt.formatted_text if fmt else None,
        "char_count": fmt.text_length if fmt else None,
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
    return {
        "page": page,
        "items": [
            {
                "video_id": v.video_id,
                "title": v.title,
                "author": v.author,
                "language": v.language_detected,
                "created_at": v.created_at.isoformat(),
            }
            for v in rows
        ],
    }


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
