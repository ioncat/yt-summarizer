"""Writers of the per-stage table `processing_stages` (NS-25 step 2).

One row per run of a stage. They are called from the same places that write the old status columns (video_service
`set_*_processing / finish_* / fail_* / reset_*`, queue_by_id `release_stage_status`, the queue's extract and transcribe
runners), inside the caller's transaction: these functions never commit, so a status column and its row change together.

- begin():   the stage starts, or is queued (the endpoint marks it at once). One OPEN ('processing') row per video and stage:
             a second begin reuses it (the queue worker starting what the endpoint already marked) and only fills in what is new.
- finish():  the open row becomes 'done' (model, times, meta); with no open row a done row is added.
- fail():    the open row becomes 'failed' with the error text and a reason code (see stage_codes); with no open row one is added.
- cancel():  the open row becomes 'cancelled' (Stop, a removed queue item). Nothing open: nothing to do.
- close_stale(): at start-up, every open row left by a crash becomes 'cancelled'.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.stage_codes import STAGES, classify_error


def _ts(dt: datetime | None = None) -> str:
    return (dt or datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S.%f")


async def _open_row(db: AsyncSession, video_id: str, stage: str) -> int | None:
    row = (await db.execute(
        text("SELECT id FROM processing_stages WHERE video_id = :v AND stage = :s AND status = 'processing' "
             "ORDER BY id DESC LIMIT 1"),
        {"v": video_id, "s": stage},
    )).first()
    return row[0] if row else None


async def _insert(db: AsyncSession, video_id: str, stage: str, status: str, **cols) -> int:
    attempt = (await db.execute(
        text("SELECT COALESCE(MAX(attempt), 0) + 1 FROM processing_stages WHERE video_id = :v AND stage = :s"),
        {"v": video_id, "s": stage},
    )).scalar_one()
    now = _ts()
    res = await db.execute(
        text("INSERT INTO processing_stages (video_id, stage, status, queue_item_id, attempt, model, started_at, finished_at, "
             "error_code, error_text, meta, created_at) VALUES (:v, :s, :status, :qid, :attempt, :model, :started, :finished, "
             ":code, :err, :meta, :now)"),
        {"v": video_id, "s": stage, "status": status, "qid": cols.get("queue_item_id"), "attempt": attempt,
         "model": cols.get("model"), "started": cols.get("started_at"), "finished": cols.get("finished_at"),
         "code": cols.get("error_code"), "err": cols.get("error_text"), "meta": cols.get("meta"), "now": now},
    )
    return res.lastrowid


def _check(stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")


async def begin(db: AsyncSession, video_id: str, stage: str, model: str | None = None,
                queue_item_id: int | None = None) -> int:
    """The stage is queued or starts. Returns the id of the open row."""
    _check(stage)
    open_id = await _open_row(db, video_id, stage)
    if open_id is None:
        return await _insert(db, video_id, stage, "processing", model=model, queue_item_id=queue_item_id, started_at=_ts())
    await db.execute(
        text("UPDATE processing_stages SET model = COALESCE(:model, model), queue_item_id = COALESCE(:qid, queue_item_id) "
             "WHERE id = :id"),
        {"model": model, "qid": queue_item_id, "id": open_id},
    )
    return open_id


async def finish(db: AsyncSession, video_id: str, stage: str, model: str | None = None, started_at: datetime | None = None,
                 meta: dict | None = None) -> None:
    """The stage produced its result."""
    _check(stage)
    now = _ts()
    started = _ts(started_at) if started_at else None
    meta_json = json.dumps(meta) if meta else None
    open_id = await _open_row(db, video_id, stage)
    if open_id is None:
        await _insert(db, video_id, stage, "done", model=model, started_at=started or now, finished_at=now, meta=meta_json)
        return
    await db.execute(
        text("UPDATE processing_stages SET status = 'done', model = COALESCE(:model, model), "
             "started_at = COALESCE(:started, started_at), finished_at = :now, error_code = NULL, error_text = NULL, "
             "meta = :meta WHERE id = :id"),
        {"model": model, "started": started, "now": now, "meta": meta_json, "id": open_id},
    )


async def fail(db: AsyncSession, video_id: str, stage: str, error: str | None, model: str | None = None) -> None:
    """The stage failed. The reason code comes from the text (stage_codes.classify_error); a failure always has one."""
    _check(stage)
    now = _ts()
    code = classify_error(error) or "unexpected"
    open_id = await _open_row(db, video_id, stage)
    if open_id is None:
        await _insert(db, video_id, stage, "failed", model=model, finished_at=now, error_code=code, error_text=error)
        return
    await db.execute(
        text("UPDATE processing_stages SET status = 'failed', model = COALESCE(:model, model), finished_at = :now, "
             "error_code = :code, error_text = :err WHERE id = :id"),
        {"model": model, "now": now, "code": code, "err": error, "id": open_id},
    )


async def cancel(db: AsyncSession, video_id: str, stage: str) -> bool:
    """Stop / removed from the queue: the open row, if any, becomes 'cancelled'. Returns True if one was closed."""
    _check(stage)
    open_id = await _open_row(db, video_id, stage)
    if open_id is None:
        return False
    await db.execute(
        text("UPDATE processing_stages SET status = 'cancelled', finished_at = :now, error_code = 'cancelled' WHERE id = :id"),
        {"now": _ts(), "id": open_id},
    )
    return True


async def recorded(stage: str, url: str, item_id: int, run):
    """Run the extract / transcribe step of a queue item (`run` is a coroutine function) and record it as a stage run.

    The video is named by the URL (extract_video_id) because the step may be what puts it into History. A failure or a
    Stop is written on the row, then re-raised for the queue worker."""
    from models.database import AsyncSessionLocal
    from services.stage_control import StageCancelled
    from services.subtitle_extractor import extract_video_id

    video_id = extract_video_id(url)
    if video_id:
        async with AsyncSessionLocal() as db:
            await begin(db, video_id, stage, queue_item_id=item_id)
            await db.commit()
    try:
        result = await run()
    except StageCancelled:
        if video_id:
            async with AsyncSessionLocal() as db:
                await cancel(db, video_id, stage)
                await db.commit()
        raise
    except Exception as exc:
        if video_id:
            async with AsyncSessionLocal() as db:
                await fail(db, video_id, stage, str(exc)[:500])
                await db.commit()
        raise
    if video_id:
        async with AsyncSessionLocal() as db:
            model = device = None
            if stage == "transcribe":
                row = (await db.execute(
                    text("SELECT sf.transcription_model, sf.transcription_device FROM subtitles_formatted sf "
                         "JOIN videos v ON v.id = sf.video_id WHERE v.video_id = :v AND v.url NOT LIKE '__pending__%' "
                         "ORDER BY sf.created_at DESC LIMIT 1"), {"v": video_id})).first()
                if row:
                    model, device = row[0], row[1]
            await finish(db, video_id, stage, model=model, meta={"device": device} if device else None)
            await db.commit()
    return result


async def close_stale(db: AsyncSession) -> int:
    """Start-up: runs cut off by a restart are over. Returns how many rows were closed."""
    res = await db.execute(
        text("UPDATE processing_stages SET status = 'cancelled', finished_at = :now, error_code = 'cancelled' "
             "WHERE status = 'processing'"),
        {"now": _ts()},
    )
    return res.rowcount
