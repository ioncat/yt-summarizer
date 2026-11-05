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
RESULT_STAGES = ("cleanup", "summary", "mindmap")   # also the order they must run in: each works on the result of the one before


async def add_by_video_ids(db: AsyncSession, video_ids: list[str], stages: list[str]) -> dict:
    """Queue existing results. Returns {"ids": [...], "duplicates": [...], "missing": [...], "covered": {...}}.

    Stage-aware (NS-25): a stage that a pending / processing item of the video already includes is "covered" and is not
    queued again, but the OTHER requested stages still are (a queued mind map no longer blocks "cleanup then summarize").
    duplicates: every requested stage is covered, nothing was added; missing: no such result in History;
    covered: {video_id: [the requested stages that were already queued]}, for duplicates and partly covered videos;
    blocked: {video_id: [queued stages]} - nothing is added for these: a stage that would be added must run BEFORE a stage
    that is already queued for the video, asked for or not (a summary or a mind map is queued, "cleanup then summarize" is
    asked): queued behind it, the cleanup would run after them and they would never be redone on its result. They are also
    listed in duplicates.
    The stages of a new item are marked 'processing' at once, so a stage that never gets to run (an earlier one failed)
    ends with a reason instead of an idle status. Order of the given ids is kept; an id listed twice is queued once.
    """
    wanted = list(dict.fromkeys(v.strip() for v in video_ids if v and v.strip()))
    if not wanted:
        return {"ids": [], "duplicates": [], "missing": [], "covered": {}, "blocked": {}}

    marks = ", ".join(f":v{i}" for i in range(len(wanted)))
    params = {f"v{i}": v for i, v in enumerate(wanted)}
    found = {
        r[0]: (r[1], r[2])
        for r in (await db.execute(
            text(f"SELECT video_id, url, id FROM videos WHERE video_id IN ({marks}) AND url NOT LIKE '__pending__%'"),
            params,
        )).fetchall()
    }
    queued_stages: dict[str, set[str]] = {}
    for vid, item_stages in (await db.execute(
        text(f"SELECT video_id, pipeline_stages FROM processing_queue WHERE video_id IN ({marks}) "
             f"AND status IN ('pending','processing')"),
        params,
    )).fetchall():
        queued_stages.setdefault(vid, set()).update(json.loads(item_stages) if item_stages else ["extract"])

    missing = [v for v in wanted if v not in found]
    duplicates: list[str] = []
    covered: dict[str, list[str]] = {}
    blocked: dict[str, list[str]] = {}
    ids: list[int] = []
    for vid in (v for v in wanted if v in found):
        already = [s for s in stages if s in queued_stages.get(vid, ())]
        todo = [s for s in stages if s not in already]
        if already:
            covered[vid] = already
        if not todo:
            duplicates.append(vid)
            continue
        in_the_way = later_stages_queued(queued_stages.get(vid, set()), todo)
        if in_the_way:
            blocked[vid] = in_the_way
            duplicates.append(vid)
            continue
        url, db_id = found[vid]
        likes = " OR ".join(f"pipeline_stages LIKE :s{i}" for i in range(len(todo)))
        # one statement checks and inserts: a request that queued one of these stages a moment ago wins, this one skips it
        res = await db.execute(
            text("INSERT INTO processing_queue (url, video_id, db_video_id, status, pipeline_stages, added_at, sort_order) "
                 "SELECT :url, :vid, :dbid, 'pending', :stages, datetime('now'), "
                 "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM processing_queue) "
                 "WHERE NOT EXISTS (SELECT 1 FROM processing_queue "
                 f"WHERE video_id = :vid AND status IN ('pending', 'processing') AND ({likes}))"),
            {"url": url, "vid": vid, "dbid": db_id, "stages": json.dumps(todo),
             **{f"s{i}": f'%"{s}"%' for i, s in enumerate(todo)}},
        )
        if res.rowcount == 1:
            ids.append(res.lastrowid)
            await _mark_queued(db, vid, todo, res.lastrowid)
        else:
            duplicates.append(vid)
    await db.commit()
    return {"ids": ids, "duplicates": duplicates, "missing": missing, "covered": covered, "blocked": blocked}


_LABEL = {"cleanup": "cleanup", "summary": "summary", "mindmap": "mind map"}


def later_stages_queued(queued: set[str], to_add: list[str]) -> list[str]:
    """The queued stages that come AFTER a stage that is about to be added (they would run first, on the old result)."""
    first = min((RESULT_STAGES.index(s) for s in to_add if s in RESULT_STAGES), default=None)
    if first is None:
        return []
    return [q for q in RESULT_STAGES[first + 1:] if q in queued]


def order_message(blockers: list[str], to_add: list[str]) -> str:
    """What to tell the user when `blockers` are queued and `to_add` would have to run before them."""
    names = " and ".join(_LABEL.get(s, s) for s in blockers)
    before = " and ".join(_LABEL.get(s, s) for s in to_add)
    return (f"A {names} is already queued and would run before the {before}: "
            "wait for it or remove it on the Queue page, then try again.")


async def queued_stages_of(db: AsyncSession, video_id: str) -> set[str]:
    """Every stage that a pending / processing item of the video includes."""
    stages: set[str] = set()
    for (item_stages,) in (await db.execute(
        text("SELECT pipeline_stages FROM processing_queue WHERE video_id = :v AND status IN ('pending', 'processing')"),
        {"v": video_id},
    )).fetchall():
        stages.update(json.loads(item_stages) if item_stages else ["extract"])
    return stages


async def ensure_stage_order(db: AsyncSession, video_id: str, stage: str) -> None:
    """The single-stage buttons: refuse (409) when a stage that comes after `stage` is already queued for the video."""
    from fastapi import HTTPException
    queued = await queued_stages_of(db, video_id)
    if stage in queued:
        return                  # an item already has this stage: the click adds nothing, so nothing can run out of order
    blockers = later_stages_queued(queued, [stage])
    if blockers:
        raise HTTPException(status_code=409, detail=order_message(blockers, [stage]))


async def _mark_queued(db: AsyncSession, video_id: str, stages: list[str], item_id: int) -> None:
    """The stages of a new item show 'processing' at once (as the single-stage endpoints do), tied to the item."""
    from services import video_service as vs

    todo = [s for s in stages if s in STAGE_COLUMNS]
    if not todo:
        return
    if "cleanup" in todo:
        model = (await vs.get_stage_settings(db, "cleanup")).get("model")
        await vs.set_cleanup_processing(db, video_id, model=model, queue_item_id=item_id)
    if "summary" in todo:
        model = (await vs.get_stage_settings(db, "summarization")).get("model")
        await vs.set_summary_processing(db, video_id, model=model, queue_item_id=item_id)
    if "mindmap" in todo:
        model = (await vs.get_stage_settings(db, "summarization")).get("model")      # the mind map uses the summary model
        await vs.start_mindmap_generation(db, video_id, queue_item_id=item_id, model=model)


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
