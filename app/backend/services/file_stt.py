"""Transcription of an uploaded audio / video file: the work behind POST /api/process/file (NS-11 stage 5).

The upload is a queue item (url "local://<original file name>", video_id "file-xxxxxxxx", db_video_id = the placeholder video of
its task, stages ["transcribe"]); the queue worker runs it with run_queued_file(). The saved upload is found again by its id.
"""
from __future__ import annotations

import asyncio
import glob
import os

from sqlalchemy import text

from services.video_service import complete_task, get_app_setting, update_task_failed

LOCAL_PREFIX = "local://"

# Live STT progress for direct file-upload transcription tasks: {task_id: progress_text}
_FILE_TASK_PROGRESS: dict[str, str] = {}


class FileTranscriptionFailed(RuntimeError):
    """The transcription of an upload failed; the message is what the task and the queue item show."""


def uploads_dir() -> str:
    """Where uploaded files are saved (data/uploads next to the backend folder)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/uploads"))


def find_upload(local_video_id: str) -> str | None:
    """The saved upload of "file-xxxxxxxx": it is saved as <12 hex chars><extension> and the id keeps the first 8 of them."""
    key = local_video_id[len("file-"):] if local_video_id.startswith("file-") else local_video_id
    if not key:
        return None
    matches = sorted(glob.glob(os.path.join(glob.escape(uploads_dir()), glob.escape(key) + "*")))
    return matches[0] if matches else None


async def enqueue_local_file(db, local_video_id: str, db_video_id: str, original_filename: str, language: str) -> int:
    """Queue the transcription of an uploaded file. Returns the queue item's id."""
    res = await db.execute(
        text("INSERT INTO processing_queue (url, video_id, db_video_id, status, pipeline_stages, language, added_at, sort_order) "
             "VALUES (:url, :vid, :dbid, 'pending', :stages, :lang, datetime('now'), "
             "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM processing_queue))"),
        {"url": LOCAL_PREFIX + original_filename, "vid": local_video_id, "dbid": db_video_id,
         "stages": '["transcribe"]', "lang": language},
    )
    await db.commit()
    return res.lastrowid


async def run_queued_file(item: dict) -> dict:
    """Run one queued upload (called by the queue worker). Returns {"video_id", "db_video_id"}; raises FileTranscriptionFailed."""
    from models.database import AsyncSessionLocal

    video_id, db_video_id = item["video_id"], item.get("db_video_id")
    original_filename = item["url"][len(LOCAL_PREFIX):]
    async with AsyncSessionLocal() as db:
        task_id = (await db.execute(
            text("SELECT id FROM processing_tasks WHERE video_id = :v ORDER BY started_at DESC LIMIT 1"), {"v": db_video_id},
        )).scalar()
    if task_id is None:
        raise FileTranscriptionFailed("The upload's task is gone: upload the file again")
    path = find_upload(video_id)
    if path is None:
        message = "The uploaded file is no longer on disk (deleted by the auto-delete setting?): upload it again"
        async with AsyncSessionLocal() as db:
            await update_task_failed(db, task_id, message)
        raise FileTranscriptionFailed(message)
    await run_file_transcription(task_id, video_id, path, original_filename, item.get("language") or "auto")
    return {"video_id": video_id, "db_video_id": db_video_id}


async def run_file_transcription(
    task_id: str,
    local_video_id: str,
    audio_path: str,
    original_filename: str,
    language: str = "auto",
) -> None:
    """Transcribe a locally uploaded audio / video file and store the result. A failure marks the task failed and raises
    FileTranscriptionFailed (the queue item then ends failed with the same message)."""
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
            message = transcription.error_message or "Transcription failed"
            async with AsyncSessionLocal() as db:
                await update_task_failed(db, task_id, message)
            raise FileTranscriptionFailed(message)

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

    except FileTranscriptionFailed:
        raise
    except Exception as e:
        async with AsyncSessionLocal() as db:
            await update_task_failed(db, task_id, str(e))
        raise FileTranscriptionFailed(str(e)) from e
