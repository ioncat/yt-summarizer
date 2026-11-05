from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Annotated

import httpx
from services.http_client import http_client
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.video_service import (
    get_all_app_settings,
    get_all_settings,
    get_app_setting,
    get_stage_settings,
    reset_stage_settings,
    save_app_settings,
    save_stage_settings,
)

logger = logging.getLogger("api")

router = APIRouter()

_YTDLP_UPDATE_STATUS: dict = {"status": "idle"}  # idle | running | done | failed

_COOKIES_MAX_BYTES = 5 * 1024 * 1024  # 5 MB — cookie files are small


class StageSettingsRequest(BaseModel):
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    model: str | None = None


class AppSettingsRequest(BaseModel):
    ollama_url: str | None = None
    ytdlp_path: str | None = None
    cookies_path: str | None = None
    force_map_reduce: bool | None = None
    parallel_workers: str | None = None
    stt_engine: str | None = None
    stt_model: str | None = None
    stt_device: str | None = None
    stt_cache_path: str | None = None
    upload_auto_delete: str | None = None
    upload_auto_delete_mode: str | None = None
    upload_auto_delete_days: str | None = None
    chat_num_ctx: str | None = None
    llm_max_num_ctx: str | None = None
    download_default_format: str | None = None
    download_default_quality: str | None = None


def _uploads_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/uploads"))


def _uploads_stats() -> dict:
    """Return file count and total size of the uploads directory."""
    d = _uploads_dir()
    if not os.path.isdir(d):
        return {"file_count": 0, "total_mb": 0.0}
    files = [f for f in os.scandir(d) if f.is_file()]
    total_bytes = sum(f.stat().st_size for f in files)
    return {"file_count": len(files), "total_mb": round(total_bytes / (1024 * 1024), 1)}


def _cleanup_old_uploads(keep_days: int) -> int:
    """Delete upload files older than keep_days days. Returns count deleted."""
    import time
    d = _uploads_dir()
    if not os.path.isdir(d):
        return 0
    cutoff = time.time() - keep_days * 86400
    deleted = 0
    for entry in os.scandir(d):
        if entry.is_file() and entry.stat().st_mtime < cutoff:
            try:
                os.remove(entry.path)
                deleted += 1
            except OSError:
                pass
    return deleted


@router.get("/settings")
async def get_settings(db: Annotated[AsyncSession, Depends(get_db)]):
    pipeline = await get_all_settings(db)
    app = await get_all_app_settings(db)
    return {"app": app, **pipeline}


@router.put("/settings/app")
async def update_app_settings(
    body: AppSettingsRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    raw = body.model_dump()
    updates: dict = {}
    for k, v in raw.items():
        if k not in body.model_fields_set:
            continue
        updates[k] = None if v is None else ("true" if v is True else ("false" if v is False else v))
    return await save_app_settings(db, updates)


@router.put("/settings/{stage}")
async def update_settings(
    stage: str,
    body: StageSettingsRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if stage not in ("cleanup", "summarization", "summarization_extract", "summarization_combine", "chat"):
        raise HTTPException(status_code=400, detail="Unknown stage")
    return await save_stage_settings(
        db, stage, body.system_prompt, body.user_prompt_template, body.model
    )


@router.delete("/settings/{stage}")
async def reset_settings(stage: str, db: Annotated[AsyncSession, Depends(get_db)]):
    if stage not in ("cleanup", "summarization", "summarization_extract", "summarization_combine", "chat"):
        raise HTTPException(status_code=400, detail="Unknown stage")
    return await reset_stage_settings(db, stage)


@router.get("/settings/ytdlp-version")
async def get_ytdlp_version():
    """Return the currently installed yt-dlp version."""
    try:
        import yt_dlp
        version = yt_dlp.version.__version__
    except Exception:
        version = None
    return {
        "version": version,
        "update_status": _YTDLP_UPDATE_STATUS.get("status", "idle"),
        "new_version": _YTDLP_UPDATE_STATUS.get("new_version"),
        "update_error": _YTDLP_UPDATE_STATUS.get("error"),
    }


@router.get("/settings/ytdlp-latest")
async def get_ytdlp_latest_version():
    """Fetch the latest yt-dlp version from PyPI."""
    try:
        async with http_client(timeout=5.0) as client:
            resp = await client.get("https://pypi.org/pypi/yt-dlp/json")
            if resp.status_code == 200:
                data = resp.json()
                return {"latest": data["info"]["version"]}
    except Exception:
        pass
    return {"latest": None}


@router.post("/settings/update-ytdlp")
async def update_ytdlp():
    """Upgrade yt-dlp to the latest version in the background."""
    if _YTDLP_UPDATE_STATUS.get("status") == "running":
        return {"status": "already_running"}
    _YTDLP_UPDATE_STATUS["status"] = "running"

    def _run_pip():
        import subprocess as _sp
        result = _sp.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            capture_output=True, text=True, timeout=120,
        )
        return result.returncode, result.stdout + result.stderr

    async def _do_update():
        try:
            returncode, output = await asyncio.to_thread(_run_pip)
            if returncode == 0:
                try:
                    import importlib
                    import yt_dlp
                    importlib.reload(yt_dlp.version)
                    new_version = yt_dlp.version.__version__
                except Exception:
                    new_version = None
                _YTDLP_UPDATE_STATUS["status"] = "done"
                _YTDLP_UPDATE_STATUS["new_version"] = new_version
            else:
                err_tail = output[-400:].strip()
                _YTDLP_UPDATE_STATUS["status"] = "failed"
                _YTDLP_UPDATE_STATUS["error"] = err_tail or f"pip exited with code {returncode}"
        except Exception as exc:
            _YTDLP_UPDATE_STATUS["status"] = "failed"
            _YTDLP_UPDATE_STATUS["error"] = str(exc) or repr(exc)
            logger.error("yt-dlp update failed: %r", exc)
        finally:
            await asyncio.sleep(60)
            _YTDLP_UPDATE_STATUS.update({"status": "idle", "new_version": None, "error": None})

    asyncio.create_task(_do_update())
    return {"status": "started"}


@router.post("/settings/upload-cookies")
async def upload_cookies(
    file: UploadFile = File(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Upload a cookies.txt file and save it to the data directory."""
    content = await file.read()
    if len(content) > _COOKIES_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Cookie file too large (max 5 MB)")
    cookies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data"))
    os.makedirs(cookies_dir, exist_ok=True)
    filename = Path(file.filename or "cookies.txt").name
    save_path = os.path.join(cookies_dir, filename)
    with open(save_path, "wb") as f:
        f.write(content)
    await save_app_settings(db, {"cookies_path": save_path})
    return {"path": save_path}


@router.get("/settings/storage")
async def get_storage_info(db: Annotated[AsyncSession, Depends(get_db)]):
    """Return upload storage stats and current policy settings."""
    stats = _uploads_stats()
    auto_delete = await get_app_setting(db, "upload_auto_delete") or "false"
    mode = await get_app_setting(db, "upload_auto_delete_mode") or "immediate"
    days = await get_app_setting(db, "upload_auto_delete_days") or "7"
    return {
        **stats,
        "auto_delete": auto_delete == "true",
        "auto_delete_mode": mode,
        "auto_delete_days": days,
    }


@router.delete("/settings/storage/uploads")
async def clear_uploads():
    """Delete all files in the uploads directory."""
    d = _uploads_dir()
    if not os.path.isdir(d):
        return {"deleted": 0}
    deleted = 0
    for entry in os.scandir(d):
        if entry.is_file():
            try:
                os.remove(entry.path)
                deleted += 1
            except OSError:
                pass
    return {"deleted": deleted, **_uploads_stats()}
