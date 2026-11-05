"""Transcription of an uploaded audio / video file: the work behind POST /api/process/file (NS-11 stage 5).

Moved here unchanged from routers/process.py (it was a BackgroundTask there); later stage-5 commits turn it into a queue stage.
"""
from __future__ import annotations

import asyncio
import os

from services.video_service import complete_task, get_app_setting, update_task_failed

# Live STT progress for direct file-upload transcription tasks: {task_id: progress_text}
_FILE_TASK_PROGRESS: dict[str, str] = {}


async def run_file_transcription(
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
