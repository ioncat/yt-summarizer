"""Queue items for results that are already in History, named by video_id (NS-11 stage 1).

A YouTube video can be queued by URL, but a local file (`file-...`) has no YouTube URL, so History
queues its rows by video_id. Only the LLM stages can run on an existing result.
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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

    max_order = (await db.execute(text("SELECT COALESCE(MAX(sort_order), 0) FROM processing_queue"))).scalar() or 0
    stages_json = json.dumps(stages)
    ids: list[int] = []
    for i, vid in enumerate(to_add):
        url, db_id = found[vid]
        res = await db.execute(
            text("INSERT INTO processing_queue (url, video_id, db_video_id, status, pipeline_stages, added_at, sort_order) "
                 "VALUES (:url, :vid, :dbid, 'pending', :stages, datetime('now'), :order)"),
            {"url": url, "vid": vid, "dbid": db_id, "stages": stages_json, "order": max_order + i + 1},
        )
        ids.append(res.lastrowid)
    await db.commit()
    return {"ids": ids, "duplicates": duplicates, "missing": missing}
