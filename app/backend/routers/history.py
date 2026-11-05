from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.text_search import MAX_QUERY_LEN, MIN_QUERY_LEN, search_texts
from services.video_service import delete_video, get_history

router = APIRouter()


@router.get("/history")
async def list_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = 1,
    search: str | None = None,
    favorites_only: bool = False,
):
    return await get_history(db, page=page, search=search or None, favorites_only=favorites_only)


@router.get("/history/text-search")
async def search_history_texts(
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = "",
    limit: int = 20,
):
    """Find videos by words inside their transcript, cleaned text, summary or mind map (read-only)."""
    q = q.strip()
    if len(q) < MIN_QUERY_LEN:
        raise HTTPException(status_code=400, detail=f"Query must be at least {MIN_QUERY_LEN} characters")
    if len(q) > MAX_QUERY_LEN:
        raise HTTPException(status_code=400, detail=f"Query must be at most {MAX_QUERY_LEN} characters")
    return await search_texts(db, q, limit=max(1, min(limit, 50)))


class BulkDeleteRequest(BaseModel):
    video_ids: list[str]


@router.post("/history/delete-bulk")
async def delete_results_bulk(
    body: BulkDeleteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete multiple videos by video_id. Returns counts of deleted and not found."""
    if not body.video_ids:
        raise HTTPException(status_code=400, detail="No video_ids provided")
    deleted = 0
    not_found = 0
    for vid in body.video_ids:
        ok = await delete_video(db, vid)
        if ok:
            deleted += 1
        else:
            not_found += 1
    return {"deleted": deleted, "not_found": not_found}
