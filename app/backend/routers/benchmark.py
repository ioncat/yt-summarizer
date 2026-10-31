from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db

router = APIRouter()


class BenchmarkRunRequest(BaseModel):
    video_id: str
    models: list[str]
    mode_override: str | None = None  # 'single' | 'map_reduce' | 'full_extract' | None
    stage: str = "summary"  # 'summary' | 'cleanup'


@router.post("/benchmark/run")
async def start_benchmark_run(
    request: BenchmarkRunRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start benchmark: run N models on the same video text in parallel."""
    from services.benchmark_service import start_benchmark
    if not request.models:
        raise HTTPException(status_code=400, detail="No models specified")
    if len(request.models) > 4:
        raise HTTPException(status_code=400, detail="Maximum 4 models per benchmark")
    if request.stage not in ("summary", "cleanup"):
        raise HTTPException(status_code=400, detail="stage must be 'summary' or 'cleanup'")
    try:
        run_ids = await start_benchmark(
            db,
            video_id=request.video_id,
            models=request.models,
            mode_override=request.mode_override,
            stage=request.stage,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"run_ids": run_ids, "count": len(run_ids)}


@router.get("/benchmarks")
async def list_all_benchmarks(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return all benchmark runs grouped by video."""
    from services.benchmark_service import get_all_benchmarks_grouped
    groups = await get_all_benchmarks_grouped(db)
    return {"groups": groups}


@router.get("/benchmark/{video_id}")
async def get_benchmark(
    video_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return all benchmark runs for a video."""
    from services.benchmark_service import get_benchmark_runs
    runs = await get_benchmark_runs(db, video_id)
    return {"runs": runs}


@router.get("/benchmark/run/{run_id}")
async def get_benchmark_run_detail(
    run_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return a single benchmark run by ID."""
    from services.benchmark_service import get_benchmark_run
    run = await get_benchmark_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.delete("/benchmark/run/{run_id}")
async def delete_benchmark_run_endpoint(
    run_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a single benchmark run by ID."""
    from services.benchmark_service import delete_benchmark_run
    ok = await delete_benchmark_run(db, run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"deleted": run_id}
