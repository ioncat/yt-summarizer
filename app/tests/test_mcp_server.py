"""Tests for app/mcp_server.py — all HTTP calls mocked via respx."""

import asyncio
import sys
import os
from unittest.mock import patch

import httpx
import pytest
import respx

# Make `app/` importable so `import mcp_server` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_server import process_video, get_result, search_history, run_cleanup, run_summary  # noqa: E402

BASE = "http://localhost:9010"


async def _noop_sleep(_seconds):
    """Drop-in replacement for asyncio.sleep that returns immediately."""
    return None


def _seq(*responses):
    """Return a side_effect callable that yields responses one by one per request."""
    it = iter(responses)

    def _side_effect(_request):
        return next(it)

    return _side_effect


# ─── process_video ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_video_success():
    """process_video polls until 'completed' and returns formatted result."""
    with respx.mock(assert_all_called=False) as mock, patch("asyncio.sleep", _noop_sleep):
        mock.post(f"{BASE}/api/process").mock(
            return_value=httpx.Response(200, json={"task_id": "task1", "video_id": "vid1"})
        )
        mock.get(f"{BASE}/api/status/task1").mock(
            side_effect=_seq(
                httpx.Response(200, json={"status": "processing"}),
                httpx.Response(200, json={"status": "completed"}),
            )
        )
        mock.get(f"{BASE}/api/result/vid1").mock(
            return_value=httpx.Response(200, json={
                "video_id": "vid1",
                "title": "Great Tutorial",
                "channel": "Tech Channel",
                "duration": 600,
                "language": "en",
                "formatted_text": "Hello world",
            })
        )

        result = await process_video("https://youtube.com/watch?v=vid1")

    assert "Great Tutorial" in result
    assert "vid1" in result


@pytest.mark.asyncio
async def test_process_video_already_processed():
    """409 response means video already exists — fetches and returns existing result."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{BASE}/api/process").mock(
            return_value=httpx.Response(409, json={"video_id": "vid409"})
        )
        mock.get(f"{BASE}/api/result/vid409").mock(
            return_value=httpx.Response(200, json={
                "video_id": "vid409",
                "title": "Already Processed Video",
                "formatted_text": "Some subtitle text",
            })
        )

        result = await process_video("https://youtube.com/watch?v=vid409")

    assert "Already Processed Video" in result
    assert "vid409" in result


@pytest.mark.asyncio
async def test_process_video_connect_error():
    """Backend unreachable → returns string containing ERROR."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{BASE}/api/process").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await process_video("https://youtube.com/watch?v=test")

    assert "ERROR" in result


# ─── get_result ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_result_found():
    """get_result returns formatted result containing title and video_id."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/result/vid123").mock(
            return_value=httpx.Response(200, json={
                "video_id": "vid123",
                "title": "My Video",
                "channel": "Some Channel",
                "duration": 300,
                "language": "ru",
                "formatted_text": "transcript text here",
            })
        )

        result = await get_result("vid123")

    assert "My Video" in result
    assert "vid123" in result


@pytest.mark.asyncio
async def test_get_result_not_found():
    """404 from backend → returns string with ERROR."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/result/missing").mock(
            return_value=httpx.Response(404, json={"detail": "Not found"})
        )

        result = await get_result("missing")

    assert "ERROR" in result


# ─── search_history ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_history_with_query():
    """search_history filters items by query against title and channel."""
    items = [
        {"video_id": "v1", "title": "Python Tutorial", "channel": "Corey", "has_summary": True, "has_cleaned": False},
        {"video_id": "v2", "title": "JavaScript Basics", "channel": "Traversy", "has_summary": False, "has_cleaned": True},
        {"video_id": "v3", "title": "Another Python Video", "channel": "Fireship", "has_summary": False, "has_cleaned": False},
    ]
    with respx.mock(assert_all_called=False) as mock:
        # The endpoint is called with ?page=1 query param.
        mock.get(f"{BASE}/api/history?page=1").mock(
            return_value=httpx.Response(200, json={"items": items, "total": 3})
        )

        result = await search_history(query="python")

    assert "Python Tutorial" in result
    assert "Another Python Video" in result
    assert "JavaScript Basics" not in result


@pytest.mark.asyncio
async def test_search_history_empty():
    """No matching items → returns 'No videos found.'"""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/history?page=1").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await search_history(query="nonexistent")

    assert result == "No videos found."


# ─── run_cleanup ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_cleanup_ollama_down():
    """Ollama offline → returns ERROR without starting cleanup."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/health").mock(
            return_value=httpx.Response(200, json={"backend": True, "ollama": False})
        )

        result = await run_cleanup("vid123")

    assert "ERROR" in result
    assert "Ollama" in result


@pytest.mark.asyncio
async def test_run_cleanup_success():
    """cleanup triggers, polls until status=done, returns 'Cleanup complete'."""
    with respx.mock(assert_all_called=False) as mock, patch("asyncio.sleep", _noop_sleep):
        mock.get(f"{BASE}/api/health").mock(
            return_value=httpx.Response(200, json={"backend": True, "ollama": True})
        )
        mock.post(f"{BASE}/api/result/vid123/cleanup").mock(
            return_value=httpx.Response(200, json={"status": "started"})
        )
        mock.get(f"{BASE}/api/result/vid123").mock(
            side_effect=_seq(
                httpx.Response(200, json={"cleanup_status": "processing", "cleaned_text": None}),
                httpx.Response(200, json={
                    "cleanup_status": "done",
                    "cleaned_text": "Cleaned transcript text goes here.",
                    "cleanup_duration_seconds": 15.3,
                }),
            )
        )

        result = await run_cleanup("vid123")

    assert "Cleanup complete" in result
    assert "vid123" in result


# ─── run_summary ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_summary_success():
    """summary triggers, polls until status=done, returns summary text."""
    with respx.mock(assert_all_called=False) as mock, patch("asyncio.sleep", _noop_sleep):
        mock.get(f"{BASE}/api/health").mock(
            return_value=httpx.Response(200, json={"backend": True, "ollama": True})
        )
        mock.post(f"{BASE}/api/result/vid123/summary").mock(
            return_value=httpx.Response(200, json={"status": "started"})
        )
        mock.get(f"{BASE}/api/result/vid123").mock(
            side_effect=_seq(
                httpx.Response(200, json={"summary_status": "processing", "summary_text": None}),
                httpx.Response(200, json={
                    "summary_status": "done",
                    "summary_text": "This video is a great introduction to the topic.",
                    "summary_duration_seconds": 25.0,
                }),
            )
        )

        result = await run_summary("vid123")

    assert "Summary complete" in result
    assert "This video is a great introduction to the topic." in result
    assert "vid123" in result
