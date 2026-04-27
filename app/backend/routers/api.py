from __future__ import annotations

import asyncio
import json
from typing import Annotated

import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.subtitle_extractor import extract_subtitles, extract_video_id
from services.text_cleaner import clean_text
from services.text_formatter import format_subtitles
from services.video_service import (
    complete_task,
    create_pending_task,
    delete_video,
    finish_cleanup,
    get_all_app_settings,
    get_all_settings,
    get_app_setting,
    get_history,
    get_result,
    get_stage_settings,
    get_task,
    reset_cleanup_status,
    reset_stage_settings,
    reset_summary_status,
    save_app_settings,
    save_stage_settings,
    set_cleanup_processing,
    set_summary_processing,
    finish_summary,
    update_task_failed,
)
from services.text_summarizer import summarize_text

# In-memory cancel flags — cleared when cleanup/summary finishes or is cancelled
_CANCEL_SET: set[str] = set()
_SUMMARY_CANCEL_SET: set[str] = set()

router = APIRouter(prefix="/api")


class ProcessRequest(BaseModel):
    url: str
    language: str = "ru"


class StageSettingsRequest(BaseModel):
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    model: str | None = None


class AppSettingsRequest(BaseModel):
    ollama_url: str | None = None
    ytdlp_path: str | None = None
    cookies_path: str | None = None


async def _run_processing(task_id: str, url: str, language: str) -> None:
    from models.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            cookies_path = await get_app_setting(db, "cookies_path")
            ytdlp_path = await get_app_setting(db, "ytdlp_path") or "yt-dlp"

        extraction = await asyncio.to_thread(
            extract_subtitles, url, language, cookies_path, ytdlp_path
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
            await complete_task(db, task_id, url, extraction, formatted)

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
    background_tasks.add_task(_run_processing, task.id, body.url, body.language)
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


async def _run_cleanup(video_id: str) -> None:
    """Background task: run LLM cleanup and persist result."""
    from models.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        fmt = await get_result(db, video_id)
        if not fmt or not fmt.get("formatted_text"):
            return
        formatted_text = fmt["formatted_text"]
        stage = await get_stage_settings(db, "cleanup")
        ollama_url = await get_app_setting(db, "ollama_url")

    cleaned = await clean_text(
        formatted_text,
        system_prompt=stage.get("system_prompt"),
        user_prompt_template=stage.get("user_prompt_template"),
        model=stage.get("model"),
        ollama_url=ollama_url,
        is_cancelled=lambda: video_id in _CANCEL_SET,
    )

    async with AsyncSessionLocal() as db:
        if video_id in _CANCEL_SET:
            _CANCEL_SET.discard(video_id)
            await reset_cleanup_status(db, video_id)
        else:
            await finish_cleanup(db, video_id, cleaned)


@router.post("/result/{video_id}/cleanup")
async def trigger_cleanup(
    video_id: str,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
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
    ok = await set_cleanup_processing(db, video_id, model=stage.get("model"))
    if not ok:
        raise HTTPException(status_code=404, detail="Result not found")
    _CANCEL_SET.discard(video_id)  # clear any stale cancel flag before starting
    background_tasks.add_task(_run_cleanup, video_id)
    return {"status": "processing"}


@router.delete("/result/{video_id}/cleanup")
async def cancel_cleanup(video_id: str):
    """Signal a running cleanup to stop. Status resets to null after current paragraph."""
    _CANCEL_SET.add(video_id)
    return {"status": "cancelling"}


async def _run_summary(video_id: str) -> None:
    """Background task: run LLM summarization and persist result."""
    from models.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        fmt = await get_result(db, video_id)
        if not fmt:
            return
        # Prefer cleaned text, fall back to formatted
        source_text = fmt.get("cleaned_text") or fmt.get("formatted_text")
        if not source_text:
            return
        stage = await get_stage_settings(db, "summarization")
        ollama_url = await get_app_setting(db, "ollama_url")

    summary = await summarize_text(
        source_text,
        system_prompt=stage.get("system_prompt"),
        user_prompt_template=stage.get("user_prompt_template"),
        model=stage.get("model"),
        ollama_url=ollama_url,
        is_cancelled=lambda: video_id in _SUMMARY_CANCEL_SET,
    )

    async with AsyncSessionLocal() as db:
        if video_id in _SUMMARY_CANCEL_SET:
            _SUMMARY_CANCEL_SET.discard(video_id)
            await reset_summary_status(db, video_id)
        else:
            await finish_summary(db, video_id, summary)


@router.post("/result/{video_id}/summary")
async def trigger_summary(
    video_id: str,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
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
    ok = await set_summary_processing(db, video_id, model=stage.get("model"))
    if not ok:
        raise HTTPException(status_code=404, detail="Result not found")
    _SUMMARY_CANCEL_SET.discard(video_id)
    background_tasks.add_task(_run_summary, video_id)
    return {"status": "processing"}


@router.delete("/result/{video_id}/summary")
async def cancel_summary(video_id: str):
    """Signal a running summarization to stop."""
    _SUMMARY_CANCEL_SET.add(video_id)
    return {"status": "cancelling"}


@router.get("/health")
async def health_check(db: Annotated[AsyncSession, Depends(get_db)]):
    """Returns backend status and Ollama availability."""
    import httpx
    ollama_ok = False
    ollama_url = await get_app_setting(db, "ollama_url")
    if ollama_url:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{ollama_url}/api/tags")
                ollama_ok = resp.status_code == 200
        except Exception:
            pass
    return {"backend": True, "ollama": ollama_ok}


@router.delete("/result/{video_id}")
async def delete_result(video_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    deleted = await delete_video(db, video_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------

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
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return await save_app_settings(db, updates)


@router.put("/settings/{stage}")
async def update_settings(
    stage: str,
    body: StageSettingsRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if stage not in ("cleanup", "summarization"):
        raise HTTPException(status_code=400, detail="Unknown stage")
    return await save_stage_settings(
        db, stage, body.system_prompt, body.user_prompt_template, body.model
    )


@router.delete("/settings/{stage}")
async def reset_settings(stage: str, db: Annotated[AsyncSession, Depends(get_db)]):
    if stage not in ("cleanup", "summarization"):
        raise HTTPException(status_code=400, detail="Unknown stage")
    return await reset_stage_settings(db, stage)


@router.post("/settings/upload-cookies")
async def upload_cookies(
    file: UploadFile = File(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Upload a cookies.txt file and save it to the data directory."""
    cookies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data"))
    os.makedirs(cookies_dir, exist_ok=True)
    save_path = os.path.join(cookies_dir, "www.youtube.com_cookies.txt")
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    await save_app_settings(db, {"cookies_path": save_path})
    return {"path": save_path}


@router.get("/models")
async def list_models(db: Annotated[AsyncSession, Depends(get_db)]):
    """Return available Ollama models."""
    import httpx
    ollama_url = await get_app_setting(db, "ollama_url")
    if not ollama_url:
        raise HTTPException(status_code=400, detail="Ollama URL not configured")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return {"models": models}
    except Exception:
        raise HTTPException(status_code=503, detail="Ollama unavailable")
