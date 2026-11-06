from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from models.database import get_db
from services.downloader import find_download
from services.subtitle_extractor import _ytdlp_cmd
from services.video_service import get_app_setting, get_result
from routers.download import _mp4_format_spec

router = APIRouter()


# ---------------------------------------------------------------------------
# Download by video_id
# ---------------------------------------------------------------------------

@router.get("/downloads/{video_id}")
async def get_saved_download(video_id: str):
    """The file the queue's download stage saved for this video (data/downloads). Only the video id comes from the request; the
    file is looked up by that id (plain id characters only), so no path can be asked for."""
    found = find_download(video_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No downloaded file for this video")
    media = "audio/mpeg" if found.suffix.lower() == ".mp3" else "video/mp4"
    return FileResponse(path=str(found), media_type=media, filename=found.name)


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
