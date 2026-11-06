from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from models.database import get_db
from services.subtitle_extractor import extract_video_id, validate_youtube_url, _ytdlp_cmd
from services.video_service import (
    delete_video,
    get_app_setting,
    get_result,
    save_chat_history,
    clear_chat_history,
    toggle_favorite,
)
from routers.download import _mp4_format_spec
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
