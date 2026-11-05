"""Re-extract subtitles (YouTube) or re-transcribe (uploaded file) of a video that is already in History (NS-11 stage 6).

Moved here from routers/result.py (it was a BackgroundTask there); later stage-6 commits turn it into a queue stage.
"""
from __future__ import annotations

import asyncio
import logging
import os

from services import file_stt
from services.subtitle_extractor import extract_subtitles
from services.video_service import get_app_setting, get_result, replace_subtitles_after_reextract

_reextract_logger = logging.getLogger("api.reextract")

# Videos currently being re-extracted (set of video_id)
_REEXTRACT_SET: set[str] = set()
# Live re-transcription progress: {video_id: progress_text}
_RETRANSCRIBE_PROGRESS: dict[str, str] = {}


async def run_reextract(video_id: str, language: str = "auto", model: str | None = None) -> None:
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
            uploads_dir = file_stt.uploads_dir()
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
