from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from models.database import get_db
from services.subtitle_extractor import extract_video_id, validate_youtube_url, _ytdlp_cmd
from services.stage_control import (
    CLEANUP_CANCEL, MINDMAP_CANCEL, SUMMARY_CANCEL,
)
from services.queue_by_id import already_running_message, ensure_stage_order, stage_will_run
from services.video_service import (
    delete_video,
    get_app_setting,
    get_result,
    get_stage_settings,
    reset_cleanup_status,
    reset_mindmap_status,
    reset_summary_status,
    save_chat_history,
    clear_chat_history,
    set_cleanup_processing,
    set_summary_processing,
    start_mindmap_generation,
    toggle_favorite,
)
from routers.download import _mp4_format_spec
from routers.settings import _uploads_dir
from services.queue_by_id import RESULT_STAGES, queued_stages_of
from services.reextract import enqueue_reextract, reextract_progress_text, reextract_queued, stop_reextract

logger = logging.getLogger("api")

router = APIRouter()

# In-memory cancel flags — cleared when cleanup/summary finishes or is cancelled
_CANCEL_SET = CLEANUP_CANCEL  # the cleanup flag, shared with the queue worker (services/stage_control.py)
_SUMMARY_CANCEL_SET = SUMMARY_CANCEL  # shared with the queue worker (services/stage_control.py)
_MINDMAP_CANCEL_SET = MINDMAP_CANCEL  # shared with the queue worker (services/stage_control.py): the same set object



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
    from services.queue_by_id import dequeue_pending_stage, has_processing_item

    if await dequeue_pending_stage(db, video_id, "cleanup"):
        await reset_cleanup_status(db, video_id)  # it never started: nothing else will reset the status
    if await has_processing_item(db, video_id):
        _CANCEL_SET.add(video_id)                 # the worker is on this video: its cleanup stage polls the flag
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
    from services.queue_by_id import dequeue_pending_stage, has_processing_item

    if await dequeue_pending_stage(db, video_id, "summary"):
        await reset_summary_status(db, video_id)  # it never started: nothing else will reset the status
    if await has_processing_item(db, video_id):
        _SUMMARY_CANCEL_SET.add(video_id)         # the worker is on this video: its summary stage polls the flag
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
    from services.queue_by_id import dequeue_pending_stage, has_processing_item

    if await dequeue_pending_stage(db, video_id, "mindmap"):
        await reset_mindmap_status(db, video_id)  # it never started: nothing else will reset the status
    if await has_processing_item(db, video_id):
        _MINDMAP_CANCEL_SET.add(video_id)      # the worker is on this video: its mind map stage polls the flag
    return {"status": "cancelling"}


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
# Download by video_id
# ---------------------------------------------------------------------------

@router.get("/result/{video_id}/download")
async def download_video(
    video_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    format: str = "mp4",
    quality: str = "best",
):
    """Download video/audio via yt-dlp. Returns the file as an attachment."""
    result = await get_result(db, video_id)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    url = result.get("url", "")
    if not url or url.startswith("local://"):
        raise HTTPException(status_code=400, detail="Download not available for local files")

    title = result.get("title") or video_id
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)[:80]

    ytdlp_path = await get_app_setting(db, "ytdlp_path")
    cookies_path = await get_app_setting(db, "cookies_path")
    cmd = _ytdlp_cmd(ytdlp_path)

    tmpdir = tempfile.mkdtemp()
    try:
        if format == "mp3":
            audio_quality = {"best": "320K", "high": "192K", "low": "128K"}.get(quality, "192K")
            args = cmd + [
                "--no-playlist",
                "-x", "--audio-format", "mp3",
                "--audio-quality", audio_quality,
                "-o", str(Path(tmpdir) / "%(title)s.%(ext)s"),
            ]
        else:
            fmt_spec = _mp4_format_spec(quality)
            args = cmd + [
                "--no-playlist",
                "-f", fmt_spec,
                "--merge-output-format", "mp4",
                "-o", str(Path(tmpdir) / "%(title)s.%(ext)s"),
            ]

        if cookies_path and Path(cookies_path).exists():
            args += ["--cookies", cookies_path]

        args += ["--", url]

        try:
            proc_result = await asyncio.wait_for(
                asyncio.to_thread(
                    subprocess.run,
                    args,
                    capture_output=True,
                    timeout=890,
                ),
                timeout=900,
            )
        except asyncio.TimeoutError:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise HTTPException(status_code=504, detail="Download timed out")

        if proc_result.returncode != 0:
            shutil.rmtree(tmpdir, ignore_errors=True)
            err = proc_result.stderr.decode(errors="replace")[-1000:] if proc_result.stderr else "unknown error"
            raise HTTPException(status_code=500, detail=f"yt-dlp failed: {err}")

        files = list(Path(tmpdir).iterdir())
        if not files:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise HTTPException(status_code=500, detail="No output file produced")

        out_file = files[0]
        ext = out_file.suffix
        download_name = f"{safe_title}{ext}"

        return FileResponse(
            path=str(out_file),
            media_type="video/mp4" if format == "mp4" else "audio/mpeg",
            filename=download_name,
            background=BackgroundTask(shutil.rmtree, tmpdir, True),
        )
    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/result/{video_id}")
async def delete_result(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    deleted = await delete_video(db, video_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}
