#!/usr/bin/env python3
"""MCP Server for YT Summarizer — stdio transport for Claude Desktop / Claude Code."""

import asyncio
import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("YT_SUMMARIZER_URL", "http://localhost:9010").rstrip("/")
POLL_INTERVAL = 3.0
POLL_TIMEOUT = 300  # 5 minutes

# Parts of a result an agent can ask for with get_result(parts=[...]): name -> field of /api/result/{id}
TEXT_PARTS = {
    "summary": "summary_text",
    "transcript": "formatted_text",
    "cleaned": "cleaned_text",
    "mindmap": "mindmap_text",
}
ALL_PARTS = (*TEXT_PARTS, "status")  # status: stage states and error reasons, no text
DEFAULT_TEXT_LIMIT = 20_000  # chars of transcript / cleaned returned when the agent gives no limit

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


def _channel(item: dict) -> str:
    """The backend sends the channel as `author`."""
    return item.get("author") or item.get("channel") or ""


def _size(n: int) -> str:
    return str(n) if n < 1000 else f"{n / 1000:.1f}k".replace(".0k", "k")


def _parts_hint(data: dict) -> str:
    """One line: which parts exist for this video and how long they are (chars)."""
    bits = []
    for part in ("summary", "cleaned", "transcript", "mindmap"):
        text = data.get(TEXT_PARTS[part])
        bits.append(f"{part} {_size(len(text))}" if text else f"{part} none")
    return "Parts (chars): " + " · ".join(bits)


def _format_part(name: str, text: str | None, offset: int, limit: int | None) -> list[str]:
    """One text part, cut to [offset, offset+limit) with the range, the total and the next offset."""
    title = name.capitalize()
    if not text:
        return [f"## {title}", "(not available for this video)", ""]
    total = len(text)
    if limit is None and name in ("transcript", "cleaned"):
        limit = DEFAULT_TEXT_LIMIT
    if offset >= total:
        return [f"## {title} (offset {offset} is past the end; total {total} chars)", ""]
    chunk = text[offset:] if limit is None else text[offset:offset + limit]
    end = offset + len(chunk)
    nxt = "end" if end >= total else f"next: offset={end}"
    return [f"## {title} (chars {offset}–{end} of {total}) · {nxt}", chunk, ""]


def _format_status(data: dict) -> list[str]:
    """State of the three LLM stages, with the reason when one failed."""
    def line(stage: str, extra: list[str]) -> str:
        status = data.get(f"{stage}_status") or "not run"
        bits = [status] + [e for e in extra if e]
        if data.get(f"{stage}_error"):
            bits.append(f"error: {data[f'{stage}_error']}")
        return f"- {stage}: " + " · ".join(bits)

    def secs(key: str) -> str:
        return f"{int(data[key])}s" if data.get(key) else ""

    summary_mode = data.get("summary_mode") or ""
    if summary_mode and data.get("summary_chunks_count"):
        summary_mode += f" ({data['summary_chunks_count']} chunks)"
    return [
        "## Status",
        line("cleanup", [f"model {data['cleanup_model']}" if data.get("cleanup_model") else "", secs("cleanup_duration_seconds")]),
        line("summary", [f"model {data['summary_model']}" if data.get("summary_model") else "", summary_mode,
                         secs("summary_duration_seconds")]),
        line("mindmap", []),
        "",
    ]


def _format_parts(data: dict, parts: list[str], offset: int, limit: int | None) -> str:
    lines: list[str] = _header_lines(data)
    for name in dict.fromkeys(parts):  # in the order asked, each once
        if name == "status":
            lines.extend(_format_status(data))
        else:
            lines.extend(_format_part(name, data.get(TEXT_PARTS[name]), offset, limit))
    lines.append(f"video_id: {data.get('video_id', '')}")
    return "\n".join(lines)


def _header_lines(data: dict) -> list[str]:
    lines = [f"# {data.get('title') or data.get('video_id', 'Unknown')}"]
    meta: list[str] = []
    if _channel(data):
        meta.append(f"Channel: {_channel(data)}")
    if data.get("duration"):
        meta.append(f"Duration: {int(data['duration']) // 60} min")
    if data.get("language"):
        meta.append(f"Language: {data['language']}")
    if meta:
        lines.append(" · ".join(meta))
    lines.append(_parts_hint(data))
    lines.append("")
    return lines


def _format_result(data: dict, include_text: bool = False) -> str:
    lines: list[str] = _header_lines(data)

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
async def get_result(
    video_id: str,
    parts: list[str] | None = None,
    offset: int = 0,
    limit: int | None = None,
    include_text: bool = False,
) -> str:
    """Get the result for an already-processed video.

    With no `parts` you get the summary (or a note that there is none), as before.
    Every answer has a line "Parts (chars): ..." showing what exists for the video and how long it is.

    Args:
        video_id: the video ID (11-char YouTube ID or 'file-...' for local files)
        parts: what to return, any of: summary, transcript (raw), cleaned, mindmap, status
            (status: state, model, time and the error reason of cleanup, summary and mindmap)
        offset: first character to return of each text part (default 0)
        limit: how many characters of each text part (default: 20000 for transcript and cleaned,
            all of summary and mindmap). Every part shows "chars A–B of TOTAL" and "next: offset=B"
            (or "end"), so a long transcript can be read in pieces.
        include_text: old switch: with no summary, show the transcript (ignored when parts is given)
    """
    if parts:
        unknown = [p for p in parts if p not in ALL_PARTS]
        if unknown:
            return f"ERROR: unknown part '{unknown[0]}'. Allowed: {', '.join(ALL_PARTS)}"
    if offset < 0 or (limit is not None and limit <= 0):
        return "ERROR: offset must be >= 0 and limit must be > 0"
    async with _client() as client:
        try:
            r = await client.get(f"/api/result/{video_id}")
        except httpx.ConnectError:
            return f"ERROR: Cannot connect to YT Summarizer at {BASE_URL}"

        if r.status_code == 404:
            return f"ERROR: video_id '{video_id}' not found in history"

        if parts:
            return _format_parts(r.json(), parts, offset, limit)
        return _format_result(r.json(), include_text=include_text)


HISTORY_PAGE_SIZE = 20  # the backend's page size
MAX_QUERY_LEN = 200  # the backend refuses longer text-search queries; a longer one would also overflow the URL


async def _search_in_texts(query: str, limit: int) -> str:
    """Words inside the transcript / cleaned text / summary / mind map of every video."""
    if len(query.strip()) < 3:
        return "ERROR: in_text needs a query of at least 3 characters"
    async with _client() as client:
        try:
            r = await client.get("/api/history/text-search", params={"q": query.strip(), "limit": limit})
        except httpx.ConnectError:
            return f"ERROR: Cannot connect to YT Summarizer at {BASE_URL}"
    if r.status_code != 200:
        return f"ERROR {r.status_code}: {r.text[:300]}"
    data = r.json()
    videos = data.get("videos", [])
    looked = ""
    if data.get("total_videos") is not None:
        looked = f" Looked through {data.get('searched', data['total_videos'])} of {data['total_videos']} video(s)."
    if not videos:
        return f"No videos contain '{query}'.{looked}"
    lines = [f"Found {len(videos)} video(s) with '{query}' in their text.{looked}"]
    for v in videos:
        lines.append(f"- {v.get('title') or 'Unknown'}{f' — {_channel(v)}' if _channel(v) else ''}  (video_id: {v['video_id']})")
        for m in v.get("matches", []):
            n = v.get("counts", {}).get(m["part"], 1)
            lines.append(f"  - {m['part']} ×{n}, first at char {m['position']}: {m['snippet']}")
    lines.append("Read around a hit: get_result(video_id, parts=[<part>], offset=<char - 300>, limit=2000)")
    return "\n".join(lines)


@mcp.tool()
async def search_history(query: str = "", limit: int = 20, in_text: bool = False) -> str:
    """Search processed videos by title or channel name (the whole history).
    Returns the most recent videos if query is empty.
    With in_text=True, search the words inside the texts instead (transcript, cleaned text,
    summary, mind map): the answer gives, per video and part, how many hits there are and the
    character position of the first one with a snippet, to read on with get_result(offset=...).
    It scans every text, so it can take seconds on a large history; the answer says how many
    videos were looked through (it stops early once `limit` videos matched).

    Args:
        query: text to search in video titles and channel names (in_text: the words to find, 3+ chars)
        limit: maximum number of videos to return (default 20)
        in_text: search inside the texts instead of titles and channels
    """
    if len(query.strip()) > MAX_QUERY_LEN:
        return f"ERROR: query is too long ({len(query.strip())} chars, at most {MAX_QUERY_LEN})"
    if in_text:
        return await _search_in_texts(query, limit)

    items: list[dict] = []
    async with _client() as client:
        page = 1
        while True:
            params: dict = {"page": page}
            if query:
                params["search"] = query
            try:
                r = await client.get("/api/history", params=params)
            except httpx.ConnectError:
                return f"ERROR: Cannot connect to YT Summarizer at {BASE_URL}"
            got = r.json().get("items", [])
            items.extend(got)
            if len(got) < HISTORY_PAGE_SIZE or len(items) >= limit:
                break
            page += 1

    if query:
        q = query.lower()
        items = [
            i for i in items
            if q in (i.get("title") or "").lower() or q in _channel(i).lower()
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
        channel = f" — {_channel(item)}" if _channel(item) else ""
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
