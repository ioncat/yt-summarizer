from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.subtitle_extractor import extract_video_id, validate_youtube_url
from services.video_service import get_app_setting

router = APIRouter()

# URL extraction helpers for bulk input parsing
_URL_RE = re.compile(r'https?://[^\s|"\'<>]+')
_TRAIL_RE = re.compile(r'[,;.:!?]+$')


# ---------------------------------------------------------------------------
# Queue endpoints (Epic 34)
# ---------------------------------------------------------------------------

MAX_BULK_ITEMS = 500  # per request, for urls and for video_ids each


class BulkQueueRequest(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=MAX_BULK_ITEMS)
    video_ids: list[str] = Field(default_factory=list, max_length=MAX_BULK_ITEMS)  # results already in History (also local files), queued by id; LLM stages only
    pipeline_stages: list[str] | None = None  # defaults to app_settings queue_default_pipeline
    force: bool = False  # skip dedup check (e.g. re-run stages on already-processed videos)
    language: str | None = None  # subtitle language; None → "auto" (auto-detect)


@router.post("/queue/bulk")
async def queue_bulk_add(
    body: BulkQueueRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add multiple URLs to the processing queue. Skips duplicates (already processed or in queue).

    Every skipped link has an explicit reason: `invalid` lists the links that are not YouTube links; `duplicates` lists the rest
    and `duplicate_details` gives each one's video id and reason: "processed", "in_queue", "in_list" (the same video is earlier
    in this very list) or, for video_ids, "order". The links that were added come back in `ids`, in the order they were sent.
    `report` repeats it as one entry per link in the order sent: {url, video_id, status} with status added / processed / in_queue /
    in_list / invalid (the page shows it as it is). An invalid entry also has `reason`: "http_only" (an http:// link to YouTube:
    only https links are accepted) or "not_youtube".

    `video_ids` queues results that are already in History by id (the only way to queue a local file);
    they can only run the LLM stages (cleanup, summary, mindmap) and the download.

    `force` applies to `urls` only: it skips the "already processed / already in the queue" check so a
    video can be re-run. `video_ids` ignore it: an id that is already pending or processing is always
    reported as a duplicate (two runs of the same stage on one video would overwrite each other). Stage-aware (NS-25):
    only the stages that a queued item already includes are skipped; the other requested stages are still queued, and a
    duplicate names the stages that are already queued.
    At most 500 urls and 500 video_ids per request.
    """
    from services.queue_service import add_items, add_items_unique, get_duplicate_reasons
    from services.queue_by_id import RESULT_STAGES, add_by_video_ids, order_message
    from services.db_retry import retry_locked
    import json as _json

    if not body.urls and not body.video_ids:
        raise HTTPException(status_code=400, detail="No URLs provided")
    if any(not v.strip() for v in body.video_ids):
        raise HTTPException(status_code=400, detail="video_ids contains an empty id")
    if body.video_ids:
        by_id_stages = body.pipeline_stages
        allowed = (*RESULT_STAGES, "download")        # "download": save the video of a result that is already in History (NS-17 item 12)
        if not by_id_stages or any(s not in allowed for s in by_id_stages):
            raise HTTPException(status_code=400, detail={
                "message": "Results already in History can only run: " + ", ".join(allowed)})

    # Step 1: validate + deduplicate within batch
    seen_video_ids: set[str] = set()
    valid_urls: list[str] = []      # the canonical links that are queued
    typed: dict[str, str] = {}      # canonical link -> the link as it was sent (the answer names it that way)
    valid_vid_ids: list[str] = []
    invalid: list[str] = []         # not a YouTube link
    in_list: list[tuple[str, str]] = []   # (the link as typed, its video id): the same video was already earlier in this list
    entries: list[dict] = []        # one per link of the list, in the order sent: the page's per-link report
    for raw_url in body.urls:
        raw = raw_url.strip()
        if not raw:
            continue
        # Extract URL from line — handles "URL | title", trailing punctuation, etc.
        m = _URL_RE.search(raw)
        url = _TRAIL_RE.sub('', m.group(0)) if m else raw
        # the same check as POST /api/process: https and a YouTube host only, stored in the canonical watch?v= form
        canonical = validate_youtube_url(url)
        vid = extract_video_id(canonical) if canonical else None
        if not vid:
            invalid.append(url)
            # an http:// link to a YouTube video is refused (https only) - say that, not "not a YouTube link"
            http_only = url[:7].lower() == "http://" and validate_youtube_url("https://" + url[7:]) is not None
            entries.append({"url": url, "video_id": None, "status": "invalid",
                            "reason": "http_only" if http_only else "not_youtube"})
        elif vid in seen_video_ids:
            in_list.append((url, vid))   # a duplicate in the list is not an invalid link (NS-24): it gets its own reason
            entries.append({"url": url, "video_id": vid, "status": "in_list"})
        else:
            entries.append({"url": url, "video_id": vid, "status": "new"})
            seen_video_ids.add(vid)
            valid_urls.append(canonical)
            typed[canonical] = url
            valid_vid_ids.append(vid)

    if body.urls and not valid_urls and not body.video_ids:
        # (every link was refused: `report` carries each one's reason, as the 200 answer does)
        raise HTTPException(status_code=400, detail={"message": "No valid YouTube URLs", "invalid": invalid, "report": entries})

    # Step 2: check against DB (skip if force=True — re-run mode from History)
    new_urls: list[str] = []
    duplicates: list[str] = []
    duplicate_details: list[dict] = []  # per duplicate url: its video id and why (no URL parsing in the client)
    if body.force:
        new_urls = valid_urls  # no dedup — user explicitly re-queuing
    else:
        duplicate_vids = await retry_locked(lambda: get_duplicate_reasons(db, valid_vid_ids), db, "queue add: duplicate check")
        for url, vid in zip(valid_urls, valid_vid_ids):
            if vid in duplicate_vids:
                duplicates.append(typed[url])
                duplicate_details.append({"url": typed[url], "video_id": vid, "reason": duplicate_vids[vid]})
            else:
                new_urls.append(url)

    for url, vid in in_list:
        duplicates.append(url)
        duplicate_details.append({"url": url, "video_id": vid, "reason": "in_list"})

    # Step 3: determine pipeline_stages
    if body.pipeline_stages is not None:
        stages = body.pipeline_stages
    else:
        raw = await retry_locked(lambda: get_app_setting(db, "queue_default_pipeline"), db, "queue add: default pipeline")
        stages = _json.loads(raw) if raw else ["extract"]

    # Step 4: add only new
    ids: list[int] = []
    if new_urls and body.force:
        ids = await retry_locked(
            lambda: add_items(db, new_urls, stages, language=body.language or None), db, "queue add: insert")
    elif new_urls:
        # check and insert in one statement per link: two identical adds at once give one row, not two
        ids, raced = await retry_locked(
            lambda: add_items_unique(db, new_urls, stages, language=body.language or None), db, "queue add: insert")
        for url, vid in raced:
            duplicates.append(typed.get(url, url))
            duplicate_details.append({"url": typed.get(url, url), "video_id": vid, "reason": "in_queue"})

    missing: list[str] = []
    if body.video_ids:
        by_id = await retry_locked(
            lambda: add_by_video_ids(db, body.video_ids, body.pipeline_stages), db, "queue add: insert by id")
        ids += by_id["ids"]
        duplicates += by_id["duplicates"]
        duplicate_details += [
            {"url": None, "video_id": v,
             "reason": "order" if v in by_id["blocked"] else "in_queue",     # "order": a later stage is queued, its prerequisite is not
             "stages": by_id["blocked"].get(v) or by_id["covered"].get(v, []),
             **({"message": order_message(by_id["blocked"][v], body.pipeline_stages)} if v in by_id["blocked"] else {})}
            for v in by_id["duplicates"]]
        missing = by_id["missing"]

    # the per-link report: "new" turns into "added", or into the reason it was skipped (processed / in_queue)
    skipped = {d["video_id"]: d["reason"] for d in duplicate_details if d["url"] is not None and d["reason"] != "in_list"}
    report = [{**e, "status": skipped.get(e["video_id"], "added") if e["status"] == "new" else e["status"]} for e in entries]
    return {"added": len(ids), "ids": ids, "invalid": invalid, "duplicates": duplicates,
            "duplicate_details": duplicate_details, "missing": missing, "report": report}


@router.get("/queue")
async def get_queue_items(db: Annotated[AsyncSession, Depends(get_db)]):
    """Return all queue items ordered by sort_order + added_at."""
    from services.queue_service import get_queue
    items = await get_queue(db)
    return {"items": items, "count": len(items)}


@router.get("/queue/counts")
async def get_queue_status_counts(db: Annotated[AsyncSession, Depends(get_db)]):
    """Return item counts per status — for nav badge."""
    from services.queue_service import get_queue_counts
    counts = await get_queue_counts(db)
    pending = counts.get("pending", 0)
    processing = counts.get("processing", 0)
    return {"pending": pending, "processing": processing, "active": pending + processing, "counts": counts}


@router.delete("/queue/all")
async def clear_queue_pending(db: Annotated[AsyncSession, Depends(get_db)]):
    """Clear all pending queue items (does not touch processing/done/failed)."""
    from services.queue_service import clear_pending
    count = await clear_pending(db)
    return {"cleared": count}


@router.delete("/queue/failed")
async def clear_queue_failed(db: Annotated[AsyncSession, Depends(get_db)]):
    """Clear all failed queue items, and the partial items that are stuck (nothing left to retry). A partial item that
    can still be retried is kept."""
    from services.queue_service import clear_failed
    count = await clear_failed(db)
    return {"cleared": count}


@router.post("/queue/failed/retry")
async def retry_queue_failed(db: Annotated[AsyncSession, Depends(get_db)]):
    """Reset all failed and partial queue items to pending; a partial item restarts only its failed stages."""
    from services.queue_service import retry_all_failed
    count = await retry_all_failed(db)
    return {"retried": count}


@router.post("/queue/{item_id}/retry")
async def retry_queue_item(item_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    """Reset a single failed or partial queue item to pending."""
    from services.queue_service import retry_item
    result = await retry_item(db, item_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Item not found")
    if result == "not_failed":
        raise HTTPException(status_code=409, detail="Item is not in failed or partial state")
    if result == "nothing_left":
        raise HTTPException(status_code=409, detail="Nothing left to retry: no failed step remains for this video. "
                                                    "Remove the item with Clean failed.")
    return {"retried": item_id}


@router.post("/queue/{item_id}/cancel")
async def cancel_queue_item(item_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    """The Cancel button of a queue row (NS-16): a waiting item is taken out of the queue, a running one is told to stop (it ends
    `skipped` when its current step returns; what it had saved stays)."""
    from services.cancel import cancel_item
    outcome = await cancel_item(db, item_id)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="Item not found")
    if outcome == "not_active":
        raise HTTPException(status_code=409, detail="This item is already over: nothing to cancel")
    return {"status": outcome, "id": item_id}


@router.delete("/queue/{item_id}")
async def delete_queue_item(item_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    """Delete a single pending queue item."""
    from services.queue_service import delete_item
    result = await delete_item(db, item_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Item not found")
    if result == "conflict":
        raise HTTPException(status_code=409, detail="Cannot delete a processing item")
    return {"deleted": item_id}
