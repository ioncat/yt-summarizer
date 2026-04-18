from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Video, SubtitleRaw, SubtitleFormatted, ProcessingTask
from models.models import generate_id
from services.subtitle_extractor import ExtractionResult, subtitles_to_json


async def get_or_create_video(db: AsyncSession, url: str, result: ExtractionResult) -> Video:
    stmt = select(Video).where(Video.url == url)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing

    m = result.metadata
    video = Video(
        id=generate_id(),
        url=url,
        video_id=m.video_id,
        title=m.title,
        author=m.author,
        duration=m.duration,
        channel_id=m.channel_id,
        channel_name=m.channel_name,
        upload_date=m.upload_date,
        view_count=m.view_count,
        description=m.description,
        thumbnail_url=m.thumbnail_url,
        language_detected=result.language,
        has_subtitles=True,
        subtitles_type=result.source_type.value if result.source_type else None,
    )
    db.add(video)
    await db.flush()
    return video


async def save_processing_result(
    db: AsyncSession,
    url: str,
    extraction_result: ExtractionResult,
    formatted: dict,
) -> tuple[Video, ProcessingTask]:
    video = await get_or_create_video(db, url, extraction_result)

    raw = SubtitleRaw(
        id=generate_id(),
        video_id=video.id,
        language=extraction_result.language,
        original_subtitles=subtitles_to_json(extraction_result.subtitles),
        source_type=extraction_result.source_type.value if extraction_result.source_type else None,
    )
    db.add(raw)

    fmt = SubtitleFormatted(
        id=generate_id(),
        video_id=video.id,
        language=extraction_result.language,
        formatted_text=formatted["formatted_text"],
        text_length=formatted["char_count"],
        processing_status="success",
    )
    db.add(fmt)

    task = ProcessingTask(
        id=generate_id(),
        video_id=video.id,
        status="completed",
        progress=100,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    db.add(task)

    await db.commit()
    return video, task


async def create_pending_task(db: AsyncSession, placeholder_video_id: str) -> ProcessingTask:
    video = Video(
        id=generate_id(),
        url=f"__pending__{placeholder_video_id}",
        video_id=placeholder_video_id,
    )
    db.add(video)
    await db.flush()

    task = ProcessingTask(
        id=generate_id(),
        video_id=video.id,
        status="pending",
        progress=0,
    )
    db.add(task)
    await db.commit()
    return task


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
    stmt = select(Video).where(Video.video_id == video_id)
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
