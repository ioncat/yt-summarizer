"""Transcription of an uploaded audio / video file: the work behind POST /api/process/file (NS-11 stage 5).

The upload is a queue item (url "local://<original file name>", video_id "file-xxxxxxxx", db_video_id = the placeholder video of
its task, stages ["transcribe"]); the queue worker runs it with run_queued_file(). The saved upload is found again by its id.
"""
from __future__ import annotations

import asyncio
import glob
import os

from sqlalchemy import text

from services import stage_runs
from services.stage_control import TRANSCRIBE_CANCEL, StageCancelled
from services.stage_progress import ProgressWriter
from services.video_service import complete_task, get_app_setting, update_task_failed

LOCAL_PREFIX = "local://"


class FileTranscriptionFailed(RuntimeError):
    """The transcription of an upload failed; the message is what the task and the queue item show."""


class TranscriptionStopped(Exception):
    """Raised inside the speech-to-text progress callback when Stop was pressed: the engine's own error handling turns it into
    a failed result, and the runner then recognises the Stop by the flag."""

STOPPED_MESSAGE = "Transcription stopped"


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
    """Queue the transcription of an uploaded file. Returns the queue item's id. The stage's run row opens at once (status
    "processing" on the request, NS-11 decision 3), with the speech-to-text model that will be used."""
    res = await db.execute(
        text("INSERT INTO processing_queue (url, video_id, db_video_id, status, pipeline_stages, language, added_at, sort_order) "
             "VALUES (:url, :vid, :dbid, 'pending', :stages, :lang, datetime('now'), "
             "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM processing_queue))"),
        {"url": LOCAL_PREFIX + original_filename, "vid": local_video_id, "dbid": db_video_id,
         "stages": '["transcribe"]', "lang": language},
    )
    await stage_runs.begin(db, local_video_id, "transcribe", await get_app_setting(db, "stt_model") or "base", res.lastrowid)
    await db.commit()
    return res.lastrowid


async def _record(video_id: str, how: str, **kw) -> None:
    """Write the end of the stage's run: how = "done" | "failed" | "cancelled". Never raises into the caller's error path."""
    from models.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            if how == "done":
                await stage_runs.finish(db, video_id, "transcribe", model=kw.get("model"), started_at=kw.get("started_at"),
                                        meta={"device": kw["device"]} if kw.get("device") else None)
            elif how == "failed":
                await stage_runs.fail(db, video_id, "transcribe", kw.get("error"), model=kw.get("model"))
            else:
                await stage_runs.cancel(db, video_id, "transcribe")
            await db.commit()
    except Exception:  # noqa: BLE001 - the run row is a record; it must not hide the real outcome
        import logging
        logging.getLogger("api").exception("could not record the %s of the transcription of %s", how, video_id)


async def task_progress_text(db, task_id: str) -> str | None:
    """What /api/status/{task_id} says while the task's queue item (an upload, or a link typed on the Processing path) is waiting or
    running: "waiting in the queue"; for a running upload the live "segment 12 · 40%" built from the run row's counters; for a running
    link "extracting subtitles…". None for a task with no queued item (or whose item is over), and for a re-extract's item."""
    import json
    row = (await db.execute(
        text("SELECT q.status, q.video_id, q.url FROM processing_queue q JOIN processing_tasks t ON t.video_id = q.db_video_id "
             "WHERE t.id = :t AND q.pipeline_stages NOT LIKE '%\"reextract\"%' ORDER BY q.id DESC LIMIT 1"), {"t": task_id},
    )).first()
    if row is None:
        return None
    if row[0] == "pending":
        return "waiting in the queue"
    if row[0] != "processing":
        return None
    if not (row[2] or "").startswith(LOCAL_PREFIX):
        return "extracting subtitles…"
    run = (await db.execute(
        text("SELECT progress_done, progress_total, meta FROM processing_stages WHERE video_id = :v AND stage = 'transcribe' "
             "AND status = 'processing' ORDER BY id DESC LIMIT 1"), {"v": row[1]},
    )).first()
    if run is None or not run[1]:
        return "transcribing…"
    try:
        segments = (json.loads(run[2]) if run[2] else {}).get("segments")
    except (TypeError, ValueError):
        segments = None
    return transcribe_text(run[0], run[1], segments)


def transcribe_text(done: int, total: int, segments: int | None) -> str:
    """"segment 12 · 40%" (seconds done / total of the audio, segments so far) - the page's and the queue's progress text."""
    pct = f" · {int(done / total * 100)}%" if total and total > 0 else ""
    return f"segment {segments}{pct}" if segments is not None else f"transcribing{pct}"


async def release_upload(db, video_id: str, db_video_id: str | None, message: str) -> None:
    """A queued upload will not be transcribed (Stop, Remove): its task ends failed with `message` and its run row is cancelled,
    so nothing stays 'processing' without an owner."""
    task_id = (await db.execute(
        text("SELECT id FROM processing_tasks WHERE video_id = :v AND status = 'pending' ORDER BY started_at DESC LIMIT 1"),
        {"v": db_video_id},
    )).scalar() if db_video_id else None
    if task_id:
        await update_task_failed(db, task_id, message)
    await stage_runs.cancel(db, video_id, "transcribe")
    await db.commit()


async def stop_upload(db, video_id: str) -> str:
    """Stop button: "stopped" (a queued item was removed), "stopping" (a running one was told to stop) or "none"."""
    from services.cancel import cancel_video_jobs, outcome_of
    return outcome_of(await cancel_video_jobs(db, video_id, "transcribe", STOPPED_MESSAGE))      # (NS-16: the one cancel path)


async def run_queued_file(item: dict) -> dict:
    """Run one queued upload (called by the queue worker). Returns {"video_id", "db_video_id"}; raises FileTranscriptionFailed.
    The stage's run row is opened (a queue item that was reset or retried gets a new run), then closed done / failed."""
    from models.database import AsyncSessionLocal

    video_id, db_video_id = item["video_id"], item.get("db_video_id")
    original_filename = item["url"][len(LOCAL_PREFIX):]
    async with AsyncSessionLocal() as db:
        await stage_runs.begin(db, video_id, "transcribe", await get_app_setting(db, "stt_model") or "base", item["id"])
        await db.commit()
    try:
        outcome = await _run_queued_file(item, video_id, db_video_id, original_filename)
    except StageCancelled:
        await _record(video_id, "cancelled")
        raise
    except FileTranscriptionFailed as exc:
        await _record(video_id, "failed", error=str(exc))
        raise
    finally:
        TRANSCRIBE_CANCEL.discard(video_id)   # a Stop that came too late must not stop the next run of this upload
    await _record(video_id, "done", model=outcome["model"], device=outcome["device"], started_at=outcome["started_at"])
    return {"video_id": video_id, "db_video_id": db_video_id}


async def _run_queued_file(item: dict, video_id: str, db_video_id: str | None, original_filename: str) -> dict:
    from models.database import AsyncSessionLocal
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
    return await run_file_transcription(task_id, video_id, path, original_filename, item.get("language") or "auto")


async def _stop_now(task_id: str, local_video_id: str) -> None:
    """Stop was pressed: the task and the queue item say so, nothing is saved, so a saved transcript stays as it was."""
    from models.database import AsyncSessionLocal
    TRANSCRIBE_CANCEL.discard(local_video_id)
    async with AsyncSessionLocal() as db:
        await update_task_failed(db, task_id, STOPPED_MESSAGE)
    raise StageCancelled(STOPPED_MESSAGE)


async def run_file_transcription(
    task_id: str,
    local_video_id: str,
    audio_path: str,
    original_filename: str,
    language: str = "auto",
) -> dict:
    """Transcribe a locally uploaded audio / video file and store the result. A failure marks the task failed and raises
    FileTranscriptionFailed (the queue item then ends failed with the same message). Nothing is stored unless the
    transcription worked and found speech, so a failed or empty run leaves any saved transcript as it was.
    Returns {"model", "device", "started_at"} of the run."""
    from models.database import AsyncSessionLocal
    from services.transcriber import transcribe as _transcribe, DEFAULT_CACHE_PATH
    from services.text_formatter import format_subtitles
    from services.subtitle_extractor import ExtractionResult, SubtitleEntry, VideoMetadata

    writer: ProgressWriter | None = None
    try:
        if local_video_id in TRANSCRIBE_CANCEL:
            await _stop_now(task_id, local_video_id)         # Stop came before the work began
        from datetime import datetime as _datetime
        async with AsyncSessionLocal() as db:
            stt_model = await get_app_setting(db, "stt_model") or "base"
            stt_device = await get_app_setting(db, "stt_device") or "auto"
            stt_cache_path = await get_app_setting(db, "stt_cache_path") or DEFAULT_CACHE_PATH

        transcription_started_at = _datetime.utcnow()
        writer = ProgressWriter(local_video_id, "transcribe", "s")   # seconds done / total, on the stage's run row

        def _on_stt_progress(n: int, cur_s: float = 0.0, tot_s: float = 0.0) -> None:
            if local_video_id in TRANSCRIBE_CANCEL:
                raise TranscriptionStopped(STOPPED_MESSAGE)   # Stop: the engine ends the run after the segment in hand
            writer.update(int(cur_s), int(tot_s), {"segments": n})

        transcription = await asyncio.to_thread(
            _transcribe, audio_path,
            language=language,
            model=stt_model,
            device=stt_device,
            cache_path=stt_cache_path,
            on_progress=_on_stt_progress,
        )
        await writer.close()                                         # the last counters are on the row before the run ends

        if local_video_id in TRANSCRIBE_CANCEL:
            await _stop_now(task_id, local_video_id)   # Stop pressed (decision 1): nothing is saved

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
        if not entries:
            # decision 5: a silent skip becomes an explicit failure; no empty "transcript" is saved
            message = "No speech was found in the file"
            async with AsyncSessionLocal() as db:
                await update_task_failed(db, task_id, message)
            raise FileTranscriptionFailed(message)
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
        return {"model": stt_model, "device": actual_device, "started_at": transcription_started_at}

    except (FileTranscriptionFailed, StageCancelled):
        raise
    except Exception as e:
        async with AsyncSessionLocal() as db:
            await update_task_failed(db, task_id, str(e))
        raise FileTranscriptionFailed(str(e)) from e
    finally:
        if writer is not None:
            await writer.close()                             # on every way out: no write after the run is over
