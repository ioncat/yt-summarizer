"""What the result API says about the stages of a video, read from `processing_stages` (NS-25 step 3).

`load_runs` reads every run of a video; `stages_view` is the new `stages` field of GET /api/result/{id}; `legacy_fields`
derives the OLD per-stage fields (`cleanup_status`, `cleanup_error`, `summary_model`, ...) from the same rows, so the
pages and the MCP tools that read them keep working. A stage with no row at all keeps what the old columns say.

Rules (the stage's CURRENT state is its newest run; the shown RESULT is described by its newest 'done' run):
- *_status: newest run processing / done / failed as is; cancelled = nothing running = None.
- *_error: the newest run's error text when it failed, else None.
- cleanup_model / summary_model, *_duration_seconds, *_finished_at, summary_mode / chunks: from the newest DONE run, so a
  failed or cancelled attempt never changes which model or mode the saved text is shown with. While the very first run is
  still going (no done run yet) the running model is shown.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.stage_codes import STAGES


def _dt(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _iso(value) -> str | None:
    d = _dt(value)
    return d.isoformat() if d else None


def _meta(raw) -> dict:
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def load_runs(db: AsyncSession, video_id: str) -> dict[str, list[dict]]:
    """Every run of the video, oldest first, by stage."""
    rows = (await db.execute(
        text("SELECT * FROM processing_stages WHERE video_id = :v ORDER BY id"), {"v": video_id},
    )).mappings().all()
    by_stage: dict[str, list[dict]] = {}
    for r in rows:
        by_stage.setdefault(r["stage"], []).append(dict(r))
    return by_stage


def _last_done(runs: list[dict]) -> dict | None:
    return next((r for r in reversed(runs) if r["status"] == "done"), None)


def _public(run: dict) -> dict:
    return {
        "attempt": run["attempt"], "status": run["status"], "queue_item_id": run["queue_item_id"], "model": run["model"],
        "started_at": _iso(run["started_at"]), "finished_at": _iso(run["finished_at"]),
        "error_code": run["error_code"], "error_text": run["error_text"], "meta": _meta(run["meta"]),
        "progress_done": run["progress_done"], "progress_total": run["progress_total"],
    }


def stages_view(by_stage: dict[str, list[dict]]) -> dict[str, dict]:
    """{stage: newest run + 'last_done' (the run the shown result came from) + 'runs' (how many)} for stages with runs."""
    out: dict[str, dict] = {}
    for stage in STAGES:
        runs = by_stage.get(stage)
        if not runs:
            continue
        done = _last_done(runs)
        out[stage] = {**_public(runs[-1]), "runs": len(runs), "last_done": _public(done) if done else None}
    return out


def _seconds(run: dict | None) -> int | None:
    if run is None:
        return None
    started, finished = _dt(run["started_at"]), _dt(run["finished_at"])
    return int((finished - started).total_seconds()) if started and finished else None


def legacy_fields(by_stage: dict[str, list[dict]]) -> dict:
    """The old result fields for every LLM stage that has runs; the others are not in the dict (the caller keeps its own)."""
    out: dict = {}
    for stage in ("cleanup", "summary", "mindmap"):
        runs = by_stage.get(stage)
        if not runs:
            continue
        latest, done = runs[-1], _last_done(runs)
        out[f"{stage}_status"] = latest["status"] if latest["status"] in ("processing", "done", "failed") else None
        out[f"{stage}_error"] = latest["error_text"] if latest["status"] == "failed" else None
        if stage == "mindmap":
            continue
        out[f"{stage}_model"] = done["model"] if done else (latest["model"] if latest["status"] == "processing" else None)
        out[f"{stage}_duration_seconds"] = _seconds(done)
        out[f"{stage}_finished_at"] = _iso(done["finished_at"]) if done else None
        if stage == "summary":
            meta = _meta(done["meta"]) if done else {}
            out["summary_mode"] = meta.get("mode")
            out["summary_chunks_count"] = meta.get("chunks")
    return out
