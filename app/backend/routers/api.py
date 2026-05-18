from __future__ import annotations

import asyncio
import json
from typing import Annotated

import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
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
from services.text_summarizer import summarize_text, extract_notes, MAP_REDUCE_THRESHOLD

# In-memory cancel flags — cleared when cleanup/summary finishes or is cancelled
_CANCEL_SET: set[str] = set()
_SUMMARY_CANCEL_SET: set[str] = set()

# In-memory progress: {video_id: {"done": int, "total": int}}
_CLEANUP_PROGRESS: dict[str, dict] = {}
_SUMMARY_PROGRESS: dict[str, dict] = {}

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
    force_map_reduce: bool | None = None
    parallel_workers: str | None = None


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
            formatted = format_subtitles(extraction.subtitles, chapters=extraction.metadata.chapters)
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
    # Inject live cleanup progress if cleanup is running
    cleanup_progress = _CLEANUP_PROGRESS.get(video_id)
    if cleanup_progress:
        result["cleanup_paragraphs_done"] = cleanup_progress["done"]
        result["cleanup_paragraphs_total"] = cleanup_progress["total"]
    # Inject live Map-Reduce progress if summarization is running
    summary_progress = _SUMMARY_PROGRESS.get(video_id)
    if summary_progress:
        result["summary_chunks_done"] = summary_progress["done"]
        result["summary_chunks_total"] = summary_progress["total"]
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
    from datetime import datetime as _dt

    async with AsyncSessionLocal() as db:
        fmt = await get_result(db, video_id)
        if not fmt or not fmt.get("formatted_text"):
            return
        formatted_text = fmt["formatted_text"]
        stage = await get_stage_settings(db, "cleanup")
        ollama_url = await get_app_setting(db, "ollama_url")
        parallel_workers = int(await get_app_setting(db, "parallel_workers") or "1")

    def _on_cleanup_progress(done: int, total: int) -> None:
        _CLEANUP_PROGRESS[video_id] = {"done": done, "total": total}

    started_at = _dt.utcnow()
    cleaned = await clean_text(
        formatted_text,
        system_prompt=stage.get("system_prompt"),
        user_prompt_template=stage.get("user_prompt_template"),
        model=stage.get("model"),
        ollama_url=ollama_url,
        is_cancelled=lambda: video_id in _CANCEL_SET,
        on_progress=_on_cleanup_progress,
        parallel_workers=parallel_workers,
    )

    _CLEANUP_PROGRESS.pop(video_id, None)

    async with AsyncSessionLocal() as db:
        if video_id in _CANCEL_SET:
            _CANCEL_SET.discard(video_id)
            await reset_cleanup_status(db, video_id)
        else:
            await finish_cleanup(db, video_id, cleaned, started_at=started_at)


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
    from datetime import datetime as _dt

    async with AsyncSessionLocal() as db:
        fmt = await get_result(db, video_id)
        if not fmt:
            return
        # Prefer cleaned text, fall back to formatted
        source_text = fmt.get("cleaned_text") or fmt.get("formatted_text")
        if not source_text:
            return
        language = fmt.get("language")
        stage = await get_stage_settings(db, "summarization")
        extract_stage = await get_stage_settings(db, "summarization_extract")
        combine_stage = await get_stage_settings(db, "summarization_combine")
        ollama_url = await get_app_setting(db, "ollama_url")
        force_map_reduce = (await get_app_setting(db, "force_map_reduce") or "false") == "true"
        parallel_workers = int(await get_app_setting(db, "parallel_workers") or "1")

    def _on_chunk_progress(done: int, total: int) -> None:
        _SUMMARY_PROGRESS[video_id] = {"done": done, "total": total}

    # Auto-select Full Extract for chapter videos ≥ MAP_REDUCE_THRESHOLD chars
    use_full_extract = (
        not force_map_reduce
        and bool(fmt.get("chapters"))
        and len(source_text) >= MAP_REDUCE_THRESHOLD
    )

    started_at = _dt.utcnow()
    if use_full_extract:
        summary, mode, chunks_count = await extract_notes(
            source_text,
            model=stage.get("model"),
            ollama_url=ollama_url,
            is_cancelled=lambda: video_id in _SUMMARY_CANCEL_SET,
            on_progress=_on_chunk_progress,
            language=language,
            parallel_workers=parallel_workers,
            # Use extract defaults — not summarization prompts
        )
    else:
        summary, mode, chunks_count = await summarize_text(
            source_text,
            system_prompt=stage.get("system_prompt"),
            user_prompt_template=stage.get("user_prompt_template"),
            model=stage.get("model"),
            ollama_url=ollama_url,
            is_cancelled=lambda: video_id in _SUMMARY_CANCEL_SET,
            force_map_reduce=force_map_reduce,
            extract_prompt=extract_stage.get("user_prompt_template"),
            combine_prompt=combine_stage.get("user_prompt_template"),
            on_progress=_on_chunk_progress,
            language=language,
            parallel_workers=parallel_workers,
        )

    _SUMMARY_PROGRESS.pop(video_id, None)

    async with AsyncSessionLocal() as db:
        if video_id in _SUMMARY_CANCEL_SET:
            _SUMMARY_CANCEL_SET.discard(video_id)
            await reset_summary_status(db, video_id)
        else:
            await finish_summary(db, video_id, summary, mode=mode, chunks_count=chunks_count, started_at=started_at)


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


# ---------------------------------------------------------------------------
# Benchmark endpoints
# ---------------------------------------------------------------------------

class BenchmarkRunRequest(BaseModel):
    video_id: str
    models: list[str]
    mode_override: str | None = None  # 'single' | 'map_reduce' | 'full_extract' | None


@router.post("/benchmark/run")
async def start_benchmark_run(
    request: BenchmarkRunRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start benchmark: run N models on the same video text in parallel."""
    from services.benchmark_service import start_benchmark
    if not request.models:
        raise HTTPException(status_code=400, detail="No models specified")
    if len(request.models) > 4:
        raise HTTPException(status_code=400, detail="Maximum 4 models per benchmark")
    try:
        run_ids = await start_benchmark(
            db,
            video_id=request.video_id,
            models=request.models,
            mode_override=request.mode_override,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"run_ids": run_ids, "count": len(run_ids)}


@router.get("/benchmark/{video_id}")
async def get_benchmark(
    video_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return all benchmark runs for a video."""
    from services.benchmark_service import get_benchmark_runs
    runs = await get_benchmark_runs(db, video_id)
    return {"runs": runs}


@router.get("/benchmark/run/{run_id}")
async def get_benchmark_run_detail(
    run_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return a single benchmark run by ID."""
    from services.benchmark_service import get_benchmark_run
    run = await get_benchmark_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


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
    raw = body.model_dump()
    updates: dict = {}
    for k, v in raw.items():
        if v is None:
            continue
        updates[k] = "true" if v is True else ("false" if v is False else v)
    return await save_app_settings(db, updates)


@router.put("/settings/{stage}")
async def update_settings(
    stage: str,
    body: StageSettingsRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if stage not in ("cleanup", "summarization", "summarization_extract", "summarization_combine"):
        raise HTTPException(status_code=400, detail="Unknown stage")
    return await save_stage_settings(
        db, stage, body.system_prompt, body.user_prompt_template, body.model
    )


@router.delete("/settings/{stage}")
async def reset_settings(stage: str, db: Annotated[AsyncSession, Depends(get_db)]):
    if stage not in ("cleanup", "summarization", "summarization_extract", "summarization_combine"):
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


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str


@router.post("/chat")
async def chat_proxy(body: ChatRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    """Proxy a chat request to Ollama with streaming — avoids browser CORS restrictions."""
    ollama_url = await get_app_setting(db, "ollama_url")
    if not ollama_url:
        raise HTTPException(status_code=400, detail="Ollama URL not configured")

    payload = {
        "model": body.model,
        "stream": True,
        "messages": [{"role": m.role, "content": m.content} for m in body.messages],
    }

    async def stream_ollama():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", f"{ollama_url}/api/chat", json=payload) as resp:
                    if resp.status_code != 200:
                        yield json.dumps({"error": f"Ollama error {resp.status_code}"}).encode()
                        return
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except Exception as exc:
            yield json.dumps({"error": str(exc)}).encode()

    return StreamingResponse(stream_ollama(), media_type="application/x-ndjson")
