"""Queue side of POST /api/process (NS-11 stage 7): a YouTube link typed on the Processing / MCP path is a normal queue item.

The endpoint creates the pending task (what /api/status/{task_id} reports) and queues an extract item for the same video: url =
the canonical link, video_id, db_video_id = the task's placeholder video, stages ["extract"], the chosen language. The queue worker's
extract step reuses that pending task, so the task the caller polls is the one that completes or fails.
"""
from __future__ import annotations

from sqlalchemy import text

from services.video_service import update_task_failed


async def enqueue_extract(db, url: str, video_id: str, db_video_id: str, language: str) -> int | None:
    """Queue the extraction of a link. Returns the queue item's id, or None when an extraction of this video is already queued or
    running (then that item will complete the same pending task). One statement checks and inserts, so simultaneous requests
    give one item."""
    res = await db.execute(
        text("INSERT INTO processing_queue (url, video_id, db_video_id, status, pipeline_stages, language, added_at, sort_order) "
             "SELECT :url, :vid, :dbid, 'pending', :stages, :lang, datetime('now'), "
             "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM processing_queue) "
             "WHERE NOT EXISTS (SELECT 1 FROM processing_queue WHERE video_id = :vid AND status IN ('pending', 'processing') "
             "AND (pipeline_stages LIKE '%\"extract\"%' OR pipeline_stages LIKE '%\"transcribe\"%'))"),
        {"url": url, "vid": video_id, "dbid": db_video_id, "stages": '["extract"]', "lang": language},
    )
    await db.commit()
    return res.lastrowid if res.rowcount == 1 else None


async def release_task(db, db_video_id: str | None, message: str) -> None:
    """A queued item that had a pending task will not run (Remove, Clear pending): the task ends failed with `message`, so the
    Processing page does not wait for ever. Items without a task (bulk adds) have no db_video_id and are left alone."""
    if not db_video_id:
        return
    task_id = (await db.execute(
        text("SELECT id FROM processing_tasks WHERE video_id = :v AND status = 'pending' ORDER BY started_at DESC LIMIT 1"),
        {"v": db_video_id},
    )).scalar()
    if task_id:
        await update_task_failed(db, task_id, message)
