"""Queue items for results that are already in History, named by video_id (NS-11 stage 1).

A YouTube video can be queued by URL, but a local file (`file-...`) has no YouTube URL, so History
queues its rows by video_id. Only the LLM stages can run on an existing result.
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services import stage_runs

# Stages that work on a result that is already extracted / transcribed
RESULT_STAGES = ("cleanup", "summary", "mindmap")


async def add_by_video_ids(db: AsyncSession, video_ids: list[str], stages: list[str]) -> dict:
    """Queue existing results. Returns {"ids": [...], "duplicates": [...], "missing": [...]}.

    duplicates: already pending or processing in the queue; missing: no such result in History.
    Order of the given ids is kept; an id listed twice is queued once.
    """
    wanted = list(dict.fromkeys(v.strip() for v in video_ids if v and v.strip()))
    if not wanted:
        return {"ids": [], "duplicates": [], "missing": []}

    marks = ", ".join(f":v{i}" for i in range(len(wanted)))
    params = {f"v{i}": v for i, v in enumerate(wanted)}
    found = {
        r[0]: (r[1], r[2])
        for r in (await db.execute(
            text(f"SELECT video_id, url, id FROM videos WHERE video_id IN ({marks}) AND url NOT LIKE '__pending__%'"),
            params,
        )).fetchall()
    }
    queued = {
        r[0]
        for r in (await db.execute(
            text(f"SELECT video_id FROM processing_queue WHERE video_id IN ({marks}) "
                 f"AND status IN ('pending','processing')"),
            params,
        )).fetchall()
    }

    missing = [v for v in wanted if v not in found]
    duplicates = [v for v in wanted if v in found and v in queued]
    to_add = [v for v in wanted if v in found and v not in queued]

    stages_json = json.dumps(stages)
    ids: list[int] = []
    for vid in to_add:
        url, db_id = found[vid]
        # one statement checks and inserts: a request that queued the same id a moment ago wins, this one skips it
        res = await db.execute(
            text("INSERT INTO processing_queue (url, video_id, db_video_id, status, pipeline_stages, added_at, sort_order) "
                 "SELECT :url, :vid, :dbid, 'pending', :stages, datetime('now'), "
                 "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM processing_queue) "
                 "WHERE NOT EXISTS (SELECT 1 FROM processing_queue "
                 "WHERE video_id = :vid AND status IN ('pending', 'processing'))"),
            {"url": url, "vid": vid, "dbid": db_id, "stages": stages_json},
        )
        if res.rowcount == 1:
            ids.append(res.lastrowid)
        else:
            duplicates.append(vid)
    await db.commit()
    return {"ids": ids, "duplicates": duplicates, "missing": missing}


# --- one stage of one video (the result page's mind map button) --------------------------------------------

async def enqueue_stage(db: AsyncSession, video_id: str, stage: str) -> int | None:
    """Queue `stage` for an existing result unless a pending / processing item that already includes it exists.

    Returns the new item's id, or None when such an item exists (the stage will run, nothing is added). One statement
    checks and inserts, so two clicks at once give one item. An item for OTHER stages of the same video does not
    count: the stage is not in it, so it would never run.
    """
    row = (await db.execute(
        text("SELECT url, id FROM videos WHERE video_id = :v AND url NOT LIKE '__pending__%'"), {"v": video_id},
    )).first()
    if row is None:
        return None
    res = await db.execute(
        text("INSERT INTO processing_queue (url, video_id, db_video_id, status, pipeline_stages, added_at, sort_order) "
             "SELECT :url, :vid, :dbid, 'pending', :stages, datetime('now'), "
             "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM processing_queue) "
             "WHERE NOT EXISTS (SELECT 1 FROM processing_queue WHERE video_id = :vid "
             "AND status IN ('pending', 'processing') AND pipeline_stages LIKE :has_stage)"),
        {"url": row[0], "vid": video_id, "dbid": row[1], "stages": json.dumps([stage]), "has_stage": f'%"{stage}"%'},
    )
    await db.commit()
    return res.lastrowid if res.rowcount == 1 else None


async def dequeue_pending_stage(db: AsyncSession, video_id: str, stage: str) -> int:
    """Remove the pending items of this video that hold ONLY `stage` (they have not started). Returns how many."""
    res = await db.execute(
        text("DELETE FROM processing_queue WHERE video_id = :vid AND status = 'pending' AND pipeline_stages = :stages"),
        {"vid": video_id, "stages": json.dumps([stage])},
    )
    await db.commit()
    return res.rowcount


async def has_processing_item(db: AsyncSession, video_id: str) -> bool:
    """Is the worker busy with an item of this video right now?"""
    row = (await db.execute(
        text("SELECT 1 FROM processing_queue WHERE video_id = :vid AND status = 'processing' LIMIT 1"), {"vid": video_id},
    )).first()
    return row is not None


# stage -> (status column, error column) of subtitles_formatted for the stages whose status the endpoint sets at once
STAGE_COLUMNS = {
    "cleanup": ("cleanup_status", "cleanup_error"),
    "mindmap": ("mindmap_status", "mindmap_error"),
    "summary": ("summary_status", "summary_error"),
}


async def release_stage_status(db: AsyncSession, video_id: str, stage: str,
                               status: str | None = None, error: str | None = None) -> bool:
    """A stage that was marked 'processing' has lost its queue item: give the status back (NS-11 review).

    The endpoint sets 'processing' at once; the item that was to run the stage may then be removed from the queue (Remove,
    Clear pending) or its multi-stage item may fail at an earlier stage, and nothing would ever end the status. This sets it
    to `status` (None = idle, or 'failed' with `error`) - only if it still says 'processing' AND no other pending / processing
    item of the video still includes the stage (that one will end it). A saved result is never touched.
    Returns True if the status was changed. `stage` is one of STAGE_COLUMNS.
    """
    status_col, error_col = STAGE_COLUMNS[stage]  # column names come from this table only, never from a caller
    other = (await db.execute(
        text("SELECT 1 FROM processing_queue WHERE video_id = :v AND status IN ('pending', 'processing') "
             "AND pipeline_stages LIKE :has LIMIT 1"),
        {"v": video_id, "has": f'%"{stage}"%'},
    )).first()
    if other is not None:
        return False
    res = await db.execute(
        text(f"UPDATE subtitles_formatted SET {status_col} = :status, {error_col} = :error "
             f"WHERE {status_col} = 'processing' AND id = ("
             "SELECT sf.id FROM subtitles_formatted sf JOIN videos v ON sf.video_id = v.id "
             "WHERE v.video_id = :v AND v.url NOT LIKE '__pending__%' ORDER BY sf.created_at DESC LIMIT 1)"),
        {"status": status, "error": error, "v": video_id},
    )
    if res.rowcount == 1:
        if status == "failed":
            await stage_runs.fail(db, video_id, stage, error)
        else:
            await stage_runs.cancel(db, video_id, stage)
    await db.commit()
    return res.rowcount == 1


async def release_mindmap_status(db: AsyncSession, video_id: str, status: str | None = None, error: str | None = None) -> bool:
    return await release_stage_status(db, video_id, "mindmap", status, error)


async def release_cleanup_status(db: AsyncSession, video_id: str, status: str | None = None, error: str | None = None) -> bool:
    return await release_stage_status(db, video_id, "cleanup", status, error)


async def release_summary_status(db: AsyncSession, video_id: str, status: str | None = None, error: str | None = None) -> bool:
    return await release_stage_status(db, video_id, "summary", status, error)
