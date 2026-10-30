#!/usr/bin/env python3
"""MCP Server for YT Summarizer — stdio transport for Claude Desktop / Claude Code."""

import asyncio
import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("YT_SUMMARIZER_URL", "http://localhost:9010").rstrip("/")
POLL_INTERVAL = 3.0
POLL_TIMEOUT = 300  # 5 minutes

mcp = FastMCP(
    "yt-summarizer",
    instructions="Extract and summarize YouTube video transcripts",
)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)


async def _poll_task(client: httpx.AsyncClient, task_id: str, video_id: str) -> dict:
    elapsed = 0.0
    while elapsed < POLL_TIMEOUT:
        resp = await client.get(f"/api/status/{task_id}")
        data = resp.json()
        status = data.get("status", "")
        if status == "completed":
            r = await client.get(f"/api/result/{video_id}")
            return r.json()
        if status == "failed":
            raise RuntimeError(data.get("error_message") or "Processing failed")
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    raise TimeoutError(f"Timed out after {POLL_TIMEOUT}s. Retrieve later with get_result(video_id='{video_id}')")


async def _poll_cleanup(client: httpx.AsyncClient, video_id: str) -> dict:
    elapsed = 0.0
    while elapsed < POLL_TIMEOUT:
        r = await client.get(f"/api/result/{video_id}")
        data = r.json()
        s = data.get("cleanup_status")
        if s == "done":
            return data
        if s == "failed":
            raise RuntimeError("AI cleanup failed — check model settings")
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    raise TimeoutError(f"Cleanup timed out after {POLL_TIMEOUT}s")


async def _poll_summary(client: httpx.AsyncClient, video_id: str) -> dict:
    elapsed = 0.0
    while elapsed < POLL_TIMEOUT:
        r = await client.get(f"/api/result/{video_id}")
        data = r.json()
        s = data.get("summary_status")
        if s == "done":
            return data
        if s == "failed":
            raise RuntimeError("Summarization failed — check model settings")
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    raise TimeoutError(f"Summarization timed out after {POLL_TIMEOUT}s")


def _format_result(data: dict, include_text: bool = False) -> str:
    lines: list[str] = []

    title = data.get("title") or data.get("video_id", "Unknown")
    lines.append(f"# {title}")

    meta: list[str] = []
    if data.get("channel"):
        meta.append(f"Channel: {data['channel']}")
    if data.get("duration"):
        mins = int(data["duration"]) // 60
        meta.append(f"Duration: {mins} min")
    if data.get("language"):
        meta.append(f"Language: {data['language']}")
    if meta:
        lines.append(" · ".join(meta))
    lines.append("")

    if data.get("summary_text"):
        lines.append("## Summary")
        lines.append(data["summary_text"])
    elif include_text:
        text = data.get("cleaned_text") or data.get("formatted_text") or ""
        if text:
            MAX = 20_000
            if len(text) > MAX:
                lines.append(f"[Transcript truncated — showing first {MAX} of {len(text)} chars]")
                text = text[:MAX]
            lines.append(text)
        else:
            lines.append("(No text available)")
    else:
        lines.append(
            "(No summary yet. Use run_summary(video_id) to generate one, "
            "or set include_text=True to read the raw transcript.)"
        )

    lines.append("")
    lines.append(f"video_id: {data.get('video_id', '')}")
    return "\n".join(lines)


# ─── Tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
async def process_video(url: str, language: str = "auto") -> str:
    """Extract subtitles from a YouTube video and return the result.
    If the video was already processed, returns the existing result immediately.

    Args:
        url: YouTube video URL (youtube.com/watch or youtu.be)
        language: subtitle language code ('en', 'ru', etc.) or 'auto' for auto-detection
    """
    async with _client() as client:
        try:
            resp = await client.post("/api/process", json={"url": url, "language": language})
        except httpx.ConnectError:
            return f"ERROR: Cannot connect to YT Summarizer at {BASE_URL}. Make sure the backend is running."

        if resp.status_code == 409:
            video_id = resp.json().get("video_id", "")
            r = await client.get(f"/api/result/{video_id}")
            return _format_result(r.json())

        if resp.status_code != 200:
            return f"ERROR {resp.status_code}: {resp.text[:300]}"

        data = resp.json()
        task_id = data["task_id"]
        video_id = data["video_id"]

        try:
            result = await _poll_task(client, task_id, video_id)
        except (TimeoutError, RuntimeError) as e:
            return f"ERROR: {e}"

        return _format_result(result)


@mcp.tool()
async def get_result(video_id: str, include_text: bool = False) -> str:
    """Get the result for an already-processed video.

    Args:
        video_id: the video ID (11-char YouTube ID or 'file-...' for local files)
        include_text: if True, include the full transcript (can be very long)
    """
    async with _client() as client:
        try:
            r = await client.get(f"/api/result/{video_id}")
        except httpx.ConnectError:
            return f"ERROR: Cannot connect to YT Summarizer at {BASE_URL}"

        if r.status_code == 404:
            return f"ERROR: video_id '{video_id}' not found in history"

        return _format_result(r.json(), include_text=include_text)


@mcp.tool()
async def search_history(query: str = "", limit: int = 20) -> str:
    """Search processed videos by title or channel name.
    Returns the most recent videos if query is empty.

    Args:
        query: text to search in video titles and channel names
        limit: maximum number of results to return (default 20)
    """
    async with _client() as client:
        try:
            r = await client.get("/api/history", params={"page": 1})
        except httpx.ConnectError:
            return f"ERROR: Cannot connect to YT Summarizer at {BASE_URL}"

        items = r.json().get("items", [])

    if query:
        q = query.lower()
        items = [
            i for i in items
            if q in (i.get("title") or "").lower() or q in (i.get("channel") or "").lower()
        ]

    items = items[:limit]

    if not items:
        return "No videos found."

    lines: list[str] = [f"Found {len(items)} video(s):"]
    for item in items:
        flags: list[str] = []
        if item.get("has_summary"):
            flags.append("summary")
        if item.get("has_cleaned"):
            flags.append("cleaned")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        channel = f" — {item['channel']}" if item.get("channel") else ""
        lines.append(f"- {item.get('title', 'Unknown')}{channel}{flag_str}  (video_id: {item['video_id']})")

    return "\n".join(lines)


@mcp.tool()
async def run_cleanup(video_id: str) -> str:
    """Run AI text cleanup on extracted subtitles. Waits until complete (up to 5 min).
    Requires Ollama to be running with a model configured in Settings.

    Args:
        video_id: the video ID to clean up
    """
    async with _client() as client:
        try:
            health = await client.get("/api/health")
            if not health.json().get("ollama"):
                return "ERROR: Ollama is not available. Start Ollama and configure a model in Settings → AI Cleanup."

            resp = await client.post(f"/api/result/{video_id}/cleanup")
            if resp.status_code == 404:
                return f"ERROR: video_id '{video_id}' not found"

            result = await _poll_cleanup(client, video_id)
        except httpx.ConnectError:
            return f"ERROR: Cannot connect to YT Summarizer at {BASE_URL}"
        except (TimeoutError, RuntimeError) as e:
            return f"ERROR: {e}"

    cleaned = result.get("cleaned_text") or ""
    duration = result.get("cleanup_duration_seconds")
    dur_str = f" in {int(duration)}s" if duration else ""
    return f"Cleanup complete{dur_str}. Cleaned text: {len(cleaned):,} chars.\nvideo_id: {video_id}"


@mcp.tool()
async def run_summary(video_id: str) -> str:
    """Run summarization on a video. Uses cleaned text if available, otherwise raw transcript.
    Waits until complete (up to 5 min).
    Requires Ollama to be running with a model configured in Settings.

    Args:
        video_id: the video ID to summarize
    """
    async with _client() as client:
        try:
            health = await client.get("/api/health")
            if not health.json().get("ollama"):
                return "ERROR: Ollama is not available. Start Ollama and configure a model in Settings → Summarization."

            resp = await client.post(f"/api/result/{video_id}/summary")
            if resp.status_code == 404:
                return f"ERROR: video_id '{video_id}' not found"

            result = await _poll_summary(client, video_id)
        except httpx.ConnectError:
            return f"ERROR: Cannot connect to YT Summarizer at {BASE_URL}"
        except (TimeoutError, RuntimeError) as e:
            return f"ERROR: {e}"

    summary = result.get("summary_text") or ""
    duration = result.get("summary_duration_seconds")
    dur_str = f" in {int(duration)}s" if duration else ""
    return f"Summary complete{dur_str}.\n\n{summary}\n\nvideo_id: {video_id}"


if __name__ == "__main__":
    mcp.run()
