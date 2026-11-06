"""One cancel path for every queued job (NS-16).

`cancel_item` serves both kinds of button (the Queue page's row, the result page's Stop):
- a WAITING item is taken out of the queue (it never started; the release hooks of `delete_item` tidy the stage statuses, the
  upload's task and the re-extract's run row);
- a RUNNING item is told to stop: its current stage polls a flag, ends by resetting its own status and keeps the previous
  result, and the worker ends the item `skipped` (the run `cancelled`). A step that cannot be cut short (yt-dlp) ends first; the
  worker checks the item's flag right after it, before the next stage starts.
"""
from __future__ import annotations

import json

from sqlalchemy import text

from services.stage_control import CLEANUP_CANCEL, ITEM_CANCEL, MINDMAP_CANCEL, SUMMARY_CANCEL, TRANSCRIBE_CANCEL

CANCELLED_MESSAGE = "Cancelled"
_STAGE_FLAGS = {"cleanup": CLEANUP_CANCEL, "summary": SUMMARY_CANCEL, "mindmap": MINDMAP_CANCEL}


async def _signal(db, item_id: int, video_id: str | None, stages: list[str], url: str) -> None:
    """Tell the running item to stop: the item's own flag (checked between stages) and the flag of the stage it is in."""
    from services.file_stt import LOCAL_PREFIX
    from services.subtitle_extractor import extract_video_id

    ITEM_CANCEL.add(item_id)
    video_id = video_id or extract_video_id(url or "")
    if not video_id:
        return
    if "reextract" in stages or (url or "").startswith(LOCAL_PREFIX):
        TRANSCRIBE_CANCEL.add(video_id)                      # a re-extract or an uploaded file: the segment loop polls this one
        return
    stage = (await db.execute(
        text("SELECT stage FROM processing_stages WHERE queue_item_id = :i AND status = 'processing' ORDER BY id DESC LIMIT 1"),
        {"i": item_id},
    )).scalar()
    if stage in _STAGE_FLAGS:
        _STAGE_FLAGS[stage].add(video_id)


async def cancel_item(db, item_id: int, upload_message: str = CANCELLED_MESSAGE) -> str:
    """Cancel one queue item. Returns "removed" (it was waiting), "stopping" (it is running and was told to stop),
    "not_found" or "not_active" (it is over: done, failed, partial or skipped). `upload_message` is what the task of a removed
    upload shows."""
    from services.queue_service import delete_item

    row = (await db.execute(
        text("SELECT status, video_id, pipeline_stages, url FROM processing_queue WHERE id = :id"), {"id": item_id},
    )).first()
    if row is None:
        return "not_found"
    status, video_id, stages_json, url = row
    if status not in ("pending", "processing"):
        return "not_active"
    if status == "pending":
        outcome = await delete_item(db, item_id, upload_message)
        if outcome == "deleted":
            return "removed"
        if outcome == "not_found":
            return "not_found"                                 # taken out by someone else a moment ago
        # "conflict": the worker picked it up in the meantime - it is running now, tell it to stop
    await _signal(db, item_id, video_id, json.loads(stages_json) if stages_json else ["extract"], url)
    return "stopping"


async def cancel_video_jobs(db, video_id: str, stage: str | None = None, upload_message: str = CANCELLED_MESSAGE) -> dict:
    """Cancel the waiting / running items of a video (the result page's Stop). With `stage`, only the items that include that
    stage (the old per-stage endpoints). Returns {"removed": n, "stopping": n}."""
    rows = (await db.execute(
        text("SELECT id, pipeline_stages FROM processing_queue WHERE video_id = :v AND status IN ('pending', 'processing') "
             "ORDER BY id"), {"v": video_id},
    )).fetchall()
    counts = {"removed": 0, "stopping": 0}
    for item_id, stages_json in rows:
        if stage is not None and stage not in (json.loads(stages_json) if stages_json else ["extract"]):
            continue
        outcome = await cancel_item(db, item_id, upload_message)
        if outcome in counts:
            counts[outcome] += 1
    return counts


def outcome_of(counts: dict) -> str:
    """The per-stage Stop endpoints' answer: "stopping" (a running item was told to stop), "stopped" (only waiting ones were
    removed) or "none" (nothing was waiting or running)."""
    return "stopping" if counts["stopping"] else "stopped" if counts["removed"] else "none"
