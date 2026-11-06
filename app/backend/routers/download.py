from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.downloader import mp4_format_spec
from services.subtitle_extractor import _ytdlp_cmd, validate_youtube_url
from services.video_service import get_app_setting

router = APIRouter()


# (the format selector lives in services/downloader.py, shared with the download stage of the queue)
_mp4_format_spec = mp4_format_spec


@router.get("/download/direct")
async def download_direct(
    url: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    format: str = "mp4",
    quality: str = "best",
):
    """Download video/audio by URL directly, without subtitle extraction."""
    canonical = validate_youtube_url(url)
    if not canonical:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    url = canonical

    ytdlp_path = await get_app_setting(db, "ytdlp_path")
    cookies_path = await get_app_setting(db, "cookies_path")
    cmd = _ytdlp_cmd(ytdlp_path)

    safe_title = re.sub(r'[\\/*?:"<>|]', "_", url.split("v=")[-1][:40])
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
                asyncio.to_thread(subprocess.run, args, capture_output=True, timeout=890),
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
        download_name = f"{safe_title}{out_file.suffix}"
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
