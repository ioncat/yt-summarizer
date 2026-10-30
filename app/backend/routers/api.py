from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from typing import Annotated

logger = logging.getLogger("api")
_reextract_logger = logging.getLogger("api.reextract")

# Live STT progress for direct file-upload transcription tasks: {task_id: progress_text}
_FILE_TASK_PROGRESS: dict[str, str] = {}

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
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
    toggle_favorite,
)
from services.text_summarizer import summarize_text, extract_notes, MAP_REDUCE_THRESHOLD
from services.text_mindmapper import generate_mindmap

# URL extraction helpers for bulk input parsing
_URL_RE = re.compile(r'https?://[^\s|"\'<>]+')
_TRAIL_RE = re.compile(r'[,;.:!?]+$')

# In-memory cancel flags — cleared when cleanup/summary finishes or is cancelled
_CANCEL_SET: set[str] = set()
_SUMMARY_CANCEL_SET: set[str] = set()
_MINDMAP_CANCEL_SET: set[str] = set()

# In-memory progress: {video_id: {"done": int, "total": int}}
_CLEANUP_PROGRESS: dict[str, dict] = {}
_SUMMARY_PROGRESS: dict[str, dict] = {}
# Videos currently being re-extracted (set of video_id)
_REEXTRACT_SET: set[str] = set()
# Live re-transcription progress: {video_id: progress_text}
_RETRANSCRIBE_PROGRESS: dict[str, str] = {}

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
    stt_engine: str | None = None
    stt_model: str | None = None
    stt_device: str | None = None
    stt_cache_path: str | None = None
    upload_auto_delete: str | None = None
    upload_auto_delete_mode: str | None = None
    upload_auto_delete_days: str | None = None
    chat_num_ctx: str | None = None


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


_SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".wma",
}


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
    # Flag if a re-extract / re-transcription is currently running
    if video_id in _REEXTRACT_SET:
        result["reextract_in_progress"] = True
        retranscribe_progress = _RETRANSCRIBE_PROGRESS.get(video_id)
        if retranscribe_progress:
            result["retranscribe_progress"] = retranscribe_progress
    return result


@router.get("/history")
async def list_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = 1,
    search: str | None = None,
    favorites_only: bool = False,
):
    return await get_history(db, page=page, search=search or None, favorites_only=favorites_only)


@router.post("/result/{video_id}/favorite")
async def favorite_video(
    video_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    new_state = await toggle_favorite(db, video_id)
    return {"video_id": video_id, "is_favorite": new_state}


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


async def _run_reextract(video_id: str, language: str = "auto", model: str | None = None) -> None:
    """Background task: re-extract subtitles for an existing video.
    For local:// URLs, re-runs Whisper transcription.
    Overwrites formatted_text + chapters, invalidates cleanup/summary."""
    import glob as _glob
    from models.database import AsyncSessionLocal

    _REEXTRACT_SET.add(video_id)
    try:
        async with AsyncSessionLocal() as db:
            fmt = await get_result(db, video_id)
            if not fmt:
                _reextract_logger.warning("reextract: video not found video_id=%s", video_id)
                return
            url = fmt["url"]

        if url and url.startswith("local://"):
            # Re-transcribe local file
            from services.transcriber import transcribe as _transcribe, DEFAULT_CACHE_PATH
            from services.text_formatter import format_subtitles as _format_subtitles
            from services.subtitle_extractor import ExtractionResult, SubtitleEntry, VideoMetadata
            from datetime import datetime as _datetime

            original_filename = url[len("local://"):]
            uuid_prefix = video_id[len("file-"):]  # strip "file-"
            uploads_dir = _uploads_dir()
            matches = _glob.glob(os.path.join(uploads_dir, f"{uuid_prefix}*"))
            if not matches:
                _reextract_logger.warning(
                    "retranscribe: file not found video_id=%s uuid_prefix=%s uploads_dir=%s",
                    video_id, uuid_prefix, uploads_dir,
                )
                return
            audio_path = matches[0]

            async with AsyncSessionLocal() as db:
                stt_model = model or await get_app_setting(db, "stt_model") or "base"
                stt_device = await get_app_setting(db, "stt_device") or "auto"
                stt_cache_path = await get_app_setting(db, "stt_cache_path") or DEFAULT_CACHE_PATH

            _reextract_logger.info(
                "retranscribe: starting video_id=%s file=%s model=%s language=%s",
                video_id, audio_path, stt_model, language,
            )
            from datetime import datetime as _dt
            transcription_started_at = _dt.utcnow()
            _RETRANSCRIBE_PROGRESS[video_id] = "starting…"

            def _on_retranscribe_progress(n: int, cur_s: float = 0.0, tot_s: float = 0.0) -> None:
                pct = f" · {int(cur_s / tot_s * 100)}%" if tot_s > 0 else ""
                _RETRANSCRIBE_PROGRESS[video_id] = f"segment {n}{pct}"

            transcription = await asyncio.to_thread(
                _transcribe, audio_path,
                language=language,
                model=stt_model,
                device=stt_device,
                cache_path=stt_cache_path,
                on_progress=_on_retranscribe_progress,
            )
            _RETRANSCRIBE_PROGRESS.pop(video_id, None)
            if not transcription.success:
                _reextract_logger.warning(
                    "retranscribe: failed video_id=%s error=%s",
                    video_id, transcription.error_message,
                )
                return

            detected_language = transcription.detected_language or (language if language != "auto" else "und")
            re_segments = transcription.segments or []
            entries = [
                SubtitleEntry(
                    timestamp="{:02d}:{:02d}:{:02d}".format(
                        int(s["start"] // 3600),
                        int(s["start"] % 3600 // 60),
                        int(s["start"] % 60),
                    ),
                    text=s["text"].strip(),
                )
                for s in re_segments
                if s.get("text", "").strip()
            ]
            audio_duration = int(re_segments[-1]["end"]) if re_segments and re_segments[-1].get("end") else None
            title = os.path.splitext(original_filename)[0]
            metadata = VideoMetadata(
                video_id=video_id,
                title=title,
                author=None, duration=audio_duration, channel_id=None,
                channel_name=None, upload_date=None, view_count=None,
                description=None, thumbnail_url=None,
            )
            extraction = ExtractionResult(
                success=True, metadata=metadata, subtitles=entries,
                language=detected_language, source_type=None,
            )
            formatted = _format_subtitles(entries)
            actual_device = transcription.device_used if hasattr(transcription, "device_used") else stt_device
            async with AsyncSessionLocal() as db:
                await replace_subtitles_after_reextract(
                    db, video_id, extraction, formatted,
                    transcription_started_at=transcription_started_at,
                    subtitle_source="transcript",
                    transcription_model=stt_model,
                    transcription_device=actual_device,
                )
            _reextract_logger.info(
                "retranscribe: success video_id=%s entries=%d lang=%s",
                video_id, len(entries), detected_language,
            )
            return

        # YouTube / standard yt-dlp path
        async with AsyncSessionLocal() as db:
            cookies_path = await get_app_setting(db, "cookies_path")
            ytdlp_path = await get_app_setting(db, "ytdlp_path") or "yt-dlp"

        _reextract_logger.info("reextract: starting video_id=%s url=%s language=%s", video_id, url, language)
        extraction = await asyncio.to_thread(
            extract_subtitles, url, language, cookies_path, ytdlp_path
        )
        if not extraction.success:
            _reextract_logger.warning(
                "reextract: extraction failed video_id=%s error_type=%s message=%s available=%s",
                video_id, extraction.error_type, extraction.error_message, extraction.available_languages,
            )
            return
        _reextract_logger.info(
            "reextract: success video_id=%s detected_lang=%s entries=%d",
            video_id, extraction.language, len(extraction.subtitles or []),
        )
        formatted = format_subtitles(
            extraction.subtitles, chapters=extraction.metadata.chapters
        )
        async with AsyncSessionLocal() as db:
            await replace_subtitles_after_reextract(db, video_id, extraction, formatted)
    except Exception:
        _reextract_logger.exception("reextract: unexpected error video_id=%s", video_id)
    finally:
        _REEXTRACT_SET.discard(video_id)
        _RETRANSCRIBE_PROGRESS.pop(video_id, None)


class ReextractRequest(BaseModel):
    language: str = "auto"
    model: str | None = None


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
    background_tasks.add_task(_run_reextract, video_id, body.language, body.model)
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
    from services.transcriber import MODEL_CATALOG, DEFAULT_CACHE_PATH, start_model_download, is_model_downloaded
    if model_name not in MODEL_CATALOG:
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
    from services.transcriber import MODEL_CATALOG, DEFAULT_CACHE_PATH, get_download_status
    if model_name not in MODEL_CATALOG:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")
    cache_path = (await get_app_setting(db, "stt_cache_path")) or DEFAULT_CACHE_PATH
    return get_download_status(model_name, cache_path)


@router.delete("/stt/models/{model_name}")
async def delete_stt_model(
    model_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a downloaded model from the cache."""
    from services.transcriber import MODEL_CATALOG, DEFAULT_CACHE_PATH, delete_model
    if model_name not in MODEL_CATALOG:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")
    cache_path = (await get_app_setting(db, "stt_cache_path")) or DEFAULT_CACHE_PATH
    deleted = delete_model(model_name, cache_path)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model not found on disk")
    return {"deleted": model_name}


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


class BulkDeleteRequest(BaseModel):
    video_ids: list[str]


@router.post("/history/delete-bulk")
async def delete_results_bulk(
    body: BulkDeleteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete multiple videos by video_id. Returns counts of deleted and not found."""
    if not body.video_ids:
        raise HTTPException(status_code=400, detail="No video_ids provided")
    deleted = 0
    not_found = 0
    for vid in body.video_ids:
        ok = await delete_video(db, vid)
        if ok:
            deleted += 1
        else:
            not_found += 1
    return {"deleted": deleted, "not_found": not_found}


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


_YTDLP_UPDATE_STATUS: dict = {"status": "idle"}  # idle | running | done | failed


@router.get("/settings/ytdlp-version")
async def get_ytdlp_version():
    """Return the currently installed yt-dlp version."""
    try:
        import yt_dlp
        version = yt_dlp.version.__version__
    except Exception:
        version = None
    return {"version": version, "update_status": _YTDLP_UPDATE_STATUS.get("status", "idle")}


@router.post("/settings/update-ytdlp")
async def update_ytdlp(background_tasks: BackgroundTasks):
    """Upgrade yt-dlp to the latest version in the background."""
    if _YTDLP_UPDATE_STATUS.get("status") == "running":
        return {"status": "already_running"}
    _YTDLP_UPDATE_STATUS["status"] = "running"

    async def _do_update():
        import asyncio as _asyncio
        try:
            proc = await _asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-U", "yt-dlp",
                stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            _YTDLP_UPDATE_STATUS["status"] = "done" if proc.returncode == 0 else "failed"
        except Exception as exc:
            _YTDLP_UPDATE_STATUS["status"] = "failed"
            logger.error("yt-dlp update failed: %s", exc)

    background_tasks.add_task(_do_update)
    return {"status": "started"}


@router.post("/settings/upload-cookies")
async def upload_cookies(
    file: UploadFile = File(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Upload a cookies.txt file and save it to the data directory."""
    cookies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data"))
    os.makedirs(cookies_dir, exist_ok=True)
    # Use original filename, fallback to cookies.txt
    filename = file.filename if file.filename else "cookies.txt"
    save_path = os.path.join(cookies_dir, filename)
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
        "options": {"num_ctx": int(await get_app_setting(db, "chat_num_ctx") or 32768)},
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
    force: bool = False  # skip dedup check (e.g. re-run stages on already-processed videos)
    language: str | None = None  # subtitle language; None → "auto" (auto-detect)


@router.post("/queue/bulk")
async def queue_bulk_add(
    body: BulkQueueRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add multiple URLs to the processing queue. Skips duplicates (already processed or in queue)."""
    from services.queue_service import add_items, get_duplicate_video_ids
    import json as _json

    if not body.urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

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

    if not valid_urls:
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

    return {"added": len(ids), "ids": ids, "invalid": invalid, "duplicates": duplicates}


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


# ---------------------------------------------------------------------------
# Storage management
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# MCP Connect endpoints
# ---------------------------------------------------------------------------

from services.mcp_connect import (
    connect as mcp_connect_exec,
    disconnect as mcp_disconnect_exec,
    get_status as mcp_get_status,
)
from fastapi import Request as _Request


@router.get("/mcp/status")
async def get_mcp_status():
    """Return Claude Desktop connection status (reads config from disk)."""
    return mcp_get_status()


class McpConnectBody(BaseModel):
    confirm: bool = False
    replace_broken: bool = False


@router.post("/mcp/connect")
async def post_mcp_connect(body: McpConnectBody, request: _Request):
    """Plan (confirm=false) or execute (confirm=true) adding the MCP entry to Claude Desktop config."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", ""):
        raise HTTPException(status_code=403, detail="MCP connect is only allowed from localhost")
    result = mcp_connect_exec(confirm=body.confirm, replace_broken=body.replace_broken)
    if not body.confirm and "planned" in result:
        return result
    if not result.get("ok") and not body.confirm:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.delete("/mcp/connect")
async def delete_mcp_connect(request: _Request):
    """Remove the yt-summarizer entry from Claude Desktop config."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", ""):
        raise HTTPException(status_code=403, detail="MCP disconnect is only allowed from localhost")
    return mcp_disconnect_exec()
