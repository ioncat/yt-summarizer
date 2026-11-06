"""Bulk URL queue: CRUD + asyncio background worker.

Worker runs as a single asyncio task (started in lifespan). Processes one item
at a time — Ollama cannot handle parallel heavy requests.

Status flow: pending → processing → done | partial | failed | skipped
(partial = the item ran to its end but one or more of its stages failed; the message names them - NS-25)
On backend restart: items stuck in 'processing' are reset to 'pending'.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import AsyncSessionLocal
from services.ollama_options import begin_llm_run, llm_failure_reason
from services import stage_runs
from services.extract_queue import release_task
from services.file_stt import LOCAL_PREFIX, release_upload, run_queued_file, transcribe_text
from services.reextract import release_reextract, run_queued_reextract
from services.stage_progress import ProgressWriter
from services.queue_by_id import STAGE_COLUMNS, release_stage_status
from services.stage_control import (
    CLEANUP_CANCEL, ITEM_CANCEL, MINDMAP_CANCEL, SUMMARY_CANCEL, StageCancelled,
)

logger = logging.getLogger("queue_service")

# Global stop flag — set to True to gracefully stop the worker loop
_WORKER_STOP = False

# In-memory progress per item_id: "paragraph 3/12", "chunk 5/20", etc.
_QUEUE_PROGRESS: dict[int, str] = {}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def get_duplicate_reasons(db: AsyncSession, video_ids: list[str]) -> dict[str, str]:
    """Why each id is a duplicate: "processed" (in History) or "in_queue" (pending / processing).

    An id that is both counts as "processed"."""
    if not video_ids:
        return {}

    placeholders = ", ".join(f":vid{i}" for i in range(len(video_ids)))
    params = {f"vid{i}": v for i, v in enumerate(video_ids)}

    # Already processed (exists in videos table, not a pending placeholder)
    done = await db.execute(
        text(
            f"SELECT video_id FROM videos WHERE video_id IN ({placeholders}) "
            f"AND url NOT LIKE '__pending__%%'"
        ),
        params,
    )
    found: dict[str, str] = {row[0]: "processed" for row in done.fetchall()}

    # Already in queue with pending/processing status
    in_queue = await db.execute(
        text(
            f"SELECT video_id FROM processing_queue "
            f"WHERE video_id IN ({placeholders}) AND status IN ('pending','processing')"
        ),
        params,
    )
    for row in in_queue.fetchall():
        if row[0]:
            found.setdefault(row[0], "in_queue")

    return found


# One INSERT that both checks and writes (NS-28 review): the sort order is taken inside the statement, and with
# `unique` the row is only inserted when no pending / processing row exists for that video_id. SQLite runs the
# statement under the write lock, so of two requests adding the same link at the same moment the second one sees the
# first one's row and inserts nothing (rowcount 0), instead of both passing a separate "is it queued?" check.
_INSERT_ITEM = (
    "INSERT INTO processing_queue (url, video_id, status, pipeline_stages, language, added_at, sort_order) "
    "SELECT :url, :vid, 'pending', :stages, :language, datetime('now'), "
    "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM processing_queue)"
)
_NOT_QUEUED = (
    " WHERE NOT EXISTS (SELECT 1 FROM processing_queue "
    "WHERE video_id = :vid AND status IN ('pending', 'processing'))"
)


async def add_items(
    db: AsyncSession,
    urls: list[str],
    pipeline_stages: list[str],
    language: str | None = None,
) -> list[int]:
    """Insert queue items without any duplicate check (force). Returns list of inserted IDs.
    video_id (YouTube ID) is stored at insert time for dedup checks.
    language=None means auto-detect; pass explicit code (e.g. "ru") to force.
    """
    from services.subtitle_extractor import extract_video_id as _extract_video_id

    stages_json = json.dumps(pipeline_stages)
    ids: list[int] = []
    for url in urls:
        vid = _extract_video_id(url)  # always valid here (caller already validated)
        res = await db.execute(
            text(_INSERT_ITEM),
            {"url": url, "vid": vid, "stages": stages_json, "language": language},
        )
        ids.append(res.lastrowid)

    await db.commit()
    return ids


async def add_items_unique(
    db: AsyncSession,
    urls: list[str],
    pipeline_stages: list[str],
    language: str | None = None,
) -> tuple[list[int], list[tuple[str, str]]]:
    """Insert queue items, each only if its video is not already pending / processing, atomically.

    Returns (inserted ids, [(url, video_id)] skipped because the video was queued meanwhile).
    """
    from services.subtitle_extractor import extract_video_id as _extract_video_id

    stages_json = json.dumps(pipeline_stages)
    ids: list[int] = []
    skipped: list[tuple[str, str]] = []
    for url in urls:
        vid = _extract_video_id(url)
        res = await db.execute(
            text(_INSERT_ITEM + _NOT_QUEUED),
            {"url": url, "vid": vid, "stages": stages_json, "language": language},
        )
        if res.rowcount == 1:
            ids.append(res.lastrowid)
        else:
            skipped.append((url, vid))

    await db.commit()
    return ids, skipped


async def get_queue(db: AsyncSession) -> list[dict]:
    """Return all queue items ordered by sort_order + added_at."""
    result = await db.execute(
        text(
            "SELECT id, url, video_id, db_video_id, status, pipeline_stages, "
            "error_message, added_at, started_at, finished_at, sort_order, language "
            "FROM processing_queue ORDER BY sort_order, added_at, id"
        )
    )
    rows = result.fetchall()
    items = [
        {
            "id": r[0],
            "url": r[1],
            "video_id": r[2],
            "db_video_id": r[3],
            "status": r[4],
            "pipeline_stages": json.loads(r[5]) if r[5] else ["extract"],
            "error_message": r[6],
            "added_at": r[7],
            "started_at": r[8],
            "finished_at": r[9],
            "sort_order": r[10],
            "progress": _QUEUE_PROGRESS.get(r[0]),
            "language": r[11],
        }
        for r in rows
    ]
    running = [i["id"] for i in items if i["status"] == "processing"]
    if running:
        live = await _live_progress(db, running)
        for item in items:
            if item["id"] in live:
                item["progress"] = live[item["id"]]          # the counters of the stage the item is in, from its run row
    for item in items:
        if item["status"] == "partial":
            # can Retry still do something? (a re-extract or a deleted video takes the failed runs away)
            item["retryable"] = await _partial_retryable(db, item["id"], item["pipeline_stages"], item["video_id"])
    return items


async def _live_progress(db: AsyncSession, item_ids: list[int]) -> dict[int, str]:
    """{queue item id: "cleanup: paragraph 3/10"} for the running items whose stage has written counters."""
    marks = ", ".join(f":i{n}" for n in range(len(item_ids)))
    out: dict[int, str] = {}
    for item_id, stage, done, total, meta in (await db.execute(
        text("SELECT queue_item_id, stage, progress_done, progress_total, meta FROM processing_stages "
             f"WHERE status = 'processing' AND progress_total IS NOT NULL AND queue_item_id IN ({marks}) ORDER BY id"),
        {f"i{n}": i for n, i in enumerate(item_ids)},
    )).fetchall():
        try:
            unit = (json.loads(meta) if meta else {}).get("unit")
        except (TypeError, ValueError):
            unit = None
        if stage == "transcribe":
            try:
                segments = (json.loads(meta) if meta else {}).get("segments")
            except (TypeError, ValueError):
                segments = None
            out[item_id] = "transcribe: " + transcribe_text(done, total, segments)
        else:
            out[item_id] = f"{stage}: {unit + ' ' if unit else ''}{done}/{total}"
    return out


async def get_queue_counts(db: AsyncSession) -> dict[str, int]:
    """Return counts per status — for nav badge."""
    result = await db.execute(
        text("SELECT status, COUNT(*) FROM processing_queue GROUP BY status")
    )
    counts: dict[str, int] = {r[0]: r[1] for r in result.fetchall()}
    return counts


async def delete_item(db: AsyncSession, item_id: int, upload_message: str = "Removed from the queue") -> str:
    """Delete a pending item. Returns 'deleted' | 'not_found' | 'conflict'. `upload_message` is what the task of a removed
    upload shows (Stop says "Transcription stopped")."""
    result = await db.execute(
        text("SELECT status, video_id, pipeline_stages, url, db_video_id FROM processing_queue WHERE id = :id"),
        {"id": item_id},
    )
    row = result.fetchone()
    if not row:
        return "not_found"
    if row[0] == "processing":
        return "conflict"
    await db.execute(
        text("DELETE FROM processing_queue WHERE id = :id"), {"id": item_id}
    )
    await db.commit()
    if row[1]:
        for stage in STAGE_COLUMNS:
            if f'"{stage}"' in (row[2] or ""):
                await release_stage_status(db, row[1], stage)  # it was to run this stage: no status stuck 'processing'
    if row[0] == "pending" and (row[3] or "").startswith(LOCAL_PREFIX) and '"reextract"' not in (row[2] or ""):
        # an upload that will not be transcribed after all: its task must not stay pending for ever (NS-11 stage 5)
        await release_upload(db, row[1], row[4], upload_message)
    if row[0] == "pending" and '"reextract"' in (row[2] or ""):
        await release_reextract(db, row[1], row[3])       # a re-extract that will not run: its run row ends (NS-11 stage 6)
    if row[0] == "pending" and not (row[3] or "").startswith(LOCAL_PREFIX) and '"reextract"' not in (row[2] or ""):
        await release_task(db, row[1], row[4], upload_message)    # a link typed on the Processing path: its task must not stay pending
    return "deleted"


async def clear_pending(db: AsyncSession) -> int:
    """Delete all pending items. Returns deleted count."""
    removed = [
        (r[0], r[1] or "") for r in (await db.execute(
            text("SELECT video_id, pipeline_stages FROM processing_queue WHERE status = 'pending' "
                 "AND video_id IS NOT NULL"),
        )).fetchall()
    ]
    uploads = (await db.execute(
        text("SELECT video_id, db_video_id FROM processing_queue WHERE status = 'pending' AND url LIKE 'local://%' "
             "AND pipeline_stages NOT LIKE '%\"reextract\"%' AND video_id IS NOT NULL"),
    )).fetchall()
    link_tasks = (await db.execute(
        text("SELECT video_id, db_video_id FROM processing_queue WHERE status = 'pending' AND db_video_id IS NOT NULL "
             "AND url NOT LIKE 'local://%' AND pipeline_stages NOT LIKE '%\"reextract\"%'"),
    )).fetchall()
    reextracts = (await db.execute(
        text("SELECT video_id, url FROM processing_queue WHERE status = 'pending' AND pipeline_stages LIKE '%\"reextract\"%' "
             "AND video_id IS NOT NULL"),
    )).fetchall()
    result = await db.execute(
        text("DELETE FROM processing_queue WHERE status = 'pending'")
    )
    await db.commit()
    for stage in STAGE_COLUMNS:
        for video_id in {v for v, stages in removed if f'"{stage}"' in stages}:
            await release_stage_status(db, video_id, stage)  # that stage will never run: no stuck 'processing'
    for video_id, db_video_id in uploads:
        await release_upload(db, video_id, db_video_id, "Removed from the queue")   # the uploads' tasks end failed, not pending
    for video_id, url in reextracts:
        await release_reextract(db, video_id, url)                                  # the re-extracts' runs end (NS-11 stage 6)
    for video_id, db_video_id in link_tasks:
        await release_task(db, video_id, db_video_id, "Removed from the queue")     # the Processing path's tasks end failed
    return result.rowcount


async def clear_failed(db: AsyncSession) -> int:
    """Delete all failed items, and the partial items that are stuck (nothing left to retry: their video is gone, or has no
    failed stage any more). A partial item that can still be retried is kept. Returns deleted count."""
    result = await db.execute(
        text("DELETE FROM processing_queue WHERE status = 'failed'")
    )
    count = result.rowcount
    for item_id, video_id, stages in (await db.execute(
        text("SELECT id, video_id, pipeline_stages FROM processing_queue WHERE status = 'partial'"),
    )).fetchall():
        if not await _partial_retryable(db, item_id, json.loads(stages) if stages else ["extract"], video_id):
            count += (await db.execute(text("DELETE FROM processing_queue WHERE id = :id"), {"id": item_id})).rowcount
    await db.commit()
    return count


async def _item_failed_stages(db: AsyncSession, item_id: int, stages: list[str]) -> list[tuple[str, str | None]]:
    """The stages of this queue item whose NEWEST run ended failed, as [(stage, error text)] in pipeline order."""
    newest: dict[str, tuple[str, str | None]] = {}
    for stage, status, error in (await db.execute(
        text("SELECT stage, status, error_text FROM processing_stages WHERE queue_item_id = :id ORDER BY id"),
        {"id": item_id},
    )).fetchall():
        newest[stage] = (status, error)
    return [(s, newest[s][1]) for s in stages if s in newest and newest[s][0] == "failed"]


async def _partial_retryable(db: AsyncSession, item_id: int, stages: list[str], video_id: str | None) -> bool:
    """A partial item can be retried while its video is in History and one of its stages still ends failed."""
    if video_id:
        gone = (await db.execute(
            text("SELECT 1 FROM videos WHERE video_id = :v AND url NOT LIKE '__pending__%' LIMIT 1"), {"v": video_id},
        )).first() is None
        if gone:
            return False
    return bool(await _item_failed_stages(db, item_id, stages))


async def _reset_to_pending(db: AsyncSession, item_id: int, status: str, stages_json: str) -> None:
    """Back to pending. A partial item restarts ONLY the stages that failed (the rest is done and in History)."""
    if status == "partial":
        await db.execute(
            text("UPDATE processing_queue SET status = 'pending', error_message = NULL, started_at = NULL, "
                 "finished_at = NULL, pipeline_stages = :stages WHERE id = :id"),
            {"stages": stages_json, "id": item_id},
        )
    else:
        await db.execute(
            text("UPDATE processing_queue SET status = 'pending', error_message = NULL, started_at = NULL, "
                 "finished_at = NULL WHERE id = :id"),
            {"id": item_id},
        )


async def _retry(db: AsyncSession, item_id: int, status: str, pipeline_stages: str | None,
                 video_id: str | None = None) -> bool:
    """Reset one failed / partial item. False when a partial item has no failed stage left to run (nothing changes)."""
    stages_json = pipeline_stages or json.dumps(["extract"])
    if status == "partial":
        if not await _partial_retryable(db, item_id, json.loads(stages_json), video_id):
            return False
        stages_json = json.dumps([s for s, _ in await _item_failed_stages(db, item_id, json.loads(stages_json))])
    await _reset_to_pending(db, item_id, status, stages_json)
    return True


async def retry_item(db: AsyncSession, item_id: int) -> str:
    """Reset a failed or partial item back to pending.

    Returns 'not_found' | 'not_failed' | 'nothing_left' (a partial item with no failed stage left to run) | 'ok'."""
    result = await db.execute(
        text("SELECT status, pipeline_stages, video_id FROM processing_queue WHERE id = :id"),
        {"id": item_id},
    )
    row = result.fetchone()
    if not row:
        return "not_found"
    if row[0] not in ("failed", "partial"):
        return "not_failed"
    if not await _retry(db, item_id, row[0], row[1], row[2]):
        return "nothing_left"
    await db.commit()
    return "ok"


async def retry_all_failed(db: AsyncSession) -> int:
    """Reset all failed and partial items to pending (a partial one restarts only its failed stages). Returns count."""
    rows = (await db.execute(
        text("SELECT id, status, pipeline_stages, video_id FROM processing_queue WHERE status IN ('failed', 'partial')"),
    )).fetchall()
    count = 0
    for item_id, status, stages, video_id in rows:
        if await _retry(db, item_id, status, stages, video_id):
            count += 1
    await db.commit()
    return count


# ---------------------------------------------------------------------------
# Worker helpers
# ---------------------------------------------------------------------------

async def _reset_stuck_items() -> None:
    """On startup: reset any 'processing' items back to 'pending'."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                "UPDATE processing_queue SET status = 'pending', started_at = NULL "
                "WHERE status = 'processing'"
            )
        )
        if result.rowcount:
            logger.warning(
                "Queue worker: reset %d stuck 'processing' items to 'pending'",
                result.rowcount,
            )
        await db.commit()


async def _pick_next() -> dict | None:
    """Pick the oldest pending item."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                "SELECT id, url, pipeline_stages, language, video_id, db_video_id FROM processing_queue "
                "WHERE status = 'pending' ORDER BY sort_order, added_at LIMIT 1"
            )
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "url": row[1],
            "pipeline_stages": json.loads(row[2]) if row[2] else ["extract"],
            "language": row[3],
            "video_id": row[4],
            "db_video_id": row[5],
        }


async def _video_exists(video_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("SELECT 1 FROM videos WHERE video_id = :v AND url NOT LIKE '__pending__%' LIMIT 1"),
            {"v": video_id},
        )
        return row.first() is not None


async def _set_processing(item_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE processing_queue SET status = 'processing', started_at = datetime('now') "
                "WHERE id = :id"
            ),
            {"id": item_id},
        )
        await db.commit()


async def _set_done(item_id: int, video_id: str | None, db_video_id: str | None) -> None:
    _QUEUE_PROGRESS.pop(item_id, None)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE processing_queue SET status = 'done', finished_at = datetime('now'), "
                "video_id = :vid, db_video_id = :dbvid WHERE id = :id"
            ),
            {"vid": video_id, "dbvid": db_video_id, "id": item_id},
        )
        await db.commit()


_STAGE_LABELS = {"extract": "Subtitles", "transcribe": "Speech-to-text", "cleanup": "Cleanup", "summary": "Summary",
                 "mindmap": "Mind map", "download": "Download"}


async def _release_unrun_stages(video_id: str | None, url: str, stages: list[str], reason: str, cancelled: bool = False) -> None:
    """Give the status back of the stages of a stopped / failed item that never ran: idle after a cancel, failed after an error.
    Call it AFTER the item is marked skipped / failed: a stage held by another pending / processing item is left alone."""
    wanted = [s for s in STAGE_COLUMNS if s in stages]
    if not wanted:
        return
    if not video_id:
        from services.subtitle_extractor import extract_video_id
        video_id = extract_video_id(url)
    if not video_id:
        return
    for stage in wanted:
        try:
            async with AsyncSessionLocal() as db:
                await release_stage_status(
                    db, video_id, stage, status=None if cancelled else "failed",
                    error=None if cancelled else f"{_STAGE_LABELS[stage]} did not run: an earlier stage failed ({reason[:300]})")
        except Exception:  # noqa: BLE001 - the item is already marked failed; this is only tidying
            logger.exception("Queue worker: could not release the %s status of %s", stage, video_id)


async def _set_partial(item_id: int, video_id: str | None, db_video_id: str | None, message: str) -> None:
    """The item ran to its end but a stage failed: not 'done'. The message names the failed stages."""
    _QUEUE_PROGRESS.pop(item_id, None)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE processing_queue SET status = 'partial', finished_at = datetime('now'), "
                "video_id = :vid, db_video_id = :dbvid, error_message = :msg WHERE id = :id"
            ),
            {"vid": video_id, "dbvid": db_video_id, "msg": message[:2000], "id": item_id},
        )
        await db.commit()


async def _set_skipped(item_id: int, message: str) -> None:
    """A stage was stopped by the user: not a failure, not a success."""
    _QUEUE_PROGRESS.pop(item_id, None)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE processing_queue SET status = 'skipped', finished_at = datetime('now'), "
                "error_message = :msg WHERE id = :id"
            ),
            {"msg": message[:2000], "id": item_id},
        )
        await db.commit()


async def _set_failed(item_id: int, error_message: str) -> None:
    _QUEUE_PROGRESS.pop(item_id, None)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE processing_queue SET status = 'failed', finished_at = datetime('now'), "
                "error_message = :msg WHERE id = :id"
            ),
            {"msg": error_message[:2000], "id": item_id},
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Pipeline stage runners (mirror api.py patterns, no circular import)
# ---------------------------------------------------------------------------

class ExtractionFailed(RuntimeError):
    """The extraction failed and its task already says why (message and available languages)."""


async def _run_extract(url: str, language: str = "auto") -> dict[str, Any]:
    """Extract subtitles and save to DB. Returns {video_id, db_video_id}."""
    import asyncio as _asyncio
    from services.subtitle_extractor import extract_subtitles, extract_video_id
    from services.text_formatter import format_subtitles
    from services.video_service import complete_task, create_pending_task, get_app_setting, update_task_failed

    yt_video_id = extract_video_id(url)
    if not yt_video_id:
        raise ValueError(f"Cannot extract video_id from URL: {url}")

    async with AsyncSessionLocal() as db:
        cookies_path = await get_app_setting(db, "cookies_path")
        ytdlp_path = await get_app_setting(db, "ytdlp_path") or "yt-dlp"
        # Create a pending task so complete_task works
        task = await create_pending_task(db, url, yt_video_id)
        task_id = task.id

    try:
        extraction = await _asyncio.to_thread(
            extract_subtitles, url, language, cookies_path, ytdlp_path
        )

        if not extraction.success:
            message = extraction.error_message or "Extraction failed"
            async with AsyncSessionLocal() as db:
                # the languages the video does have go with the failure: the Processing page offers them (NS-11 stage 7)
                await update_task_failed(db, task_id, message, available_languages=extraction.available_languages)
            raise ExtractionFailed(message)

        formatted = format_subtitles(extraction.subtitles, chapters=extraction.metadata.chapters)

        async with AsyncSessionLocal() as db:
            db_video = await complete_task(db, task_id, url, extraction, formatted)
            db_video_id = db_video.id if db_video else None
    except ExtractionFailed:
        raise                                            # the task already says why
    except Exception as exc:
        # an exception of the extractor itself: the task must not stay pending
        async with AsyncSessionLocal() as db:
            await update_task_failed(db, task_id, str(exc)[:500] or exc.__class__.__name__)
        raise

    return {"video_id": yt_video_id, "db_video_id": db_video_id}


async def _run_cleanup_stage(yt_video_id: str, item_id: int) -> None:
    """Run LLM cleanup for a video (already extracted)."""
    from datetime import datetime as _dt
    from services.text_cleaner import clean_text
    from services.video_service import (
        get_result, get_stage_settings, get_app_setting,
        set_cleanup_processing, finish_cleanup, fail_cleanup_stage, reset_cleanup_status,
    )

    writer = ProgressWriter(yt_video_id, "cleanup", "paragraph")   # the counters on the stage's run row (NS-25 stage 4b)
    try:
        async with AsyncSessionLocal() as db:
            fmt = await get_result(db, yt_video_id)
            if not fmt:
                raise StageFailure(f"Cleanup: video {yt_video_id} is not in History")
            if not fmt.get("formatted_text"):
                raise StageFailure("Cleanup: the video has no text to clean")
            formatted_text = fmt["formatted_text"]
            stage = await get_stage_settings(db, "cleanup")
            ollama_url = await get_app_setting(db, "ollama_url")
            parallel_workers = int(await get_app_setting(db, "parallel_workers") or "1")
            begin_llm_run(await get_app_setting(db, "llm_max_num_ctx"))
            model = stage.get("model")
            if not model or not ollama_url:
                raise StageFailure("Cleanup needs an Ollama URL and a cleanup model: set them in Settings")
            await set_cleanup_processing(db, yt_video_id, model=model, queue_item_id=item_id)

        def on_cleanup_progress(done: int, total: int) -> None:
            writer.update(done, total)   # the counters go to the stage's run row: the result page and the queue page read them there

        CLEANUP_CANCEL.discard(yt_video_id)  # a flag left over from an earlier run must not stop this one
        started_at = _dt.utcnow()
        cleaned = await clean_text(
            formatted_text,
            system_prompt=stage.get("system_prompt"),
            user_prompt_template=stage.get("user_prompt_template"),
            model=model,
            ollama_url=ollama_url,
            is_cancelled=lambda: yt_video_id in CLEANUP_CANCEL,
            on_progress=on_cleanup_progress,
            parallel_workers=parallel_workers,
        )

        await writer.close()  # the last counters are on the row before it is finished / cancelled below
        if yt_video_id in CLEANUP_CANCEL:
            # Stop pressed (NS-11 decision 1, as in the background copy): the status is reset, the previous cleaned text
            # and its details are kept, and no benchmark row is written
            CLEANUP_CANCEL.discard(yt_video_id)
            async with AsyncSessionLocal() as db:
                await reset_cleanup_status(db, yt_video_id)
            raise StageCancelled("Cleanup cancelled")

        async with AsyncSessionLocal() as db:
            await finish_cleanup(
                db, yt_video_id, cleaned, started_at=started_at,
                error=llm_failure_reason() or (
                    None if cleaned else "No cleaned text was produced: Ollama may be unreachable, or the model returned nothing"),
            )
    except StageCancelled:
        raise
    except Exception as exc:
        logger.exception("Queue cleanup: stage failed for %s", yt_video_id)
        # a StageFailure's own message first: the reason box of an earlier stage must not leak into it
        reason = str(exc)[:500] if isinstance(exc, StageFailure) else (llm_failure_reason() or str(exc)[:500])
        async with AsyncSessionLocal() as db:
            await fail_cleanup_stage(db, yt_video_id, error=reason)
        raise
    finally:
        await writer.close()                      # on every way out: no write after the run is over


async def _run_summary_stage(yt_video_id: str, item_id: int) -> None:
    """Run LLM summarization for a video."""
    from datetime import datetime as _dt
    from services.text_summarizer import summarize_text, extract_notes, MAP_REDUCE_THRESHOLD
    from services.video_service import (
        get_result, get_stage_settings, get_app_setting,
        set_summary_processing, finish_summary, fail_summary_stage, reset_summary_status,
    )

    writer: ProgressWriter | None = None
    try:
        async with AsyncSessionLocal() as db:
            fmt = await get_result(db, yt_video_id)
            if not fmt:
                raise StageFailure(f"Summary: video {yt_video_id} is not in History")
            source_text = fmt.get("cleaned_text") or fmt.get("formatted_text")
            if not source_text:
                raise StageFailure("Summary: the video has no text to summarize")
            language = fmt.get("language")
            stage = await get_stage_settings(db, "summarization")
            extract_stage = await get_stage_settings(db, "summarization_extract")
            combine_stage = await get_stage_settings(db, "summarization_combine")
            ollama_url = await get_app_setting(db, "ollama_url")
            force_map_reduce = (await get_app_setting(db, "force_map_reduce") or "false") == "true"
            parallel_workers = int(await get_app_setting(db, "parallel_workers") or "1")
            begin_llm_run(await get_app_setting(db, "llm_max_num_ctx"))
            model = stage.get("model")
            if not model or not ollama_url:
                raise StageFailure("Summary needs an Ollama URL and a summarization model: set them in Settings")
            await set_summary_processing(db, yt_video_id, model=model, queue_item_id=item_id)

        use_full_extract = (
            not force_map_reduce
            and bool(fmt.get("chapters"))
            and len(source_text) >= MAP_REDUCE_THRESHOLD
        )

        writer = ProgressWriter(yt_video_id, "summary", "chapter" if use_full_extract else "chunk")

        def on_summary_progress(done: int, total: int) -> None:
            writer.update(done, total)   # the counters go to the stage's run row: the result page and the queue page read them there

        SUMMARY_CANCEL.discard(yt_video_id)  # a flag left over from an earlier run must not stop this one
        started_at = _dt.utcnow()
        if use_full_extract:
            summary, mode, chunks_count = await extract_notes(
                source_text,
                model=model,
                ollama_url=ollama_url,
                is_cancelled=lambda: yt_video_id in SUMMARY_CANCEL,
                on_progress=on_summary_progress,
                language=language,
                parallel_workers=parallel_workers,
            )
        else:
            summary, mode, chunks_count = await summarize_text(
                source_text,
                system_prompt=stage.get("system_prompt"),
                user_prompt_template=stage.get("user_prompt_template"),
                model=model,
                ollama_url=ollama_url,
                is_cancelled=lambda: yt_video_id in SUMMARY_CANCEL,
                force_map_reduce=force_map_reduce,
                extract_prompt=extract_stage.get("user_prompt_template"),
                combine_prompt=combine_stage.get("user_prompt_template"),
                on_progress=on_summary_progress,
                language=language,
                parallel_workers=parallel_workers,
            )

        await writer.close()  # the last counters are on the row before it is finished / cancelled below
        if yt_video_id in SUMMARY_CANCEL:
            # Stop pressed (NS-11 decision 1, as in the background copy): the status is reset, the previous summary and
            # its details are kept, and no benchmark row is written
            SUMMARY_CANCEL.discard(yt_video_id)
            async with AsyncSessionLocal() as db:
                await reset_summary_status(db, yt_video_id)
            raise StageCancelled("Summary cancelled")

        async with AsyncSessionLocal() as db:
            await finish_summary(
                db, yt_video_id, summary, mode=mode,
                chunks_count=chunks_count, started_at=started_at,
                error=llm_failure_reason() or (None if summary else "No summary was produced: Ollama may be unreachable, or the model returned nothing"),
            )
    except StageCancelled:
        raise
    except Exception as exc:
        logger.exception("Queue summary: stage failed for %s", yt_video_id)
        # a StageFailure's own message first: the reason box of an earlier stage must not leak into it
        reason = str(exc)[:500] if isinstance(exc, StageFailure) else (llm_failure_reason() or str(exc)[:500])
        async with AsyncSessionLocal() as db:
            await fail_summary_stage(db, yt_video_id, error=reason)
        raise
    finally:
        if writer is not None:
            await writer.close()                  # on every way out: no write after the run is over


async def _run_transcribe(url: str, language: str = "auto", item_id: int = 0) -> dict[str, Any]:
    """Download audio from a YouTube URL and transcribe via STT. Returns {video_id, db_video_id}."""
    import asyncio as _asyncio
    import tempfile
    from services.subtitle_extractor import (
        extract_audio, extract_video_id,
        ExtractionResult, SubtitleEntry, AudioExtractionResult,
    )
    from services.transcriber import transcribe as _transcribe, DEFAULT_CACHE_PATH
    from services.text_formatter import format_subtitles
    from services.video_service import (
        complete_task, create_pending_task, update_task_failed, get_app_setting,
    )

    yt_video_id = extract_video_id(url)
    if not yt_video_id:
        raise ValueError(f"Cannot extract video_id from URL: {url}")

    async with AsyncSessionLocal() as db:
        cookies_path = await get_app_setting(db, "cookies_path")
        ytdlp_path = await get_app_setting(db, "ytdlp_path") or "yt-dlp"
        stt_model = await get_app_setting(db, "stt_model") or "base"
        stt_device = await get_app_setting(db, "stt_device") or "auto"
        stt_cache_path = await get_app_setting(db, "stt_cache_path") or DEFAULT_CACHE_PATH
        task = await create_pending_task(db, url, yt_video_id)
        task_id = task.id

    _QUEUE_PROGRESS[item_id] = "transcribe: downloading audio…"
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_result: AudioExtractionResult = await _asyncio.to_thread(
            extract_audio, url, tmpdir, ytdlp_path, cookies_path
        )
        if not audio_result.success:
            async with AsyncSessionLocal() as db:
                await update_task_failed(db, task_id, audio_result.error_message or "Audio download failed")
            raise RuntimeError(audio_result.error_message or "Audio download failed")

        _QUEUE_PROGRESS[item_id] = "transcribe: transcribing…"
        import datetime as _dt_mod
        transcription_started_at = _dt_mod.datetime.utcnow()

        def _on_progress(n: int, cur_s: float = 0.0, tot_s: float = 0.0) -> None:
            pct = f" · {int(cur_s / tot_s * 100)}%" if tot_s > 0 else ""
            _QUEUE_PROGRESS[item_id] = f"transcribe: segment {n}{pct}"

        transcription = await _asyncio.to_thread(
            _transcribe, audio_result.audio_path,
            language=language,
            model=stt_model,
            device=stt_device,
            cache_path=stt_cache_path,
            on_progress=_on_progress,
        )

    if not transcription.success:
        async with AsyncSessionLocal() as db:
            await update_task_failed(db, task_id, transcription.error_message or "Transcription failed")
        raise RuntimeError(transcription.error_message or "Transcription failed")

    detected_language = transcription.detected_language or (language if language != "auto" else "und")

    entries = [
        SubtitleEntry(
            timestamp="{:02d}:{:02d}:{:02d}".format(
                int(s["start"] // 3600),
                int(s["start"] % 3600 // 60),
                int(s["start"] % 60),
            ),
            text=s["text"].strip(),
        )
        for s in (transcription.segments or [])
        if s.get("text", "").strip()
    ]

    metadata = audio_result.metadata
    extraction = ExtractionResult(
        success=True,
        metadata=metadata,
        subtitles=entries,
        language=detected_language,
        source_type=None,
    )
    formatted = format_subtitles(entries, chapters=metadata.chapters if metadata else None)

    async with AsyncSessionLocal() as db:
        await complete_task(
            db, task_id, url, extraction, formatted,
            subtitle_source="transcript",
            transcription_started_at=transcription_started_at,
        )

    return {"video_id": yt_video_id, "db_video_id": None}


class StageFailure(RuntimeError):
    """A stage that cannot run at all (no model, no text, no such video): its message is stored and shown to the user.

    NS-11 decision: this used to be a silent skip (the queue item ended 'done' having done nothing).
    """


async def _run_mindmap_stage(yt_video_id: str, item_id: int) -> None:
    """Run mindmap generation for a video."""
    from services.text_mindmapper import generate_mindmap
    from services.video_service import (
        get_result, get_stage_settings, get_app_setting,
        start_mindmap_generation, finish_mindmap, fail_mindmap_stage, reset_mindmap_status,
    )

    try:
        async with AsyncSessionLocal() as db:
            result = await get_result(db, yt_video_id)
            if not result:
                raise StageFailure(f"Mind map: video {yt_video_id} is not in History")
            text = result.get("summary_text") or result.get("cleaned_text") or result.get("formatted_text")
            if not text:
                raise StageFailure("Mind map: the video has no text to build a mind map from")
            stage = await get_stage_settings(db, "summarization")
            ollama_url = await get_app_setting(db, "ollama_url")
            model = stage.get("model") if stage else None
            begin_llm_run(await get_app_setting(db, "llm_max_num_ctx"))
            if not ollama_url or not model:
                raise StageFailure("Mind map needs an Ollama URL and a summarization model: set them in Settings")
            lang_code = result.get("language") or "ru"
            lang_map = {"ru": "Russian", "en": "English", "uk": "Ukrainian", "de": "German",
                        "fr": "French", "es": "Spanish", "zh": "Chinese", "ja": "Japanese"}
            language = lang_map.get(lang_code.lower(), lang_code)
            await start_mindmap_generation(db, yt_video_id, queue_item_id=item_id, model=model)

        MINDMAP_CANCEL.discard(yt_video_id)  # a flag left over from an earlier run must not stop this one
        _QUEUE_PROGRESS[item_id] = "mindmap: generating…"
        mindmap_md = await generate_mindmap(
            text=text,
            ollama_url=ollama_url,
            model=model,
            language=language,
            is_cancelled=lambda: yt_video_id in MINDMAP_CANCEL,
        )

        if yt_video_id in MINDMAP_CANCEL:
            # Stop pressed (NS-11 decision 1, as in the background copy): the status is reset, a saved map is kept
            MINDMAP_CANCEL.discard(yt_video_id)
            async with AsyncSessionLocal() as db:
                await reset_mindmap_status(db, yt_video_id)
            raise StageCancelled("Mind map cancelled")

        async with AsyncSessionLocal() as db:
            await finish_mindmap(
                db, yt_video_id, mindmap_md,
                error=llm_failure_reason() or (None if mindmap_md else "No mind map was produced: Ollama may be unreachable, or the model returned nothing"),
                model=model,
            )
    except StageCancelled:
        raise
    except Exception as exc:
        logger.exception("Queue mindmap: stage failed for %s", yt_video_id)
        # a StageFailure's own message first: the reason box of an earlier stage must not leak into it
        reason = str(exc)[:500] if isinstance(exc, StageFailure) else (llm_failure_reason() or str(exc)[:500])
        async with AsyncSessionLocal() as db:
            await fail_mindmap_stage(db, yt_video_id, error=reason)
        raise


# ---------------------------------------------------------------------------
# Queue worker
# ---------------------------------------------------------------------------

async def _cancellable(item_id: int, step):
    """Run a step that cannot be cut short (yt-dlp) and check the item's Stop flag when it returns: inside the run, so the run is
    recorded as cancelled. What the step saved (the video) stays; the item ends skipped."""
    result = await step
    _check_item_cancel(item_id)
    return result


def _check_item_cancel(item_id: int) -> None:
    """Between the stages of an item: a Stop that arrived while a step that cannot be cut short was running ends the item here."""
    if item_id in ITEM_CANCEL:
        raise StageCancelled("Cancelled")


async def _run_download_stage(item_id: int, video_id: str, url: str) -> None:
    """The download stage (NS-17 items 12 / 13): save the video or audio in data/downloads with yt-dlp, in the format and quality
    chosen in Settings. A failure ends the run `failed` WITHOUT raising, so the item ends partial with the reason; a Stop
    (checked when yt-dlp returns, it cannot be interrupted) cancels the run and ends the item skipped."""
    from services import downloader
    from services.subtitle_extractor import _ytdlp_cmd, validate_youtube_url
    from services.video_service import get_app_setting

    async with AsyncSessionLocal() as db:
        await stage_runs.begin(db, video_id, "download", queue_item_id=item_id)
        await db.commit()
        previous = await downloader.saved_file(db, video_id)           # a good file from an earlier run is not ours to delete
    keep = {previous.name} if previous is not None else set()
    downloader.remove_leftovers(video_id, keep)                        # fragments of an earlier crashed run
    started = datetime.utcnow()
    try:
        if url.startswith(LOCAL_PREFIX):
            raise downloader.DownloadFailed("Download is not available for local files")
        canonical = validate_youtube_url(url)
        if not canonical:
            raise downloader.DownloadFailed("Cannot download: not a YouTube https link")
        async with AsyncSessionLocal() as db:
            fmt = (await get_app_setting(db, "download_default_format")) or "mp4"
            quality = (await get_app_setting(db, "download_default_quality")) or "best"
            ytdlp_path = await get_app_setting(db, "ytdlp_path")
            cookies_path = await get_app_setting(db, "cookies_path")
        _QUEUE_PROGRESS[item_id] = "download: downloading…"
        out = await downloader.download_file(canonical, video_id, fmt, quality, _ytdlp_cmd(ytdlp_path), cookies_path)
        _check_item_cancel(item_id)
        meta = {"file": out.name, "size": out.stat().st_size, "format": fmt, "quality": quality}
        async with AsyncSessionLocal() as db:
            await stage_runs.finish(db, video_id, "download", started_at=started, meta=meta)
            await db.commit()
        downloader.remove_leftovers(video_id, {out.name})              # only the file the run names stays
    except StageCancelled:
        downloader.remove_leftovers(video_id, keep)                    # a cancelled run leaves no file of its own
        async with AsyncSessionLocal() as db:
            await stage_runs.cancel(db, video_id, "download")
            await db.commit()
        raise
    except Exception as exc:  # noqa: BLE001 - any failure of the download is the stage's failure, not the item's crash
        if item_id in ITEM_CANCEL:
            # The user pressed Cancel and yt-dlp died with it ("Interrupted by user"): that is a Stop, not a failed download
            downloader.remove_leftovers(video_id, keep)
            async with AsyncSessionLocal() as db:
                await stage_runs.cancel(db, video_id, "download")
                await db.commit()
            raise StageCancelled("Cancelled") from exc
        if not isinstance(exc, downloader.DownloadFailed):
            logger.exception("Queue worker: download of %s failed", video_id)
        downloader.remove_leftovers(video_id, keep)                    # a failed or timed-out run leaves no fragments
        async with AsyncSessionLocal() as db:
            await stage_runs.fail(db, video_id, "download", str(exc)[:500])
            await db.commit()


async def _run_first_stage(item: dict, item_id: int, url: str, pipeline_stages: list[str], item_language: str) -> tuple[str, str | None]:
    """Stage 1 of an item: re-extract / transcribe an upload / transcribe a link / extract subtitles / (stages only) find the video
    in History. Returns (video id, db video id); raises what the stage raises."""
    # Stage 1: transcribe OR extract (mutually exclusive) — skip for already-processed videos
    if "reextract" in pipeline_stages:
        # a re-extract / re-transcribe of a video that is in History (NS-11 stage 6): replaces its text in place
        _QUEUE_PROGRESS[item_id] = "re-extracting…"
        reextract_result = await run_queued_reextract(item)
        yt_video_id = reextract_result["video_id"]
        db_video_id = reextract_result["db_video_id"]
    elif "transcribe" in pipeline_stages and url.startswith(LOCAL_PREFIX):
        # an uploaded file (NS-11 stage 5): the audio is on disk, the item names it by video_id
        _QUEUE_PROGRESS[item_id] = "transcribing…"
        file_result = await run_queued_file(item)
        yt_video_id = file_result["video_id"]
        db_video_id = file_result["db_video_id"]
    elif "transcribe" in pipeline_stages:
        _QUEUE_PROGRESS[item_id] = "downloading audio…"
        transcribe_result = await stage_runs.recorded(
            "transcribe", url, item_id,
            lambda: _cancellable(item_id, _run_transcribe(url, language=item_language, item_id=item_id)))
        yt_video_id = transcribe_result["video_id"]
        db_video_id = transcribe_result["db_video_id"]
    elif "extract" in pipeline_stages:
        _QUEUE_PROGRESS[item_id] = "extracting subtitles…"
        extract_result = await stage_runs.recorded(
            "extract", url, item_id, lambda: _cancellable(item_id, _run_extract(url, language=item_language)))
        yt_video_id = extract_result["video_id"]
        db_video_id = extract_result["db_video_id"]
    else:
        # Stages-only mode: the video is already in History. The item names it by video_id
        # (local files have no YouTube URL); items queued before that fall back to the URL.
        from services.subtitle_extractor import extract_video_id as _extract_video_id
        yt_video_id = item.get("video_id") or _extract_video_id(url)
        db_video_id = None
        if not yt_video_id:
            raise ValueError(f"Cannot extract video_id from URL: {url}")
        if not await _video_exists(yt_video_id):
            # deleted after it was queued, or never extracted: not a silent "done"
            raise LookupError(f"Video {yt_video_id} is not in History (deleted, or never extracted)")
        logger.info("Queue worker: skipping extract for item %d (stages-only mode)", item_id)
    return yt_video_id, db_video_id


async def queue_worker() -> None:
    """Main queue worker loop. Call once from lifespan(). Runs forever."""
    global _WORKER_STOP
    logger.info("Queue worker started")

    await _reset_stuck_items()

    while not _WORKER_STOP:
        item = await _pick_next()
        if not item:
            await asyncio.sleep(5)
            continue

        item_id = item["id"]
        url = item["url"]
        pipeline_stages: list[str] = item["pipeline_stages"]
        item_language: str = item.get("language") or "auto"
        logger.info("Queue worker: processing item %d url=%s stages=%s language=%s", item_id, url, pipeline_stages, item_language)
        ITEM_CANCEL.discard(item_id)      # a Stop meant for an earlier life of this id must not stop this run
        await _set_processing(item_id)

        try:
            first_stage_error: Exception | None = None
            try:
                yt_video_id, db_video_id = await _run_first_stage(item, item_id, url, pipeline_stages, item_language)
            except StageCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                # No subtitles (or any other failure of stage 1) must not cost the download the user also asked for (NS-17 item 13):
                # the text stages are skipped, the download still runs, and the item ends partial with the reason.
                from services.subtitle_extractor import extract_video_id as _video_id_of
                if "download" not in pipeline_stages or "reextract" in pipeline_stages or url.startswith(LOCAL_PREFIX) or not _video_id_of(url):
                    raise
                logger.warning("Queue worker: item %d: stage 1 failed (%s); the download still runs", item_id, exc)
                first_stage_error = exc
                yt_video_id, db_video_id = _video_id_of(url), None

            # Stage 2: cleanup (optional)
            if first_stage_error is None and "cleanup" in pipeline_stages:
                _check_item_cancel(item_id)
                await _run_cleanup_stage(yt_video_id, item_id)

            # Stage 3: summary (optional)
            if first_stage_error is None and "summary" in pipeline_stages:
                _check_item_cancel(item_id)
                await _run_summary_stage(yt_video_id, item_id)

            # Stage 4: mindmap (optional)
            if first_stage_error is None and "mindmap" in pipeline_stages:
                _check_item_cancel(item_id)
                await _run_mindmap_stage(yt_video_id, item_id)

            # Stage 5: download (optional; after the text stages, so the text is there first)
            if "download" in pipeline_stages:
                _check_item_cancel(item_id)
                await _run_download_stage(item_id, yt_video_id, url)

            async with AsyncSessionLocal() as db:
                failed = await _item_failed_stages(db, item_id, pipeline_stages)
            if first_stage_error is not None:
                first = "transcribe" if "transcribe" in pipeline_stages else "extract"
                if first not in {s for s, _ in failed}:
                    failed = [(first, str(first_stage_error)[:500])] + failed
            if failed:
                # a stage ended failed without raising (an empty answer): the item is not "done"
                message = "; ".join(f"{_STAGE_LABELS.get(s, s)} failed: {err or 'no reason recorded'}" for s, err in failed)
                if first_stage_error is not None and "download" not in {s for s, _ in failed}:
                    from services.downloader import find_download
                    saved = find_download(yt_video_id)
                    if saved is not None:
                        message += f"; the video was downloaded ({saved.name}, in data/downloads)"
                await _set_partial(item_id, yt_video_id, db_video_id, message)
                if first_stage_error is not None:
                    await _release_unrun_stages(item.get("video_id"), url, pipeline_stages, str(first_stage_error))
                logger.warning("Queue worker: item %d partial video_id=%s: %s", item_id, yt_video_id, message)
            else:
                await _set_done(item_id, yt_video_id, db_video_id)
                logger.info("Queue worker: item %d done video_id=%s", item_id, yt_video_id)

        except StageCancelled as e:
            logger.info("Queue worker: item %d cancelled: %s", item_id, e)
            await _set_skipped(item_id, str(e))
            # the stages that were queued with it and never ran go back to idle (the one that was stopped reset itself)
            await _release_unrun_stages(item.get("video_id"), url, pipeline_stages, str(e), cancelled=True)
            if item.get("video_id"):                  # the Stop flags set for stages that never started must not wait for the next run
                for flags in (CLEANUP_CANCEL, SUMMARY_CANCEL, MINDMAP_CANCEL):
                    flags.discard(item["video_id"])

        except Exception as e:
            logger.error("Queue worker: item %d failed: %s", item_id, e, exc_info=True)
            await _set_failed(item_id, str(e))
            # A summary / mind map that was queued (status 'processing') inside this multi-stage item and never got to run
            # because an earlier stage failed: say so instead of leaving 'processing' without an owner. A failure of the
            # stage itself already set 'failed', so nothing changes then.
            await _release_unrun_stages(item.get("video_id"), url, pipeline_stages, str(e))

        finally:
            ITEM_CANCEL.discard(item_id)

        # Brief pause between items to avoid hammering Ollama immediately
        await asyncio.sleep(1)

    logger.info("Queue worker stopped")
