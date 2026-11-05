from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request as _Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.ollama_options import build_options
from services.video_service import get_app_setting

from services.mcp_connect import (
    connect as mcp_connect_exec,
    disconnect as mcp_disconnect_exec,
    get_status as mcp_get_status,
)

import json

logger = logging.getLogger("api")

router = APIRouter()


@router.get("/health")
async def health_check(db: Annotated[AsyncSession, Depends(get_db)]):
    """Returns backend status and Ollama availability."""
    ollama_ok = False
    ollama_url = await get_app_setting(db, "ollama_url")
    if ollama_url:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{ollama_url}/api/tags")
                ollama_ok = resp.status_code == 200
        except Exception:
            pass
    return {"backend": True, "ollama": ollama_ok}


@router.get("/models")
async def list_models(db: Annotated[AsyncSession, Depends(get_db)]):
    """Return available Ollama models."""
    ollama_url = await get_app_setting(db, "ollama_url")
    if not ollama_url:
        raise HTTPException(status_code=400, detail="Ollama URL not configured")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return {"models": models}
    except Exception:
        raise HTTPException(status_code=503, detail="Ollama unavailable")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str


@router.post("/chat")
async def chat_proxy(body: ChatRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    """Proxy a chat request to Ollama with streaming — avoids browser CORS restrictions."""
    ollama_url = await get_app_setting(db, "ollama_url")
    if not ollama_url:
        raise HTTPException(status_code=400, detail="Ollama URL not configured")

    payload = {
        "model": body.model,
        "stream": True,
        "messages": [{"role": m.role, "content": m.content} for m in body.messages],
        "options": build_options(
            *(m.content for m in body.messages),
            max_ctx=int(await get_app_setting(db, "chat_num_ctx") or 32768),
        ),
    }

    async def stream_ollama():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", f"{ollama_url}/api/chat", json=payload) as resp:
                    if resp.status_code != 200:
                        yield json.dumps({"error": f"Ollama error {resp.status_code}"}).encode()
                        return
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except Exception as exc:
            yield json.dumps({"error": str(exc)}).encode()

    return StreamingResponse(stream_ollama(), media_type="application/x-ndjson")


@router.get("/mcp/status")
async def get_mcp_status():
    """Return Claude Desktop connection status (reads config from disk)."""
    return mcp_get_status()


class McpConnectBody(BaseModel):
    confirm: bool = False
    replace_broken: bool = False


@router.post("/mcp/connect")
async def post_mcp_connect(body: McpConnectBody, request: _Request):
    """Plan (confirm=false) or execute (confirm=true) adding the MCP entry to Claude Desktop config."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", ""):
        raise HTTPException(status_code=403, detail="MCP connect is only allowed from localhost")
    result = mcp_connect_exec(confirm=body.confirm, replace_broken=body.replace_broken)
    if not body.confirm and "planned" in result:
        return result
    if not result.get("ok") and not body.confirm:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.delete("/mcp/connect")
async def delete_mcp_connect(request: _Request):
    """Remove the yt-summarizer entry from Claude Desktop config."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", ""):
        raise HTTPException(status_code=403, detail="MCP disconnect is only allowed from localhost")
    return mcp_disconnect_exec()
