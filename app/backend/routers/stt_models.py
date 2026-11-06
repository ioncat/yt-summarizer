from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.video_service import get_app_setting

router = APIRouter()


# ---------------------------------------------------------------------------
# STT model management
# ---------------------------------------------------------------------------

@router.get("/stt/models")
async def get_stt_models(db: Annotated[AsyncSession, Depends(get_db)]):
    """Return full model catalog with downloaded status."""
    from services.transcriber import get_available_models, DEFAULT_CACHE_PATH
    cache_path = (await get_app_setting(db, "stt_cache_path")) or DEFAULT_CACHE_PATH
    engine = (await get_app_setting(db, "stt_engine")) or "faster-whisper"
    return {"engine": engine, "models": get_available_models(cache_path)}


@router.post("/stt/models/{model_name}/download")
async def download_stt_model(
    model_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start downloading a model in the background."""
    from services.transcriber import MODEL_CATALOG, QWEN_CATALOG, DEFAULT_CACHE_PATH, start_model_download, is_model_downloaded
    if model_name not in MODEL_CATALOG and model_name not in QWEN_CATALOG:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")
    cache_path = (await get_app_setting(db, "stt_cache_path")) or DEFAULT_CACHE_PATH
    if is_model_downloaded(model_name, cache_path):
        return {"status": "already_downloaded"}
    started = start_model_download(model_name, cache_path)
    return {"status": "started" if started else "already_downloading"}


@router.get("/stt/models/{model_name}/download/status")
async def get_stt_model_download_status(
    model_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Poll download progress for a model."""
    from services.transcriber import MODEL_CATALOG, QWEN_CATALOG, DEFAULT_CACHE_PATH, get_download_status
    if model_name not in MODEL_CATALOG and model_name not in QWEN_CATALOG:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")
    cache_path = (await get_app_setting(db, "stt_cache_path")) or DEFAULT_CACHE_PATH
    return get_download_status(model_name, cache_path)


@router.delete("/stt/models/{model_name}")
async def delete_stt_model(
    model_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a downloaded model from the cache."""
    from services.transcriber import MODEL_CATALOG, QWEN_CATALOG, DEFAULT_CACHE_PATH, delete_model
    if model_name not in MODEL_CATALOG and model_name not in QWEN_CATALOG:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")
    cache_path = (await get_app_setting(db, "stt_cache_path")) or DEFAULT_CACHE_PATH
    deleted = delete_model(model_name, cache_path)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model not found on disk")
    return {"deleted": model_name}
