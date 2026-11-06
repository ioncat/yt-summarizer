from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.extract_queue import enqueue_extract
from services.file_stt import enqueue_local_file, task_progress_text, uploads_dir
from services.subtitle_extractor import extract_video_id, validate_youtube_url
from services.video_service import (
    create_pending_task,
    get_result,
    get_task,
)

router = APIRouter()

_SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".wma",
}

class ProcessRequest(BaseModel):
    url: str
    language: str = "auto"      # decision 8: auto everywhere (it used to be "ru" here only)


@router.post("/process")
async def process_video(
    body: ProcessRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Extract the subtitles of a YouTube link. The link is queued (NS-11 stage 7): the answer comes at once, the queue worker does
    the extraction in its turn, and /api/status/{task_id} follows it. A link that is already queued returns the same task."""
    canonical = validate_youtube_url(body.url)
    if not canonical:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    video_id = extract_video_id(canonical)

    # Dedup: if video already processed, redirect to existing result
    existing = await get_result(db, video_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"message": "Video already processed", "video_id": video_id},
        )

    task = await create_pending_task(db, canonical, video_id)
    await enqueue_extract(db, canonical, video_id, task.video_id, body.language)
    return {"task_id": task.id, "video_id": video_id}


@router.post("/process/file")
async def process_file(
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    language: str = Form("auto"),
):
    """Upload a local audio/video file for transcription. The upload is saved and queued (NS-11 stage 5): the answer comes at
    once, the queue worker transcribes it in its turn; /api/status/{task_id} follows it."""
    from uuid import uuid4

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(_SUPPORTED_AUDIO_EXTENSIONS))}")

    target_dir = uploads_dir()
    os.makedirs(target_dir, exist_ok=True)

    file_uuid = uuid4().hex[:12]
    save_filename = f"{file_uuid}{ext}"
    save_path = os.path.join(target_dir, save_filename)

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    original_filename = file.filename or save_filename
    local_video_id = f"file-{file_uuid[:8]}"

    task = await create_pending_task(db, f"local://{original_filename}", local_video_id)
    await enqueue_local_file(db, local_video_id, task.video_id, original_filename, language)
    return {"task_id": task.id, "video_id": local_video_id}


@router.delete("/process/file/{video_id}")
async def stop_file_transcription(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Stop the transcription of an uploaded file (NS-11 stage 5): a queued one is taken out of the queue, a running one is told
    to stop (it ends after the segment in hand). Either way nothing is saved, so a saved transcript stays as it was."""
    from services.file_stt import stop_upload
    outcome = await stop_upload(db, video_id)
    if outcome == "none":
        raise HTTPException(status_code=404, detail="This file is not being transcribed")
    return {"status": outcome}


@router.get("/status/{task_id}")
async def get_status(task_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    import json
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
        "progress_text": await task_progress_text(db, task.id),
        "error_message": error_message,
        "available_languages": available_languages,
    }
