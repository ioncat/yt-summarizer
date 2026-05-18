from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import BenchmarkRun
from services.text_summarizer import (
    MAP_REDUCE_THRESHOLD,
    extract_notes,
    summarize_text,
)
from services.video_service import get_app_setting, get_result, get_stage_settings

logger = logging.getLogger(__name__)


async def get_benchmark_runs(db: AsyncSession, video_id: str) -> list[dict]:
    """Return all benchmark runs for a video, newest first."""
    stmt = (
        select(BenchmarkRun)
        .where(BenchmarkRun.video_id == video_id)
        .order_by(BenchmarkRun.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_run_to_dict(r) for r in rows]


async def get_all_benchmarks_grouped(db: AsyncSession) -> list[dict]:
    """Return all benchmark runs grouped by video_id, newest video first.
    Each group: { video_id, title, total_runs, models, latest_run_at }.
    """
    from models.models import Video

    stmt = select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc())
    result = await db.execute(stmt)
    rows = result.scalars().all()

    # Group by video_id
    groups: dict[str, dict] = {}
    for r in rows:
        if r.video_id not in groups:
            groups[r.video_id] = {
                "video_id": r.video_id,
                "title": None,
                "total_runs": 0,
                "models": set(),
                "latest_run_at": r.created_at.isoformat(),
            }
        g = groups[r.video_id]
        g["total_runs"] += 1
        g["models"].add(r.model)

    if not groups:
        return []

    # Look up video titles
    video_ids = list(groups.keys())
    title_stmt = select(Video.video_id, Video.title).where(Video.video_id.in_(video_ids))
    title_rows = (await db.execute(title_stmt)).all()
    for vid, title in title_rows:
        if vid in groups:
            groups[vid]["title"] = title

    # Convert sets to sorted lists, return as list
    out = []
    for g in groups.values():
        g["models"] = sorted(g["models"])
        out.append(g)
    out.sort(key=lambda x: x["latest_run_at"], reverse=True)
    return out


async def get_benchmark_run(db: AsyncSession, run_id: int) -> dict | None:
    result = await db.execute(select(BenchmarkRun).where(BenchmarkRun.id == run_id))
    row = result.scalar_one_or_none()
    return _run_to_dict(row) if row else None


def _run_to_dict(run: BenchmarkRun) -> dict:
    return {
        "id": run.id,
        "video_id": run.video_id,
        "stage": run.stage,
        "mode": run.mode,
        "model": run.model,
        "input_chars": run.input_chars,
        "output_text": run.output_text,
        "output_chars": run.output_chars,
        "duration_seconds": run.duration_seconds,
        "status": run.status,
        "created_at": run.created_at.isoformat(),
    }


def _resolve_mode(
    source_text: str,
    has_chapters: bool,
    force_map_reduce: bool,
    mode_override: str | None,
) -> str:
    """Determine processing mode — same logic as _run_summary in api.py."""
    if mode_override:
        return mode_override
    if not force_map_reduce and has_chapters and len(source_text) >= MAP_REDUCE_THRESHOLD:
        return "full_extract"
    if len(source_text) < MAP_REDUCE_THRESHOLD and not force_map_reduce:
        return "single"
    return "map_reduce"


async def _run_one_model(
    run_id: int,
    model: str,
    source_text: str,
    mode: str,
    has_chapters: bool,
    ollama_url: str,
    language: str | None,
    video_id: str,
) -> None:
    """Run one model benchmark, update its DB row when done."""
    from models.database import AsyncSessionLocal

    logger.info("benchmark: run_id=%d model=%s mode=%s start", run_id, model, mode)
    started = time.monotonic()

    if mode == "full_extract":
        output, _, _ = await extract_notes(
            source_text,
            model=model,
            ollama_url=ollama_url,
            language=language,
        )
    else:
        force_mr = mode == "map_reduce"
        output, _, _ = await summarize_text(
            source_text,
            model=model,
            ollama_url=ollama_url,
            force_map_reduce=force_mr,
            language=language,
        )

    duration = int(time.monotonic() - started)
    status = "done" if output else "failed"
    output_chars = len(output) if output else 0

    logger.info(
        "benchmark: run_id=%d model=%s status=%s duration=%ds output_chars=%d",
        run_id, model, status, duration, output_chars,
    )

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("""
                UPDATE benchmark_runs
                SET output_text = :output,
                    output_chars = :output_chars,
                    duration_seconds = :duration,
                    status = :status
                WHERE id = :id
            """),
            {
                "output": output,
                "output_chars": output_chars,
                "duration": duration,
                "status": status,
                "id": run_id,
            },
        )
        await db.commit()


async def start_benchmark(
    db: AsyncSession,
    video_id: str,
    models: list[str],
    mode_override: str | None = None,
) -> list[int]:
    """
    Create benchmark_runs rows for each model and launch background tasks.
    Returns list of run IDs (one per model).
    """
    fmt = await get_result(db, video_id)
    if not fmt:
        raise ValueError(f"Video {video_id} not found")

    source_text = fmt.get("cleaned_text") or fmt.get("formatted_text") or ""
    if not source_text:
        raise ValueError("No text available for benchmark")

    has_chapters = bool(fmt.get("chapters"))
    language = fmt.get("language")

    force_map_reduce_raw = await get_app_setting(db, "force_map_reduce") or "false"
    force_map_reduce = force_map_reduce_raw == "true"
    ollama_url = await get_app_setting(db, "ollama_url") or ""

    mode = _resolve_mode(source_text, has_chapters, force_map_reduce, mode_override)
    input_chars = len(source_text)

    run_ids: list[int] = []
    for model in models:
        run = BenchmarkRun(
            video_id=video_id,
            stage="summary",
            mode=mode,
            model=model,
            input_chars=input_chars,
            status="processing",
        )
        db.add(run)
        await db.flush()  # get auto-increment id
        run_ids.append(run.id)

    await db.commit()

    # Fire background tasks — one per model, all parallel
    for run_id, model in zip(run_ids, models):
        asyncio.create_task(
            _run_one_model(
                run_id=run_id,
                model=model,
                source_text=source_text,
                mode=mode,
                has_chapters=has_chapters,
                ollama_url=ollama_url,
                language=language,
                video_id=video_id,
            )
        )

    logger.info(
        "benchmark: started %d models for video=%s mode=%s run_ids=%s",
        len(models), video_id, mode, run_ids,
    )
    return run_ids
