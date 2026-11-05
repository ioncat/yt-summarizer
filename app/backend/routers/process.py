from __future__ import annotations

import asyncio
import os
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.subtitle_extractor import extract_subtitles, extract_video_id, validate_youtube_url
from services.text_formatter import format_subtitles
from services.video_service import (
    complete_task,
    create_pending_task,
    get_app_setting,
    get_result,
    get_task,
    update_task_failed,
)

router = APIRouter()

# Live STT progress for direct file-upload transcription tasks: {task_id: progress_text}
_FILE_TASK_PROGRESS: dict[str, str] = {}

_SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".wma",
}

# URL extraction helpers for bulk input parsing
_URL_RE = re.compile(r'https?://[^\s|"\'<>]+')
_TRAIL_RE = re.compile(r'[,;.:!?]+$')


class ProcessRequest(BaseModel):
    url: str
    language: str = "ru"


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
    canonical = validate_youtube_url(body.url)
    if not canonical:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    video_id = extract_video_id(canonical)

    # Dedup: if video already processed, redirect to existing result
    existing = await get_result(db, video_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"message": "Video already processed", "video_id": video_id},
        )

    task = await create_pending_task(db, canonical, video_id)
    background_tasks.add_task(_run_processing, task.id, canonical, body.language)
    return {"task_id": task.id, "video_id": video_id}


async def _run_transcribe_file(
    task_id: str,
    local_video_id: str,
    audio_path: str,
    original_filename: str,
    language: str = "auto",
) -> None:
    """Background task: transcribe a locally uploaded audio/video file."""
    from models.database import AsyncSessionLocal
    from services.transcriber import transcribe as _transcribe, DEFAULT_CACHE_PATH
    from services.text_formatter import format_subtitles
    from services.subtitle_extractor import ExtractionResult, SubtitleEntry, VideoMetadata

    try:
        from datetime import datetime as _datetime
        async with AsyncSessionLocal() as db:
            stt_model = await get_app_setting(db, "stt_model") or "base"
            stt_device = await get_app_setting(db, "stt_device") or "auto"
            stt_cache_path = await get_app_setting(db, "stt_cache_path") or DEFAULT_CACHE_PATH

        transcription_started_at = _datetime.utcnow()
        _FILE_TASK_PROGRESS[task_id] = "transcribing…"

        def _on_stt_progress(n: int, cur_s: float = 0.0, tot_s: float = 0.0) -> None:
            pct = f" · {int(cur_s / tot_s * 100)}%" if tot_s > 0 else ""
            _FILE_TASK_PROGRESS[task_id] = f"segment {n}{pct}"

        transcription = await asyncio.to_thread(
            _transcribe, audio_path,
            language=language,
            model=stt_model,
            device=stt_device,
            cache_path=stt_cache_path,
            on_progress=_on_stt_progress,
        )
        _FILE_TASK_PROGRESS.pop(task_id, None)

        if not transcription.success:
            async with AsyncSessionLocal() as db:
                await update_task_failed(db, task_id, transcription.error_message or "Transcription failed")
            return

        detected_language = transcription.detected_language or (language if language != "auto" else "und")
        segments = transcription.segments or []
        entries = [
            SubtitleEntry(
                timestamp="{:02d}:{:02d}:{:02d}".format(
                    int(s["start"] // 3600),
                    int(s["start"] % 3600 // 60),
                    int(s["start"] % 60),
                ),
                text=s["text"].strip(),
            )
            for s in segments
            if s.get("text", "").strip()
        ]
        # Compute audio duration from last segment end time
        audio_duration = int(segments[-1]["end"]) if segments and segments[-1].get("end") else None

        title = os.path.splitext(original_filename)[0]
        metadata = VideoMetadata(
            video_id=local_video_id,
            title=title,
            author=None,
            duration=audio_duration,
            channel_id=None,
            channel_name=None,
            upload_date=None,
            view_count=None,
            description=None,
            thumbnail_url=None,
        )
        extraction = ExtractionResult(
            success=True,
            metadata=metadata,
            subtitles=entries,
            language=detected_language,
            source_type=None,
        )
        formatted = format_subtitles(entries)

        # Resolve actual device used (may differ from setting if CUDA fell back to CPU)
        actual_device = transcription.device_used if hasattr(transcription, "device_used") else stt_device

        async with AsyncSessionLocal() as db:
            await complete_task(
                db, task_id, f"local://{original_filename}", extraction, formatted,
                subtitle_source="transcript",
                transcription_started_at=transcription_started_at,
                transcription_model=stt_model,
                transcription_device=actual_device,
            )
            auto_delete = await get_app_setting(db, "upload_auto_delete")
            auto_delete_mode = await get_app_setting(db, "upload_auto_delete_mode") or "immediate"

        if auto_delete == "true" and auto_delete_mode == "immediate":
            try:
                os.remove(audio_path)
            except OSError:
                pass

    except Exception as e:
        async with AsyncSessionLocal() as db:
            await update_task_failed(db, task_id, str(e))


@router.post("/process/file")
async def process_file(
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    language: str = Form("auto"),
):
    """Upload a local audio/video file for transcription."""
    from uuid import uuid4

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(_SUPPORTED_AUDIO_EXTENSIONS))}")

    uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/uploads"))
    os.makedirs(uploads_dir, exist_ok=True)

    file_uuid = uuid4().hex[:12]
    save_filename = f"{file_uuid}{ext}"
    save_path = os.path.join(uploads_dir, save_filename)

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    original_filename = file.filename or save_filename
    local_video_id = f"file-{file_uuid[:8]}"

    task = await create_pending_task(db, f"local://{original_filename}", local_video_id)
    background_tasks.add_task(_run_transcribe_file, task.id, local_video_id, save_path, original_filename, language)
    return {"task_id": task.id, "video_id": local_video_id}


@router.get("/status/{task_id}")
async def get_status(task_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    import json
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
        "progress_text": _FILE_TASK_PROGRESS.get(task.id),
        "error_message": error_message,
        "available_languages": available_languages,
    }


# ---------------------------------------------------------------------------
# STT model management
# ---------------------------------------------------------------------------

@router.get("/stt/models")
async def get_stt_models(db: Annotated[AsyncSession, Depends(get_db)]):
    """Return full model catalog with downloaded status."""
    from services.transcriber import get_available_models, DEFAULT_CACHE_PATH
    cache_path = (await get_app_setting(db, "stt_cache_path")) or DEFAULT_CACHE_PATH
    engine = (await get_app_setting(db, "stt_engine")) or "faster-whisper"
    return {"engine": engine, "models": get_available_models(cache_path)}


@router.post("/stt/models/{model_name}/download")
async def download_stt_model(
    model_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start downloading a model in the background."""
    from services.transcriber import MODEL_CATALOG, QWEN_CATALOG, DEFAULT_CACHE_PATH, start_model_download, is_model_downloaded
    if model_name not in MODEL_CATALOG and model_name not in QWEN_CATALOG:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")
    cache_path = (await get_app_setting(db, "stt_cache_path")) or DEFAULT_CACHE_PATH
    if is_model_downloaded(model_name, cache_path):
        return {"status": "already_downloaded"}
    started = start_model_download(model_name, cache_path)
    return {"status": "started" if started else "already_downloading"}


@router.get("/stt/models/{model_name}/download/status")
async def get_stt_model_download_status(
    model_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Poll download progress for a model."""
    from services.transcriber import MODEL_CATALOG, QWEN_CATALOG, DEFAULT_CACHE_PATH, get_download_status
    if model_name not in MODEL_CATALOG and model_name not in QWEN_CATALOG:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")
    cache_path = (await get_app_setting(db, "stt_cache_path")) or DEFAULT_CACHE_PATH
    return get_download_status(model_name, cache_path)


@router.delete("/stt/models/{model_name}")
async def delete_stt_model(
    model_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a downloaded model from the cache."""
    from services.transcriber import MODEL_CATALOG, QWEN_CATALOG, DEFAULT_CACHE_PATH, delete_model
    if model_name not in MODEL_CATALOG and model_name not in QWEN_CATALOG:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")
    cache_path = (await get_app_setting(db, "stt_cache_path")) or DEFAULT_CACHE_PATH
    deleted = delete_model(model_name, cache_path)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model not found on disk")
    return {"deleted": model_name}


# ---------------------------------------------------------------------------
# Queue endpoints (Epic 34)
# ---------------------------------------------------------------------------

MAX_BULK_ITEMS = 500  # per request, for urls and for video_ids each


class BulkQueueRequest(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=MAX_BULK_ITEMS)
    video_ids: list[str] = Field(default_factory=list, max_length=MAX_BULK_ITEMS)  # results already in History (also local files), queued by id; LLM stages only
    pipeline_stages: list[str] | None = None  # defaults to app_settings queue_default_pipeline
    force: bool = False  # skip dedup check (e.g. re-run stages on already-processed videos)
    language: str | None = None  # subtitle language; None → "auto" (auto-detect)


@router.post("/queue/bulk")
async def queue_bulk_add(
    body: BulkQueueRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add multiple URLs to the processing queue. Skips duplicates (already processed or in queue).

    `video_ids` queues results that are already in History by id (the only way to queue a local file);
    they can only run the LLM stages (cleanup, summary, mindmap).

    `force` applies to `urls` only: it skips the "already processed / already in the queue" check so a
    video can be re-run. `video_ids` ignore it: an id that is already pending or processing is always
    reported as a duplicate (two runs of the same stage on one video would overwrite each other).
    At most 500 urls and 500 video_ids per request.
    """
    from services.queue_service import add_items, get_duplicate_video_ids
    from services.queue_by_id import RESULT_STAGES, add_by_video_ids
    import json as _json

    if not body.urls and not body.video_ids:
        raise HTTPException(status_code=400, detail="No URLs provided")
    if any(not v.strip() for v in body.video_ids):
        raise HTTPException(status_code=400, detail="video_ids contains an empty id")
    if body.video_ids:
        by_id_stages = body.pipeline_stages
        if not by_id_stages or any(s not in RESULT_STAGES for s in by_id_stages):
            raise HTTPException(status_code=400, detail={
                "message": "Results already in History can only run: " + ", ".join(RESULT_STAGES)})

    # Step 1: validate + deduplicate within batch
    seen_video_ids: set[str] = set()
    valid_urls: list[str] = []      # URL → (url, video_id)
    valid_vid_ids: list[str] = []
    invalid: list[str] = []
    for raw_url in body.urls:
        raw = raw_url.strip()
        if not raw:
            continue
        # Extract URL from line — handles "URL | title", trailing punctuation, etc.
        m = _URL_RE.search(raw)
        url = _TRAIL_RE.sub('', m.group(0)) if m else raw
        vid = extract_video_id(url)
        if not vid:
            invalid.append(url)
        elif vid in seen_video_ids:
            invalid.append(url)  # intra-batch duplicate → treat as invalid
        else:
            seen_video_ids.add(vid)
            valid_urls.append(url)
            valid_vid_ids.append(vid)

    if body.urls and not valid_urls and not body.video_ids:
        raise HTTPException(status_code=400, detail={"message": "No valid YouTube URLs", "invalid": invalid})

    # Step 2: check against DB (skip if force=True — re-run mode from History)
    new_urls: list[str] = []
    duplicates: list[str] = []
    if body.force:
        new_urls = valid_urls  # no dedup — user explicitly re-queuing
    else:
        duplicate_vids = await get_duplicate_video_ids(db, valid_vid_ids)
        for url, vid in zip(valid_urls, valid_vid_ids):
            if vid in duplicate_vids:
                duplicates.append(url)
            else:
                new_urls.append(url)

    # Step 3: determine pipeline_stages
    if body.pipeline_stages is not None:
        stages = body.pipeline_stages
    else:
        raw = await get_app_setting(db, "queue_default_pipeline")
        stages = _json.loads(raw) if raw else ["extract"]

    # Step 4: add only new
    ids: list[int] = []
    if new_urls:
        ids = await add_items(db, new_urls, stages, language=body.language or None)

    missing: list[str] = []
    if body.video_ids:
        by_id = await add_by_video_ids(db, body.video_ids, body.pipeline_stages)
        ids += by_id["ids"]
        duplicates += by_id["duplicates"]
        missing = by_id["missing"]

    return {"added": len(ids), "ids": ids, "invalid": invalid, "duplicates": duplicates, "missing": missing}


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


@router.delete("/queue/failed")
async def clear_queue_failed(db: Annotated[AsyncSession, Depends(get_db)]):
    """Clear all failed queue items."""
    from services.queue_service import clear_failed
    count = await clear_failed(db)
    return {"cleared": count}


@router.post("/queue/failed/retry")
async def retry_queue_failed(db: Annotated[AsyncSession, Depends(get_db)]):
    """Reset all failed queue items to pending."""
    from services.queue_service import retry_all_failed
    count = await retry_all_failed(db)
    return {"retried": count}


@router.post("/queue/{item_id}/retry")
async def retry_queue_item(item_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    """Reset a single failed queue item to pending."""
    from services.queue_service import retry_item
    result = await retry_item(db, item_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Item not found")
    if result == "not_failed":
        raise HTTPException(status_code=409, detail="Item is not in failed state")
    return {"retried": item_id}


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
