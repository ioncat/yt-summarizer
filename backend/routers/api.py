from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import get_db
from services.subtitle_extractor import extract_subtitles, extract_video_id
from services.text_cleaner import clean_text
from services.text_formatter import format_subtitles
from services.video_service import (
    complete_task,
    create_pending_task,
    delete_video,
    get_history,
    get_result,
    get_task,
    update_task_failed,
)

router = APIRouter(prefix="/api")


class ProcessRequest(BaseModel):
    url: str
    language: str = "ru"
    enable_cleanup: bool = False


async def _run_processing(task_id: str, url: str, language: str, enable_cleanup: bool = False) -> None:
    from models.database import AsyncSessionLocal

    try:
        extraction = await asyncio.to_thread(
            extract_subtitles, url, language, settings.cookies_path
        )
        async with AsyncSessionLocal() as db:
            if not extraction.success:
                await update_task_failed(
                    db, task_id,
                    extraction.error_message or "Extraction failed",
                    available_languages=extraction.available_languages,
                )
                return
            formatted = format_subtitles(extraction.subtitles)
            cleaned = await clean_text(formatted["formatted_text"]) if enable_cleanup else None
            await complete_task(db, task_id, url, extraction, formatted, cleaned_text=cleaned)

    except Exception as e:
        async with AsyncSessionLocal() as db:
            await update_task_failed(db, task_id, str(e))


@router.post("/process")
async def process_video(
    body: ProcessRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    video_id = extract_video_id(body.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    task = await create_pending_task(db, body.url, video_id)
    background_tasks.add_task(_run_processing, task.id, body.url, body.language, body.enable_cleanup)
    return {"task_id": task.id, "video_id": video_id}


@router.get("/status/{task_id}")
async def get_status(task_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    error_message = task.error_message
    available_languages = None
    if error_message:
        try:
            parsed = json.loads(error_message)
            error_message = parsed.get("message", error_message)
            available_languages = parsed.get("available_languages")
        except (json.JSONDecodeError, AttributeError):
            pass

    return {
        "task_id": task.id,
        "status": task.status,
        "progress": task.progress,
        "error_message": error_message,
        "available_languages": available_languages,
    }


@router.get("/result/{video_id}")
async def get_video_result(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await get_result(db, video_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return result


@router.get("/history")
async def list_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = 1,
):
    return await get_history(db, page=page)


@router.delete("/result/{video_id}")
async def delete_result(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    deleted = await delete_video(db, video_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}
