from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.stage_control import CLEANUP_CANCEL, MINDMAP_CANCEL, SUMMARY_CANCEL
from services.queue_by_id import already_running_message, ensure_stage_order, stage_will_run, RESULT_STAGES, queued_stages_of
from services.video_service import get_app_setting, get_result, get_stage_settings, set_cleanup_processing, set_summary_processing, start_mindmap_generation
from routers.settings import _uploads_dir
from services.reextract import enqueue_reextract, reextract_queued, stop_reextract

router = APIRouter()

# In-memory cancel flags — cleared when cleanup/summary finishes or is cancelled
_CANCEL_SET = CLEANUP_CANCEL  # the cleanup flag, shared with the queue worker (services/stage_control.py)
_SUMMARY_CANCEL_SET = SUMMARY_CANCEL  # shared with the queue worker (services/stage_control.py)
_MINDMAP_CANCEL_SET = MINDMAP_CANCEL  # shared with the queue worker (services/stage_control.py): the same set object


@router.post("/result/{video_id}/cleanup")
async def trigger_cleanup(
    video_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Queue the AI cleanup. The status is 'processing' at once (the page shows progress while the item waits its turn
    behind the queue); the queue worker does the work. A second click while one is queued or running adds nothing
    (NS-11 stage 4a)."""
    from services.db_retry import retry_locked
    from services.queue_by_id import enqueue_stage

    stage = await get_stage_settings(db, "cleanup")
    if not stage.get("model"):
        raise HTTPException(
            status_code=400,
            detail="No model configured. Please select a model in Settings first."
        )
    ollama_url = await get_app_setting(db, "ollama_url")
    if not ollama_url:
        raise HTTPException(
            status_code=400,
            detail="Ollama URL not configured. Please set it in Settings → General."
        )
    if not await get_result(db, video_id):
        raise HTTPException(status_code=404, detail="Result not found")
    _CANCEL_SET.discard(video_id)  # clear any stale cancel flag before starting
    await ensure_stage_order(db, video_id, "cleanup")  # 409 when a summary / mind map is queued: it would run on the old text
    # queue first: if the database is busy nothing has changed (503); the status is set right after, and again by the
    # stage itself when it starts
    item_id = await retry_locked(lambda: enqueue_stage(db, video_id, "cleanup"), db, "cleanup: queue")
    if item_id is None and not await stage_will_run(db, video_id, "cleanup"):
        raise HTTPException(status_code=409, detail=already_running_message("cleanup"))  # nothing queued: no status to set
    await set_cleanup_processing(db, video_id, model=stage.get("model"), queue_item_id=item_id)
    return {"status": "processing"}


@router.delete("/result/{video_id}/cleanup")
async def cancel_cleanup(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Stop the cleanup: a queued one is taken out of the queue, a running one is told to stop (it ends after the
    paragraph in hand). Either way the status goes back to "nothing running" and a previous cleaned text is kept."""
    from services.cancel import cancel_video_jobs

    await cancel_video_jobs(db, video_id, "cleanup")      # (NS-16: the same path as the Queue page's Cancel)
    return {"status": "cancelling"}


class ReextractRequest(BaseModel):
    language: str = "auto"
    model: str | None = None


async def _db_id(db: AsyncSession, video_id: str) -> str | None:
    return (await db.execute(
        text("SELECT id FROM videos WHERE video_id = :v AND url NOT LIKE '__pending__%'"), {"v": video_id})).scalar()


@router.post("/result/{video_id}/reextract")
async def trigger_reextract(
    video_id: str,
    body: ReextractRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Re-fetch subtitles (YouTube) or re-transcribe (uploaded file) for an existing video; invalidates what was made from the old
    text. The work is a queue item (NS-11 stage 6): the answer comes at once, the queue worker does it in its turn."""
    fmt = await get_result(db, video_id)
    if not fmt:
        raise HTTPException(status_code=404, detail="Video not found")
    if fmt.get("cleanup_status") == "processing":
        raise HTTPException(status_code=409, detail="Cleanup is in progress — cancel first")
    if fmt.get("summary_status") == "processing":
        raise HTTPException(status_code=409, detail="Summarization is in progress — cancel first")
    if await reextract_queued(db, video_id):
        raise HTTPException(status_code=409, detail="Re-extract already in progress")
    queued = await queued_stages_of(db, video_id)
    if queued & set(RESULT_STAGES):
        names = " and ".join(sorted(queued & set(RESULT_STAGES)))
        raise HTTPException(status_code=409, detail=f"A {names} is already queued for this video and would work on the old text: "
                                                    "wait for it or remove it on the Queue page, then try again.")
    # For local files: verify the original upload still exists before queuing
    url = fmt.get("url", "") or ""
    if url.startswith("local://") and video_id.startswith("file-"):
        import glob as _glob
        uuid_prefix = video_id[len("file-"):]
        matches = _glob.glob(os.path.join(_uploads_dir(), f"{uuid_prefix}*"))
        if not matches:
            raise HTTPException(
                status_code=422,
                detail="Original file not found — it was deleted after transcription. Upload the file again to re-transcribe.",
            )
    if await enqueue_reextract(db, video_id, await _db_id(db, video_id), url, body.language, body.model) is None:
        raise HTTPException(status_code=409, detail="Re-extract already in progress")   # another request queued it a moment ago
    return {"status": "reextracting"}


@router.delete("/result/{video_id}/reextract")
async def stop_reextract_endpoint(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Stop a re-extract / re-transcribe: a queued one leaves the queue, a running one ends after the segment in hand. Either way
    nothing is replaced: the saved subtitles and what was made from them stay (NS-11 decision 1)."""
    outcome = await stop_reextract(db, video_id)
    if outcome == "none":
        raise HTTPException(status_code=404, detail="No re-extract is queued or running for this video")
    return {"status": outcome}


@router.post("/result/{video_id}/summary")
async def trigger_summary(
    video_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Queue the summarization. The status is 'processing' at once (the page shows progress while the item waits its
    turn behind the queue); the queue worker does the work. A second click while one is queued or running adds nothing
    (NS-11 stage 3)."""
    from services.db_retry import retry_locked
    from services.queue_by_id import enqueue_stage

    stage = await get_stage_settings(db, "summarization")
    if not stage.get("model"):
        raise HTTPException(
            status_code=400,
            detail="No summarization model configured. Please select one in Settings → Summarization."
        )
    ollama_url = await get_app_setting(db, "ollama_url")
    if not ollama_url:
        raise HTTPException(
            status_code=400,
            detail="Ollama URL not configured. Please set it in Settings → General."
        )
    if not await get_result(db, video_id):
        raise HTTPException(status_code=404, detail="Result not found")
    _SUMMARY_CANCEL_SET.discard(video_id)
    await ensure_stage_order(db, video_id, "summary")  # 409 when a mind map is queued: it would be built from the old summary
    # queue first: if the database is busy nothing has changed (503); the status is set right after, and again by the
    # stage itself when it starts
    item_id = await retry_locked(lambda: enqueue_stage(db, video_id, "summary"), db, "summary: queue")
    if item_id is None and not await stage_will_run(db, video_id, "summary"):
        raise HTTPException(status_code=409, detail=already_running_message("summary"))
    await set_summary_processing(db, video_id, model=stage.get("model"), queue_item_id=item_id)
    return {"status": "processing"}


@router.delete("/result/{video_id}/summary")
async def cancel_summary(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Stop the summarization: a queued one is taken out of the queue, a running one is told to stop.

    Either way the status goes back to "nothing running" and a previous summary is kept (as in the background copy).
    """
    from services.cancel import cancel_video_jobs

    await cancel_video_jobs(db, video_id, "summary")      # (NS-16: the same path as the Queue page's Cancel)
    return {"status": "cancelling"}


# ---------------------------------------------------------------------------
# Mindmap endpoints
# ---------------------------------------------------------------------------

@router.post("/result/{video_id}/mindmap")
async def trigger_mindmap(
    video_id: str,
    db: AsyncSession = Depends(get_db),
    force: bool = False,
):
    """Queue the mind map. Returns the saved map unless force=true (the page's "Regenerate").

    The status is 'processing' at once (the page shows progress while the item waits its turn behind the queue); the
    queue worker does the work. A second click while one is queued or running adds nothing (NS-11 stage 2).
    """
    from services.db_retry import retry_locked
    from services.queue_by_id import enqueue_stage

    result = await get_result(db, video_id)
    if not result:
        raise HTTPException(404, "Video not found")

    # Return the saved map if there is one and the user did not ask to regenerate: also after a FAILED regeneration (the old
    # map was kept), not only when the last run succeeded. While a run is going on, nothing new is queued.
    if not force and result.get("mindmap_text") and result.get("mindmap_status") != "processing":
        return {"status": "done", "mindmap_text": result["mindmap_text"]}

    _MINDMAP_CANCEL_SET.discard(video_id)
    # queue first: if the database is busy nothing has changed; the status is set right after (and again by the stage
    # itself when it starts), so a queued item never has a stale "idle" status for more than a moment
    item_id = await retry_locked(lambda: enqueue_stage(db, video_id, "mindmap"), db, "mindmap: queue")
    if item_id is None and not await stage_will_run(db, video_id, "mindmap"):
        raise HTTPException(status_code=409, detail=already_running_message("mindmap"))
    model = (await get_stage_settings(db, "summarization")).get("model")      # the mind map uses the summary model
    await start_mindmap_generation(db, video_id, queue_item_id=item_id, model=model)
    return {"status": "processing"}


@router.delete("/result/{video_id}/mindmap")
async def cancel_mindmap(video_id: str, db: AsyncSession = Depends(get_db)):
    """Stop the mind map: a queued one is taken out of the queue, a running one is told to stop.

    Either way the status goes back to "nothing running" and a saved map is kept (as in the background copy).
    """
    from services.cancel import cancel_video_jobs

    await cancel_video_jobs(db, video_id, "mindmap")      # (NS-16: the same path as the Queue page's Cancel)
    return {"status": "cancelling"}
