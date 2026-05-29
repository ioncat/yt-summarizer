from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

import os

logger = logging.getLogger("api.mindmap")

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
    replace_subtitles_after_reextract,
    reset_cleanup_status,
    reset_stage_settings,
    reset_summary_status,
    save_app_settings,
    save_stage_settings,
    set_cleanup_processing,
    set_summary_processing,
    finish_summary,
    update_task_failed,
    save_chat_history,
    clear_chat_history,
    start_mindmap_generation,
    finish_mindmap,
    reset_mindmap_status,
)
from services.text_summarizer import summarize_text, extract_notes, MAP_REDUCE_THRESHOLD
from services.text_mindmapper import generate_mindmap

# In-memory cancel flags — cleared when cleanup/summary finishes or is cancelled
_CANCEL_SET: set[str] = set()
_SUMMARY_CANCEL_SET: set[str] = set()
_MINDMAP_CANCEL_SET: set[str] = set()

# In-memory progress: {video_id: {"done": int, "total": int}}
_CLEANUP_PROGRESS: dict[str, dict] = {}
_SUMMARY_PROGRESS: dict[str, dict] = {}
# Videos currently being re-extracted (set of video_id)
_REEXTRACT_SET: set[str] = set()

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

    # Dedup: if video already processed, redirect to existing result
    existing = await get_result(db, video_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"message": "Video already processed", "video_id": video_id},
        )

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
    # Flag if a re-extract is currently running
    if video_id in _REEXTRACT_SET:
        result["reextract_in_progress"] = True
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


async def _run_reextract(video_id: str, language: str = "auto") -> None:
    """Background task: re-extract subtitles for an existing video.
    Overwrites formatted_text + chapters, invalidates cleanup/summary."""
    from models.database import AsyncSessionLocal

    _REEXTRACT_SET.add(video_id)
    try:
        async with AsyncSessionLocal() as db:
            fmt = await get_result(db, video_id)
            if not fmt:
                return
            url = fmt["url"]
            # If caller passes "auto", fall back to previously detected language
            if language == "auto":
                language = fmt.get("language") or "auto"
            cookies_path = await get_app_setting(db, "cookies_path")
            ytdlp_path = await get_app_setting(db, "ytdlp_path") or "yt-dlp"

        extraction = await asyncio.to_thread(
            extract_subtitles, url, language, cookies_path, ytdlp_path
        )
        if not extraction.success:
            return
        formatted = format_subtitles(
            extraction.subtitles, chapters=extraction.metadata.chapters
        )
        async with AsyncSessionLocal() as db:
            await replace_subtitles_after_reextract(db, video_id, extraction, formatted)
    finally:
        _REEXTRACT_SET.discard(video_id)


class ReextractRequest(BaseModel):
    language: str = "auto"


@router.post("/result/{video_id}/reextract")
async def trigger_reextract(
    video_id: str,
    body: ReextractRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Re-fetch subtitles for an existing video. Invalidates cleanup/summary."""
    fmt = await get_result(db, video_id)
    if not fmt:
        raise HTTPException(status_code=404, detail="Video not found")
    if fmt.get("cleanup_status") == "processing":
        raise HTTPException(status_code=409, detail="Cleanup is in progress — cancel first")
    if fmt.get("summary_status") == "processing":
        raise HTTPException(status_code=409, detail="Summarization is in progress — cancel first")
    if video_id in _REEXTRACT_SET:
        raise HTTPException(status_code=409, detail="Re-extract already in progress")
    background_tasks.add_task(_run_reextract, video_id, body.language)
    return {"status": "reextracting"}


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
# Mindmap endpoints
# ---------------------------------------------------------------------------

async def _run_mindmap(video_id: str) -> None:
    """Background task: generate compact mindmap markdown via LLM."""
    logger.info("[mindmap] _run_mindmap started for video_id=%s", video_id)
    from models.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        result = await get_result(db, video_id)
        if not result:
            logger.warning("[mindmap] video_id=%s not found in DB", video_id)
            return

        text = result.get("summary_text") or result.get("cleaned_text") or result.get("formatted_text")
        if not text:
            logger.warning("[mindmap] no text for video_id=%s", video_id)
            await finish_mindmap(db, video_id, None)
            return

        stage = await get_stage_settings(db, "summarization")
        ollama_url = await get_app_setting(db, "ollama_url")
        model = stage.get("model") if stage else None
        logger.info("[mindmap] ollama_url=%s model=%s text_len=%d", ollama_url, model, len(text))

        if not ollama_url or not model:
            logger.warning("[mindmap] missing ollama_url or model, failing")
            await finish_mindmap(db, video_id, None)
            return

        # Resolve language code → full name for the prompt
        lang_code = result.get("language") or "ru"
        lang_map = {"ru": "Russian", "en": "English", "uk": "Ukrainian", "de": "German",
                    "fr": "French", "es": "Spanish", "zh": "Chinese", "ja": "Japanese"}
        language = lang_map.get(lang_code.lower(), lang_code)
        logger.info("[mindmap] language=%s, calling generate_mindmap...", language)

        mindmap_md = await generate_mindmap(
            text=text,
            ollama_url=ollama_url,
            model=model,
            language=language,
            is_cancelled=lambda: video_id in _MINDMAP_CANCEL_SET,
        )

        logger.info("[mindmap] generate_mindmap returned: %s", "None" if mindmap_md is None else f"{len(mindmap_md)} chars")

        if video_id in _MINDMAP_CANCEL_SET:
            _MINDMAP_CANCEL_SET.discard(video_id)
            await reset_mindmap_status(db, video_id)
            return

        await finish_mindmap(db, video_id, mindmap_md)
        logger.info("[mindmap] finish_mindmap done for video_id=%s", video_id)


@router.post("/result/{video_id}/mindmap")
async def trigger_mindmap(
    video_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    force: bool = False,
):
    """Trigger LLM mindmap generation. Returns cached result unless force=true."""
    result = await get_result(db, video_id)
    if not result:
        raise HTTPException(404, "Video not found")

    # Return cached result if available and not forced
    if not force and result.get("mindmap_text") and result.get("mindmap_status") == "done":
        return {"status": "done", "mindmap_text": result["mindmap_text"]}

    await start_mindmap_generation(db, video_id)
    _MINDMAP_CANCEL_SET.discard(video_id)
    background_tasks.add_task(_run_mindmap, video_id)
    return {"status": "processing"}


@router.delete("/result/{video_id}/mindmap")
async def cancel_mindmap(video_id: str):
    """Signal a running mindmap generation to stop."""
    _MINDMAP_CANCEL_SET.add(video_id)
    return {"status": "cancelling"}


# ---------------------------------------------------------------------------
# Benchmark endpoints
# ---------------------------------------------------------------------------

class BenchmarkRunRequest(BaseModel):
    video_id: str
    models: list[str]
    mode_override: str | None = None  # 'single' | 'map_reduce' | 'full_extract' | None
    stage: str = "summary"  # 'summary' | 'cleanup'


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
    if request.stage not in ("summary", "cleanup"):
        raise HTTPException(status_code=400, detail="stage must be 'summary' or 'cleanup'")
    try:
        run_ids = await start_benchmark(
            db,
            video_id=request.video_id,
            models=request.models,
            mode_override=request.mode_override,
            stage=request.stage,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"run_ids": run_ids, "count": len(run_ids)}


@router.get("/benchmarks")
async def list_all_benchmarks(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return all benchmark runs grouped by video."""
    from services.benchmark_service import get_all_benchmarks_grouped
    groups = await get_all_benchmarks_grouped(db)
    return {"groups": groups}


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


@router.delete("/benchmark/run/{run_id}")
async def delete_benchmark_run_endpoint(
    run_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a single benchmark run by ID."""
    from services.benchmark_service import delete_benchmark_run
    ok = await delete_benchmark_run(db, run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"deleted": run_id}


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


# ---------------------------------------------------------------------------
# Queue endpoints (Epic 34)
# ---------------------------------------------------------------------------

class BulkQueueRequest(BaseModel):
    urls: list[str]
    pipeline_stages: list[str] | None = None  # defaults to app_settings queue_default_pipeline


@router.post("/queue/bulk")
async def queue_bulk_add(
    body: BulkQueueRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add multiple URLs to the processing queue."""
    from services.queue_service import add_items

    if not body.urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    # Validate each URL and collect valid ones
    valid_urls: list[str] = []
    invalid: list[str] = []
    for url in body.urls:
        if extract_video_id(url.strip()):
            valid_urls.append(url.strip())
        else:
            invalid.append(url.strip())

    if not valid_urls:
        raise HTTPException(status_code=400, detail={"message": "No valid YouTube URLs", "invalid": invalid})

    # Determine pipeline_stages
    if body.pipeline_stages is not None:
        stages = body.pipeline_stages
    else:
        raw = await get_app_setting(db, "queue_default_pipeline")
        import json as _json
        stages = _json.loads(raw) if raw else ["extract"]

    ids = await add_items(db, valid_urls, stages)
    return {"added": len(ids), "ids": ids, "invalid": invalid}


@router.get("/queue")
async def get_queue_items(db: Annotated[AsyncSession, Depends(get_db)]):
    """Return all queue items ordered by sort_order + added_at."""
    from services.queue_service import get_queue
    items = await get_queue(db)
    return {"items": items, "count": len(items)}


@router.get("/queue/counts")
async def get_queue_status_counts(db: Annotated[AsyncSession, Depends(get_db)]):
    """Return item counts per status — for nav badge."""
    from services.queue_service import get_queue_counts
    counts = await get_queue_counts(db)
    pending = counts.get("pending", 0)
    processing = counts.get("processing", 0)
    return {"pending": pending, "processing": processing, "active": pending + processing, "counts": counts}


@router.delete("/queue/all")
async def clear_queue_pending(db: Annotated[AsyncSession, Depends(get_db)]):
    """Clear all pending queue items (does not touch processing/done/failed)."""
    from services.queue_service import clear_pending
    count = await clear_pending(db)
    return {"cleared": count}


@router.delete("/queue/{item_id}")
async def delete_queue_item(item_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    """Delete a single pending queue item."""
    from services.queue_service import delete_item
    result = await delete_item(db, item_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Item not found")
    if result == "conflict":
        raise HTTPException(status_code=409, detail="Cannot delete a processing item")
    return {"deleted": item_id}
