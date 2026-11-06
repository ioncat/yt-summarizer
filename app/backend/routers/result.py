from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.subtitle_extractor import extract_video_id, validate_youtube_url
from services.video_service import delete_video, get_result, save_chat_history, clear_chat_history, toggle_favorite
from services.reextract import reextract_progress_text

logger = logging.getLogger("api")

router = APIRouter()


@router.get("/result/{video_id}")
async def get_video_result(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await get_result(db, video_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    # (the live cleanup / summary counters come with the result: get_result reads them from the stage's run row)
    # Flag if a re-extract / re-transcription is currently running
    progress = await reextract_progress_text(db, video_id)      # from the queue item and the stage's run row (NS-11 stage 6)
    if progress is not None:
        result["reextract_in_progress"] = True
        result["retranscribe_progress"] = progress
    return result


@router.post("/result/{video_id}/cancel")
async def cancel_video(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """The result page's Stop (NS-16): cancels every waiting or running job of this video, whatever its stage. Waiting ones leave
    the queue, a running one is told to stop. Nothing running is not an error (the job may have just finished)."""
    from services.cancel import cancel_video_jobs
    counts = await cancel_video_jobs(db, video_id)
    return {"status": "cancelling" if counts["removed"] or counts["stopping"] else "idle", **counts}


@router.post("/result/{video_id}/favorite")
async def favorite_video(
    video_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    new_state = await toggle_favorite(db, video_id)
    return {"video_id": video_id, "is_favorite": new_state}


# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------

class ChatHistoryRequest(BaseModel):
    messages: list[dict]


@router.put("/result/{video_id}/chat")
async def save_chat(
    video_id: str,
    body: ChatHistoryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await save_chat_history(db, video_id, body.messages)
    return {"status": "ok"}


@router.delete("/result/{video_id}/chat")
async def clear_chat(
    video_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await clear_chat_history(db, video_id)
    return {"status": "ok"}





# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/result/{video_id}")
async def delete_result(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    deleted = await delete_video(db, video_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}
