"""Fill `processing_stages` from the old per-stage columns of subtitles_formatted (NS-25, migration step 1: add first).

Idempotent: a (video_id, stage) pair that already has any row is never touched, so running it on every start is safe and
a stage run recorded by the new code is never duplicated. The old columns are NOT changed or dropped here.

One row per stage that has data for the newest subtitles_formatted row of a video:
- cleanup / summary / mindmap: a 'done' row when a result text is saved (model, times, summary mode and chunks from the old
  columns), and a 'failed' row (with its error text and a reason code) when the status says failed - both, in that order,
  when a failed re-run sits on top of an older saved result (the failed row is then the latest, the done row the last success);
- extract or transcribe: one 'done' row for how the text got there (captions, or speech-to-text with its model and device);
- a 'processing' status is not copied (a run that was cut off by a restart is reset by the start-up code).
Every copied row carries meta {"legacy": true}.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text

from services.stage_codes import classify_error

logger = logging.getLogger("api")

_LATEST = """
    SELECT v.video_id AS vid, sf.created_at AS fmt_created, sf.subtitle_source AS source,
           sf.transcription_model AS t_model, sf.transcription_device AS t_device,
           sf.transcription_started_at AS t_started, sf.transcription_finished_at AS t_finished,
           sf.cleaned_text AS cleaned_text, sf.cleanup_status AS cleanup_status, sf.cleanup_model AS cleanup_model,
           sf.cleanup_started_at AS cleanup_started, sf.cleanup_finished_at AS cleanup_finished,
           sf.cleanup_error AS cleanup_error,
           sf.summary_text AS summary_text, sf.summary_status AS summary_status, sf.summary_model AS summary_model,
           sf.summary_mode AS summary_mode, sf.summary_chunks_count AS summary_chunks,
           sf.summary_started_at AS summary_started, sf.summary_finished_at AS summary_finished,
           sf.summary_error AS summary_error,
           sf.mindmap_text AS mindmap_text, sf.mindmap_status AS mindmap_status, sf.mindmap_error AS mindmap_error
    FROM subtitles_formatted sf
    JOIN videos v ON v.id = sf.video_id
    WHERE v.url NOT LIKE '__pending__%'
      AND sf.id = (SELECT s2.id FROM subtitles_formatted s2 WHERE s2.video_id = sf.video_id
                   ORDER BY s2.created_at DESC LIMIT 1)
"""

_INSERT = """
    INSERT INTO processing_stages
        (video_id, stage, status, queue_item_id, attempt, model, started_at, finished_at,
         error_code, error_text, meta, created_at)
    VALUES
        (:video_id, :stage, :status, NULL, :attempt, :model, :started_at, :finished_at,
         :error_code, :error_text, :meta, :created_at)
"""


def _row(r, stage, status, attempt, model=None, started=None, finished=None, error=None, meta=None):
    return {
        "video_id": r["vid"], "stage": stage, "status": status, "attempt": attempt, "model": model,
        "started_at": started, "finished_at": finished,
        "error_code": (classify_error(error) or "unexpected") if status == "failed" else None,   # a failed run always has a code
        "error_text": error if status == "failed" else None,
        "meta": json.dumps({"legacy": True, **(meta or {})}),
        "created_at": finished or started or r["fmt_created"],
    }


def _stage_rows(r, stage, saved, status, model, started, finished, error, meta):
    """The saved result as a 'done' row, then a 'failed' row if the last run failed."""
    out = []
    if saved:
        out.append(_row(r, stage, "done", 1, model, started, finished, None, meta))
    if status == "failed":
        out.append(_row(r, stage, "failed", len(out) + 1, model, None, finished, error or None, None))
    return out


def rows_for(r) -> dict[str, list[dict]]:
    """The legacy rows of one video (r = one row of _LATEST), by stage."""
    rows: dict[str, list[dict]] = {}
    if r["source"] == "transcript":
        rows["transcribe"] = [_row(r, "transcribe", "done", 1, r["t_model"], r["t_started"], r["t_finished"],
                                   None, {"device": r["t_device"]} if r["t_device"] else None)]
    elif r["source"]:
        rows["extract"] = [_row(r, "extract", "done", 1, None, None, r["fmt_created"], None, {"source": r["source"]})]
    rows["cleanup"] = _stage_rows(r, "cleanup", bool(r["cleaned_text"]), r["cleanup_status"], r["cleanup_model"],
                                  r["cleanup_started"], r["cleanup_finished"], r["cleanup_error"], None)
    rows["summary"] = _stage_rows(
        r, "summary", bool(r["summary_text"]), r["summary_status"], r["summary_model"], r["summary_started"],
        r["summary_finished"], r["summary_error"],
        {k: v for k, v in (("mode", r["summary_mode"]), ("chunks", r["summary_chunks"])) if v is not None})
    rows["mindmap"] = _stage_rows(r, "mindmap", bool(r["mindmap_text"]), r["mindmap_status"], None, None, None,
                                  r["mindmap_error"], None)
    return {stage: lst for stage, lst in rows.items() if lst}


async def backfill_processing_stages(conn) -> dict[str, int]:
    """Insert the legacy rows that are missing. `conn` is an open connection (inside a transaction). Returns {stage: rows}."""
    existing = {(r[0], r[1]) for r in (await conn.execute(text("SELECT video_id, stage FROM processing_stages"))).fetchall()}
    latest = (await conn.execute(text(_LATEST))).mappings().all()
    batch: list[dict] = []
    counts: dict[str, int] = {}
    for r in latest:
        for stage, rows in rows_for(r).items():
            if (r["vid"], stage) in existing:
                continue
            batch.extend(rows)
            counts[stage] = counts.get(stage, 0) + len(rows)
    for i in range(0, len(batch), 500):
        await conn.execute(text(_INSERT), batch[i:i + 500])
    if batch:
        logger.info("startup: processing_stages filled from the old columns: %s", counts)
    return counts
