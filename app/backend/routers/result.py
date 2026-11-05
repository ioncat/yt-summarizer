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
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from models.database import get_db
from services.subtitle_extractor import extract_subtitles, extract_video_id, validate_youtube_url, _ytdlp_cmd
from services.text_cleaner import clean_text
from services.text_summarizer import summarize_text, extract_notes, MAP_REDUCE_THRESHOLD
from services.text_mindmapper import generate_mindmap
from services.video_service import (
    delete_video,
    finish_cleanup,
    finish_mindmap,
    finish_summary,
    get_app_setting,
    get_result,
    get_stage_settings,
    replace_subtitles_after_reextract,
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
from services.ollama_options import begin_llm_run, llm_failure_reason
from routers.settings import _uploads_dir

logger = logging.getLogger("api")
_reextract_logger = logging.getLogger("api.reextract")

router = APIRouter()

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
        begin_llm_run(await get_app_setting(db, "llm_max_num_ctx"))

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
                    "retranscribe: failed video_id=%s model=%s language=%s device=%s error=%s",
                    video_id, stt_model, language, stt_device, transcription.error_message,
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
        from services.text_formatter import format_subtitles
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
        begin_llm_run(await get_app_setting(db, "llm_max_num_ctx"))

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
            await finish_summary(db, video_id, summary, mode=mode, chunks_count=chunks_count, started_at=started_at,
                                 error=llm_failure_reason())


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
        begin_llm_run(await get_app_setting(db, "llm_max_num_ctx"))
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

        await finish_mindmap(db, video_id, mindmap_md, error=llm_failure_reason())
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
