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
from services.stage_control import TRANSCRIBE_CANCEL, StageCancelled
from services.stage_progress import ProgressWriter
from services.subtitle_extractor import extract_subtitles
from sqlalchemy import text

from services.video_service import get_app_setting, get_result, replace_subtitles_after_reextract

STOPPED_MESSAGE = "Re-extract stopped"
FILE_GONE = "The uploaded file is no longer on disk (deleted by the auto-delete setting?): upload it again to re-transcribe"
REEXTRACT_STAGE = "reextract"       # the name inside a queue item's pipeline_stages


class ReextractFailed(RuntimeError):
    """The re-extract could not be done; the message is what the queue item shows. Nothing was replaced."""


def run_stage_of(url: str | None) -> str:
    """The stage a re-extract of this video records its run under: an uploaded file is re-transcribed, a YouTube video re-extracted."""
    return "transcribe" if (url or "").startswith(file_stt.LOCAL_PREFIX) else "extract"


async def enqueue_reextract(db, video_id: str, db_video_id: str, url: str, language: str, model: str | None) -> int | None:
    """Queue the re-extract of a video that is in History. Returns the queue item's id, or None when a re-extract of this video is
    already queued or running (nothing is added). One statement checks and inserts, so simultaneous requests give one item. The
    stage's run opens at once (status "processing" on the request, decision 3); it carries the speech-to-text model asked for."""
    from services import stage_runs
    res = await db.execute(
        text("INSERT INTO processing_queue (url, video_id, db_video_id, status, pipeline_stages, language, added_at, sort_order) "
             "SELECT :url, :vid, :dbid, 'pending', :stages, :lang, datetime('now'), "
             "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM processing_queue) "
             "WHERE NOT EXISTS (SELECT 1 FROM processing_queue WHERE video_id = :vid AND status IN ('pending', 'processing') "
             "AND pipeline_stages LIKE '%\"reextract\"%')"),
        {"url": url, "vid": video_id, "dbid": db_video_id, "stages": '["reextract"]', "lang": language},
    )
    if res.rowcount != 1:
        return None                         # nothing was inserted, so there is nothing to roll back
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


async def release_reextract(db, video_id: str, url: str | None) -> None:
    """A queued re-extract will not run (Remove, Clear pending, Stop): its run row, opened on the request, is cancelled so nothing
    stays 'processing' without an owner."""
    from services import stage_runs
    await stage_runs.cancel(db, video_id, run_stage_of(url))
    await db.commit()


async def stop_reextract(db, video_id: str) -> str:
    """Stop button: "stopped" (a queued re-extract was removed), "stopping" (a running one was told to stop) or "none". Either way
    nothing is replaced: the saved subtitles and what was made from them stay."""
    from services.queue_service import delete_item
    row = (await db.execute(
        text("SELECT id, status, url FROM processing_queue WHERE video_id = :v AND status IN ('pending', 'processing') "
             "AND pipeline_stages LIKE '%\"reextract\"%' ORDER BY id DESC LIMIT 1"), {"v": video_id},
    )).first()
    if row is None:
        return "none"
    if row[1] == "processing":
        TRANSCRIBE_CANCEL.add(video_id)
        return "stopping"
    if await delete_item(db, row[0]) == "deleted":                         # (releases the run too)
        return "stopped"
    TRANSCRIBE_CANCEL.add(video_id)          # it started in the meantime: tell the running one
    return "stopping"


async def reextract_progress_text(db, video_id: str) -> str | None:
    """The page's "retranscribe_progress" while a re-extract is queued or running: "waiting in the queue", "starting…", or the live
    "segment 12 · 40%" from the run row's counters. None when no re-extract is queued or running."""
    import json
    row = (await db.execute(
        text("SELECT status, url FROM processing_queue WHERE video_id = :v AND status IN ('pending', 'processing') "
             "AND pipeline_stages LIKE '%\"reextract\"%' ORDER BY id DESC LIMIT 1"), {"v": video_id},
    )).first()
    if row is None:
        return None
    if row[0] == "pending":
        return "waiting in the queue"
    run = (await db.execute(
        text("SELECT progress_done, progress_total, meta FROM processing_stages WHERE video_id = :v AND stage = :s "
             "AND status = 'processing' ORDER BY id DESC LIMIT 1"), {"v": video_id, "s": run_stage_of(row[1])},
    )).first()
    if run is None or not run[1]:
        return "starting…"
    try:
        segments = (json.loads(run[2]) if run[2] else {}).get("segments")
    except (TypeError, ValueError):
        segments = None
    return file_stt.transcribe_text(run[0], run[1], segments)


async def run_queued_reextract(item: dict) -> dict:
    """Run one queued re-extract (called by the queue worker). Returns {"video_id", "db_video_id"}; raises ReextractFailed."""
    from models.database import AsyncSessionLocal
    from services import stage_runs
    video_id = item["video_id"]
    async with AsyncSessionLocal() as db:
        fmt = await get_result(db, video_id)
        stage = run_stage_of(fmt["url"] if fmt else item.get("url"))
        model = (await db.execute(
            text("SELECT model FROM processing_stages WHERE video_id = :v AND stage = :s AND status = 'processing' "
                 "ORDER BY id DESC LIMIT 1"), {"v": video_id, "s": stage},
        )).scalar()
    async with AsyncSessionLocal() as db:
        if model is None and stage == "transcribe":
            model = await get_app_setting(db, "stt_model") or "base"
        await stage_runs.begin(db, video_id, stage, model, item["id"])      # a retried item gets its new run here
        await db.commit()
    try:
        outcome = await run_reextract(video_id, item.get("language") or "auto", model)
    except StageCancelled:
        await _record(video_id, stage, "cancelled")
        raise
    except ReextractFailed as exc:
        await _record(video_id, stage, "failed", error=str(exc), model=model)
        raise
    finally:
        TRANSCRIBE_CANCEL.discard(video_id)      # a Stop that came too late must not stop the next run
    await _record(video_id, stage, "done", model=outcome.get("model"), device=outcome.get("device"), started_at=outcome.get("started_at"))
    return {"video_id": video_id, "db_video_id": item.get("db_video_id")}


async def _record(video_id: str, stage: str, how: str, **kw) -> None:
    """Write the end of the run row: how = "done" | "failed" | "cancelled". A failure to write must not hide the real outcome."""
    from models.database import AsyncSessionLocal
    from services import stage_runs
    try:
        async with AsyncSessionLocal() as db:
            if how == "done":
                await stage_runs.finish(db, video_id, stage, model=kw.get("model"), started_at=kw.get("started_at"),
                                        meta={"device": kw["device"]} if kw.get("device") else None)
            elif how == "failed":
                await stage_runs.fail(db, video_id, stage, kw.get("error"), model=kw.get("model"))
            else:
                await stage_runs.cancel(db, video_id, stage)
            await db.commit()
    except Exception:  # noqa: BLE001
        _reextract_logger.exception("could not record the %s of the re-extract of %s", how, video_id)

_reextract_logger = logging.getLogger("api.reextract")



async def run_reextract(video_id: str, language: str = "auto", model: str | None = None) -> dict:
    """Re-extract subtitles for an existing video (for local:// URLs: re-run the speech-to-text on the saved upload).
    Overwrites formatted_text + chapters in place and invalidates what was made from the old text - only when it worked; any failure
    raises ReextractFailed and replaces nothing. Returns {"model", "device", "started_at"} for a transcription, {} for an extraction."""
    import glob as _glob
    from models.database import AsyncSessionLocal

    writer: ProgressWriter | None = None
    try:
        if video_id in TRANSCRIBE_CANCEL:
            TRANSCRIBE_CANCEL.discard(video_id)
            raise StageCancelled(STOPPED_MESSAGE)        # Stop came before the work began
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
            writer = ProgressWriter(video_id, "transcribe", "s")     # seconds done / total, on the stage's run row (decision 2)

            def _on_retranscribe_progress(n: int, cur_s: float = 0.0, tot_s: float = 0.0) -> None:
                if video_id in TRANSCRIBE_CANCEL:
                    raise file_stt.TranscriptionStopped(STOPPED_MESSAGE)   # Stop: the engine ends after the segment in hand
                writer.update(int(cur_s), int(tot_s), {"segments": n})

            transcription = await asyncio.to_thread(
                _transcribe, audio_path,
                language=language,
                model=stt_model,
                device=stt_device,
                cache_path=stt_cache_path,
                on_progress=_on_retranscribe_progress,
            )
            await writer.close()                                   # the last counters are on the row before the run ends
            if video_id in TRANSCRIBE_CANCEL:
                TRANSCRIBE_CANCEL.discard(video_id)
                raise StageCancelled(STOPPED_MESSAGE)        # Stop pressed (decision 1): nothing is replaced
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
            return {"model": stt_model, "device": actual_device, "started_at": transcription_started_at}

        # YouTube / standard yt-dlp path
        async with AsyncSessionLocal() as db:
            cookies_path = await get_app_setting(db, "cookies_path")
            ytdlp_path = await get_app_setting(db, "ytdlp_path") or "yt-dlp"

        _reextract_logger.info("reextract: starting video_id=%s url=%s language=%s", video_id, url, language)
        extraction = await asyncio.to_thread(
            extract_subtitles, url, language, cookies_path, ytdlp_path
        )
        if video_id in TRANSCRIBE_CANCEL:
            TRANSCRIBE_CANCEL.discard(video_id)
            raise StageCancelled(STOPPED_MESSAGE)            # Stop pressed while yt-dlp ran: its result is thrown away
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
        return {}
    except (ReextractFailed, StageCancelled):
        raise
    except Exception as exc:
        _reextract_logger.exception("reextract: unexpected error video_id=%s", video_id)
        raise ReextractFailed(str(exc)[:500]) from exc
    finally:
        if writer is not None:
            await writer.close()                             # on every way out: no write after the run is over
