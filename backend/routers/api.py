from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import get_db
from services.subtitle_extractor import extract_subtitles, extract_video_id
from services.text_formatter import format_subtitles
from services.video_service import (
    create_pending_task,
    delete_video,
    get_history,
    get_result,
    get_task,
    save_processing_result,
    update_task_failed,
)

router = APIRouter(prefix="/api")


class ProcessRequest(BaseModel):
    url: str
    language: str = "ru"


async def _run_processing(task_id: str, url: str, language: str) -> None:
    from models.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            extraction = await asyncio.to_thread(
                extract_subtitles, url, language, settings.cookies_path
            )
            if not extraction.success:
                await update_task_failed(db, task_id, extraction.error_message or "Extraction failed")
                return

            formatted = format_subtitles(extraction.subtitles)
            await save_processing_result(db, url, extraction, formatted)

        except Exception as e:
            async with AsyncSessionLocal() as db2:
                await update_task_failed(db2, task_id, str(e))


@router.post("/process")
async def process_video(
    body: ProcessRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    video_id = extract_video_id(body.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    task = await create_pending_task(db, video_id)
    background_tasks.add_task(_run_processing, task.id, body.url, body.language)
    return {"task_id": task.id, "video_id": video_id}


@router.get("/status/{task_id}")
async def get_status(task_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.id,
        "status": task.status,
        "progress": task.progress,
        "error_message": task.error_message,
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
