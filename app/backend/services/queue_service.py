"""Bulk URL queue: CRUD + asyncio background worker.

Worker runs as a single asyncio task (started in lifespan). Processes one item
at a time — Ollama cannot handle parallel heavy requests.

Status flow: pending → processing → done | failed
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

logger = logging.getLogger("queue_service")

# Global stop flag — set to True to gracefully stop the worker loop
_WORKER_STOP = False


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def get_duplicate_video_ids(db: AsyncSession, video_ids: list[str]) -> set[str]:
    """Return subset of video_ids that are already processed or pending in queue."""
    if not video_ids:
        return set()

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
    found: set[str] = {row[0] for row in done.fetchall()}

    # Already in queue with pending/processing status
    in_queue = await db.execute(
        text(
            f"SELECT video_id FROM processing_queue "
            f"WHERE video_id IN ({placeholders}) AND status IN ('pending','processing')"
        ),
        params,
    )
    found.update(row[0] for row in in_queue.fetchall() if row[0])

    return found


async def add_items(db: AsyncSession, urls: list[str], pipeline_stages: list[str]) -> list[int]:
    """Insert queue items. Returns list of inserted IDs.
    video_id (YouTube ID) is stored at insert time for dedup checks.
    """
    from services.subtitle_extractor import extract_video_id as _extract_video_id

    stages_json = json.dumps(pipeline_stages)
    result = await db.execute(text("SELECT COALESCE(MAX(sort_order), 0) FROM processing_queue"))
    max_order = result.scalar() or 0

    ids: list[int] = []
    for i, url in enumerate(urls):
        vid = _extract_video_id(url)  # always valid here (caller already validated)
        res = await db.execute(
            text(
                "INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order) "
                "VALUES (:url, :vid, 'pending', :stages, datetime('now'), :order)"
            ),
            {"url": url, "vid": vid, "stages": stages_json, "order": max_order + i + 1},
        )
        ids.append(res.lastrowid)

    await db.commit()
    return ids


async def get_queue(db: AsyncSession) -> list[dict]:
    """Return all queue items ordered by sort_order + added_at."""
    result = await db.execute(
        text(
            "SELECT id, url, video_id, db_video_id, status, pipeline_stages, "
            "error_message, added_at, started_at, finished_at, sort_order "
            "FROM processing_queue ORDER BY sort_order, added_at"
        )
    )
    rows = result.fetchall()
    return [
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
        }
        for r in rows
    ]


async def get_queue_counts(db: AsyncSession) -> dict[str, int]:
    """Return counts per status — for nav badge."""
    result = await db.execute(
        text("SELECT status, COUNT(*) FROM processing_queue GROUP BY status")
    )
    counts: dict[str, int] = {r[0]: r[1] for r in result.fetchall()}
    return counts


async def delete_item(db: AsyncSession, item_id: int) -> str:
    """Delete a pending item. Returns 'deleted' | 'not_found' | 'conflict'."""
    result = await db.execute(
        text("SELECT status FROM processing_queue WHERE id = :id"),
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
    return "deleted"


async def clear_pending(db: AsyncSession) -> int:
    """Delete all pending items. Returns deleted count."""
    result = await db.execute(
        text("DELETE FROM processing_queue WHERE status = 'pending'")
    )
    await db.commit()
    return result.rowcount


async def clear_failed(db: AsyncSession) -> int:
    """Delete all failed items. Returns deleted count."""
    result = await db.execute(
        text("DELETE FROM processing_queue WHERE status = 'failed'")
    )
    await db.commit()
    return result.rowcount


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
                "SELECT id, url, pipeline_stages FROM processing_queue "
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
        }


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
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE processing_queue SET status = 'done', finished_at = datetime('now'), "
                "video_id = :vid, db_video_id = :dbvid WHERE id = :id"
            ),
            {"vid": video_id, "dbvid": db_video_id, "id": item_id},
        )
        await db.commit()


async def _set_failed(item_id: int, error_message: str) -> None:
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
        task_id, _ = await create_pending_task(db, url, yt_video_id)

    extraction = await _asyncio.to_thread(
        extract_subtitles, url, language, cookies_path, ytdlp_path
    )

    if not extraction.success:
        async with AsyncSessionLocal() as db:
            await update_task_failed(db, task_id, extraction.error_message or "Extraction failed")
        raise RuntimeError(extraction.error_message or "Extraction failed")

    formatted = format_subtitles(extraction.subtitles, chapters=extraction.metadata.chapters)

    async with AsyncSessionLocal() as db:
        db_video = await complete_task(db, task_id, url, extraction, formatted)
        db_video_id = db_video.id if db_video else None

    return {"video_id": yt_video_id, "db_video_id": db_video_id}


async def _run_cleanup_stage(yt_video_id: str) -> None:
    """Run LLM cleanup for a video (already extracted)."""
    from datetime import datetime as _dt
    from services.text_cleaner import clean_text
    from services.video_service import (
        get_result, get_stage_settings, get_app_setting,
        set_cleanup_processing, finish_cleanup, reset_cleanup_status,
    )

    async with AsyncSessionLocal() as db:
        fmt = await get_result(db, yt_video_id)
        if not fmt or not fmt.get("formatted_text"):
            logger.warning("Queue cleanup: no formatted_text for %s, skipping", yt_video_id)
            return
        formatted_text = fmt["formatted_text"]
        stage = await get_stage_settings(db, "cleanup")
        ollama_url = await get_app_setting(db, "ollama_url")
        parallel_workers = int(await get_app_setting(db, "parallel_workers") or "1")
        model = stage.get("model")
        if not model:
            logger.warning("Queue cleanup: no cleanup model configured, skipping cleanup for %s", yt_video_id)
            return
        await set_cleanup_processing(db, yt_video_id, model=model)

    started_at = _dt.utcnow()
    cleaned = await clean_text(
        formatted_text,
        system_prompt=stage.get("system_prompt"),
        user_prompt_template=stage.get("user_prompt_template"),
        model=model,
        ollama_url=ollama_url,
        is_cancelled=lambda: False,  # no per-item cancel for queue
        on_progress=None,
        parallel_workers=parallel_workers,
    )

    async with AsyncSessionLocal() as db:
        await finish_cleanup(db, yt_video_id, cleaned, started_at=started_at)


async def _run_summary_stage(yt_video_id: str) -> None:
    """Run LLM summarization for a video."""
    from datetime import datetime as _dt
    from services.text_summarizer import summarize_text, extract_notes, MAP_REDUCE_THRESHOLD
    from services.video_service import (
        get_result, get_stage_settings, get_app_setting,
        set_summary_processing, finish_summary, reset_summary_status,
    )

    async with AsyncSessionLocal() as db:
        fmt = await get_result(db, yt_video_id)
        if not fmt:
            return
        source_text = fmt.get("cleaned_text") or fmt.get("formatted_text")
        if not source_text:
            logger.warning("Queue summary: no source text for %s, skipping", yt_video_id)
            return
        language = fmt.get("language")
        stage = await get_stage_settings(db, "summarization")
        extract_stage = await get_stage_settings(db, "summarization_extract")
        combine_stage = await get_stage_settings(db, "summarization_combine")
        ollama_url = await get_app_setting(db, "ollama_url")
        force_map_reduce = (await get_app_setting(db, "force_map_reduce") or "false") == "true"
        parallel_workers = int(await get_app_setting(db, "parallel_workers") or "1")
        model = stage.get("model")
        if not model:
            logger.warning("Queue summary: no summary model configured, skipping for %s", yt_video_id)
            return
        await set_summary_processing(db, yt_video_id, model=model)

    use_full_extract = (
        not force_map_reduce
        and bool(fmt.get("chapters"))
        and len(source_text) >= MAP_REDUCE_THRESHOLD
    )

    started_at = _dt.utcnow()
    if use_full_extract:
        summary, mode, chunks_count = await extract_notes(
            source_text,
            model=model,
            ollama_url=ollama_url,
            is_cancelled=lambda: False,
            on_progress=None,
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
            is_cancelled=lambda: False,
            force_map_reduce=force_map_reduce,
            extract_prompt=extract_stage.get("user_prompt_template"),
            combine_prompt=combine_stage.get("user_prompt_template"),
            on_progress=None,
            language=language,
            parallel_workers=parallel_workers,
        )

    async with AsyncSessionLocal() as db:
        await finish_summary(
            db, yt_video_id, summary, mode=mode,
            chunks_count=chunks_count, started_at=started_at,
        )


# ---------------------------------------------------------------------------
# Queue worker
# ---------------------------------------------------------------------------

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
        logger.info("Queue worker: processing item %d url=%s stages=%s", item_id, url, pipeline_stages)
        await _set_processing(item_id)

        try:
            # Stage 1: extract (always first)
            extract_result = await _run_extract(url)
            yt_video_id = extract_result["video_id"]
            db_video_id = extract_result["db_video_id"]

            # Stage 2: cleanup (optional)
            if "cleanup" in pipeline_stages:
                await _run_cleanup_stage(yt_video_id)

            # Stage 3: summary (optional, implies cleanup was run)
            if "summary" in pipeline_stages:
                await _run_summary_stage(yt_video_id)

            await _set_done(item_id, yt_video_id, db_video_id)
            logger.info("Queue worker: item %d done video_id=%s", item_id, yt_video_id)

        except Exception as e:
            logger.error("Queue worker: item %d failed: %s", item_id, e, exc_info=True)
            await _set_failed(item_id, str(e))

        # Brief pause between items to avoid hammering Ollama immediately
        await asyncio.sleep(1)

    logger.info("Queue worker stopped")
