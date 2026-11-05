"""Re-extract subtitles (YouTube) or re-transcribe (uploaded file) of a video that is already in History (NS-11 stage 6).

A re-extract is a queue item (stages ["reextract"], url = the video's url, video_id and db_video_id = the video in History, the
language in the item, the speech-to-text model asked for in the stage's run row); the queue worker runs it with run_queued_reextract().
The data is replaced IN PLACE (decision 7), and only by a run that worked; every failure is explicit (ReextractFailed with the
message the queue item shows) and leaves the saved subtitles, the cleaned text, the summary and the map as they were.
"""
from __future__ import annotations

import asyncio
import logging
import os

from services import file_stt
from services.subtitle_extractor import extract_subtitles
from sqlalchemy import text

from services.video_service import get_app_setting, get_result, replace_subtitles_after_reextract

FILE_GONE = "The uploaded file is no longer on disk (deleted by the auto-delete setting?): upload it again to re-transcribe"
REEXTRACT_STAGE = "reextract"       # the name inside a queue item's pipeline_stages


class ReextractFailed(RuntimeError):
    """The re-extract could not be done; the message is what the queue item shows. Nothing was replaced."""


def run_stage_of(url: str | None) -> str:
    """The stage a re-extract of this video records its run under: an uploaded file is re-transcribed, a YouTube video re-extracted."""
    return "transcribe" if (url or "").startswith(file_stt.LOCAL_PREFIX) else "extract"


async def enqueue_reextract(db, video_id: str, db_video_id: str, url: str, language: str, model: str | None) -> int:
    """Queue the re-extract of a video that is in History. Returns the queue item's id. The stage's run opens at once (status
    "processing" on the request, decision 3); it carries the speech-to-text model that was asked for."""
    from services import stage_runs
    res = await db.execute(
        text("INSERT INTO processing_queue (url, video_id, db_video_id, status, pipeline_stages, language, added_at, sort_order) "
             "VALUES (:url, :vid, :dbid, 'pending', :stages, :lang, datetime('now'), "
             "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM processing_queue))"),
        {"url": url, "vid": video_id, "dbid": db_video_id, "stages": '["reextract"]', "lang": language},
    )
    run_model = model or (await get_app_setting(db, "stt_model") or "base" if run_stage_of(url) == "transcribe" else None)
    await stage_runs.begin(db, video_id, run_stage_of(url), run_model, res.lastrowid)
    await db.commit()
    return res.lastrowid


async def reextract_queued(db, video_id: str) -> bool:
    """Is a re-extract of this video waiting in the queue or running?"""
    return (await db.execute(
        text("SELECT 1 FROM processing_queue WHERE video_id = :v AND status IN ('pending', 'processing') "
             "AND pipeline_stages LIKE '%\"reextract\"%' LIMIT 1"), {"v": video_id},
    )).first() is not None


async def run_queued_reextract(item: dict) -> dict:
    """Run one queued re-extract (called by the queue worker). Returns {"video_id", "db_video_id"}; raises ReextractFailed."""
    from models.database import AsyncSessionLocal
    video_id = item["video_id"]
    async with AsyncSessionLocal() as db:
        fmt = await get_result(db, video_id)
        stage = run_stage_of(fmt["url"] if fmt else item.get("url"))
        model = (await db.execute(
            text("SELECT model FROM processing_stages WHERE video_id = :v AND stage = :s AND status = 'processing' "
                 "ORDER BY id DESC LIMIT 1"), {"v": video_id, "s": stage},
        )).scalar()
    await run_reextract(video_id, item.get("language") or "auto", model)
    return {"video_id": video_id, "db_video_id": item.get("db_video_id")}

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
                raise ReextractFailed("The video is not in History (deleted after the re-extract was queued?)")
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
                raise ReextractFailed(FILE_GONE)
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
                raise ReextractFailed(transcription.error_message or "Transcription failed")

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
            if not entries:
                # decision 5: a silent skip becomes a failure; the saved transcript (and what was made from it) is NOT replaced
                raise ReextractFailed("No speech was found in the file")
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
            raise ReextractFailed(extraction.error_message or "The subtitles could not be extracted")
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
    except ReextractFailed:
        raise
    except Exception as exc:
        _reextract_logger.exception("reextract: unexpected error video_id=%s", video_id)
        raise ReextractFailed(str(exc)[:500]) from exc
    finally:
        _REEXTRACT_SET.discard(video_id)
        _RETRANSCRIBE_PROGRESS.pop(video_id, None)
