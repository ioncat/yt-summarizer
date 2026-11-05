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
        # The endpoint is called with ?page=1&search=<query>.
        mock.get(f"{BASE}/api/history").mock(
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
        mock.get(f"{BASE}/api/history").mock(
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


# ─── the channel comes from the backend's `author` field ──────────────────────

@pytest.mark.asyncio
async def test_get_result_shows_the_channel_from_author():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/result/vidA").mock(return_value=httpx.Response(200, json={
            "video_id": "vidA", "title": "T", "author": "Real Channel", "summary_text": "S"}))
        result = await get_result("vidA")
    assert "Channel: Real Channel" in result


@pytest.mark.asyncio
async def test_search_history_uses_author_for_filter_and_listing():
    items = [
        {"video_id": "v1", "title": "One", "author": "Corey Schafer", "has_summary": True},
        {"video_id": "v2", "title": "Two", "author": "Other", "has_summary": False},
    ]
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/history").mock(return_value=httpx.Response(200, json={"items": items}))
        result = await search_history(query="corey")
    assert "One — Corey Schafer" in result and "Two" not in result


# ─── get_result: parts, paging, hint (NS-29) ───────────────────────────────────

LONG = "".join(f"{i:05d} " for i in range(5000))  # 30,000 chars, every 6-char block is its own number
FULL = {
    "video_id": "vidP", "title": "Parts", "author": "Chan", "duration": 600, "language": "ru",
    "summary_text": "Short summary.", "cleaned_text": "Cleaned text.", "formatted_text": LONG,
    "mindmap_text": "# Root\n- leaf",
}


async def _get(data, **kw):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/result/vidP").mock(return_value=httpx.Response(200, json=data))
        return await get_result("vidP", **kw)


@pytest.mark.asyncio
async def test_default_answer_is_unchanged_except_for_the_parts_line():
    result = await _get(FULL)
    assert result == (
        "# Parts\n"
        "Channel: Chan · Duration: 10 min · Language: ru\n"
        "Parts (chars): summary 14 · cleaned 13 · transcript 30k · mindmap 13\n"
        "\n"
        "## Summary\n"
        "Short summary.\n"
        "\n"
        "video_id: vidP"
    )
    # no summary and no include_text: the old hint text is still there
    no_summary = await _get({**FULL, "summary_text": None})
    assert "(No summary yet. Use run_summary(video_id)" in no_summary and "summary none" in no_summary


@pytest.mark.asyncio
async def test_include_text_still_works_the_old_way():
    result = await _get({**FULL, "summary_text": None}, include_text=True)
    assert "[Transcript truncated — showing first 20000 of 30000 chars]" not in result  # cleaned text is preferred
    assert "Cleaned text." in result
    long_only = await _get({**FULL, "summary_text": None, "cleaned_text": None}, include_text=True)
    assert "[Transcript truncated — showing first 20000 of 30000 chars]" in long_only


@pytest.mark.asyncio
@pytest.mark.parametrize("part,text,header", [
    ("summary", "Short summary.", "## Summary (chars 0–14 of 14) · end"),
    ("cleaned", "Cleaned text.", "## Cleaned (chars 0–13 of 13) · end"),
    ("mindmap", "# Root\n- leaf", "## Mindmap (chars 0–13 of 13) · end"),
])
async def test_each_small_part_is_returned_whole(part, text, header):
    result = await _get(FULL, parts=[part])
    assert header in result and text in result
    assert "Short summary." not in result or part == "summary"  # only what was asked for


@pytest.mark.asyncio
async def test_transcript_defaults_to_20000_chars_and_says_where_to_continue():
    result = await _get(FULL, parts=["transcript"])
    assert "## Transcript (chars 0–20000 of 30000) · next: offset=20000" in result
    assert LONG[:20000] in result and LONG[20000:20010] not in result


@pytest.mark.asyncio
async def test_a_long_transcript_can_be_read_in_pieces_to_the_end_marker():
    got, offset, calls = "", 0, 0
    while True:
        result = await _get(FULL, parts=["transcript"], offset=offset, limit=7000)
        calls += 1
        header = next(l for l in result.splitlines() if l.startswith("## Transcript"))
        body = result.split(header + "\n", 1)[1].rsplit("\n\nvideo_id:", 1)[0]
        got += body
        if header.endswith("· end"):
            break
        assert f"next: offset={offset + 7000}" in header
        offset += 7000
    assert calls == 5 and got == LONG  # 7000 x4 + 2000: the pieces add up to the whole text
    assert "chars 28000–30000 of 30000" in header


@pytest.mark.asyncio
async def test_offset_past_the_end_and_bad_numbers():
    past = await _get(FULL, parts=["transcript"], offset=30000)
    assert "past the end" in past and "total 30000" in past
    assert (await _get(FULL, parts=["transcript"], offset=-1)).startswith("ERROR")
    assert (await _get(FULL, parts=["transcript"], limit=0)).startswith("ERROR")


@pytest.mark.asyncio
async def test_unknown_part_is_an_error_that_lists_the_allowed_ones_and_makes_no_request():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/api/result/vidP").mock(return_value=httpx.Response(200, json=FULL))
        result = await get_result("vidP", parts=["summary", "bogus"])
    assert result == "ERROR: unknown part 'bogus'. Allowed: summary, transcript, cleaned, mindmap, status"
    assert not route.called


@pytest.mark.asyncio
async def test_parts_come_in_the_order_asked_each_once_and_a_missing_part_is_said_so():
    result = await _get({**FULL, "mindmap_text": None}, parts=["cleaned", "mindmap", "summary", "cleaned"])
    assert result.index("## Cleaned") < result.index("## Mindmap") < result.index("## Summary")
    assert result.count("## Cleaned") == 1
    assert "## Mindmap\n(not available for this video)" in result


@pytest.mark.asyncio
async def test_limit_applies_to_summary_too_and_no_limit_means_all_of_it():
    big = {**FULL, "summary_text": "S" * 25_000}
    assert "chars 0–25000 of 25000) · end" in await _get(big, parts=["summary"])  # not cut at 20000
    cut = await _get(big, parts=["summary"], limit=100)
    assert "chars 0–100 of 25000) · next: offset=100" in cut


@pytest.mark.asyncio
async def test_parts_line_shows_what_exists():
    result = await _get({**FULL, "cleaned_text": None, "mindmap_text": None})
    assert "Parts (chars): summary 14 · cleaned none · transcript 30k · mindmap none" in result


# ─── get_result: the status part (NS-29) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_status_part_shows_stage_states_models_and_error_reasons():
    data = {
        **FULL,
        "cleanup_status": "done", "cleanup_model": "gemma4:e4b", "cleanup_duration_seconds": 42.4,
        "summary_status": "failed", "summary_model": "gemma4:e4b", "summary_mode": "map_reduce",
        "summary_chunks_count": 5,
        "summary_error": "model returned no answer (thinking used the whole context) — raise llm_max_num_ctx",
        "mindmap_status": "failed", "mindmap_error": "model returned nothing",
    }
    result = await _get(data, parts=["status"])
    assert "## Status" in result
    assert "- cleanup: done · model gemma4:e4b · 42s" in result
    assert "- summary: failed · model gemma4:e4b · map_reduce (5 chunks) · error: model returned no answer" in result
    assert "- mindmap: failed · error: model returned nothing" in result
    assert "## Summary" not in result  # only status was asked for


@pytest.mark.asyncio
async def test_status_part_for_a_video_where_nothing_ran_and_mixed_with_text():
    result = await _get({"video_id": "vidP", "title": "T", "formatted_text": "abc"}, parts=["status", "transcript"])
    assert "- cleanup: not run" in result and "- summary: not run" in result and "- mindmap: not run" in result
    assert result.index("## Status") < result.index("## Transcript (chars 0–3 of 3) · end")


@pytest.mark.asyncio
async def test_offset_and_limit_do_not_touch_the_status_part():
    result = await _get({**FULL, "cleanup_status": "done"}, parts=["status"], offset=50, limit=5)
    assert "- cleanup: done" in result


# ─── search_history: the whole history, and inside the texts (NS-29) ───────────

def _page(start, n):
    return [{"video_id": f"v{i:03d}", "title": f"Video {i}", "author": "Chan", "has_summary": False}
            for i in range(start, start + n)]


@pytest.mark.asyncio
async def test_search_history_reads_every_page_not_just_the_first():
    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"items": {1: _page(0, 20), 2: _page(20, 20), 3: _page(40, 5)}[page]})

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/api/history").mock(side_effect=handler)
        result = await search_history(limit=100)
    assert "Found 45 video(s):" in result and "v044" in result
    assert route.call_count == 3  # a short third page ends it


@pytest.mark.asyncio
async def test_search_history_stops_paging_once_it_has_enough():
    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"items": _page((page - 1) * 20, 20)})

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/api/history").mock(side_effect=handler)
        result = await search_history(limit=25)
    assert "Found 25 video(s):" in result and route.call_count == 2


@pytest.mark.asyncio
async def test_search_history_passes_the_query_to_the_server_and_still_filters():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"items": [
            {"video_id": "a", "title": "Привет мир", "author": "X"},
            {"video_id": "b", "title": "Совсем другое", "author": "Y"}]})

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/history").mock(side_effect=handler)
        result = await search_history(query="ПРИВЕТ")
    assert seen[0]["search"] == "ПРИВЕТ" and seen[0]["page"] == "1"
    assert "Привет мир" in result and "Совсем другое" not in result


TEXT_HITS = {"query": "зиррокс", "searched": 7, "total_videos": 120, "videos": [{
    "video_id": "vidT", "title": "Лекция", "author": "Канал",
    "counts": {"transcript": 14, "summary": 1},
    "matches": [
        {"part": "summary", "position": 120, "snippet": "…про Зиррокс в начале…"},
        {"part": "transcript", "position": 41230, "snippet": "…и тут Зиррокс снова…"},
    ]}]}


@pytest.mark.asyncio
async def test_search_in_text_lists_parts_counts_positions_and_snippets():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=TEXT_HITS)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/history/text-search").mock(side_effect=handler)
        result = await search_history(query="зиррокс", limit=5, in_text=True)
    assert seen == [{"q": "зиррокс", "limit": "5"}]
    assert "Found 1 video(s) with 'зиррокс' in their text. Looked through 7 of 120 video(s)." in result
    assert "- Лекция — Канал  (video_id: vidT)" in result
    assert "  - transcript ×14, first at char 41230: …и тут Зиррокс снова…" in result
    assert "  - summary ×1, first at char 120: …про Зиррокс в начале…" in result
    assert "get_result(video_id, parts=[<part>], offset=" in result


@pytest.mark.asyncio
async def test_search_in_text_needs_three_characters_and_makes_no_request():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/api/history/text-search").mock(return_value=httpx.Response(200, json=TEXT_HITS))
        for q in ("", "  ab "):
            assert (await search_history(query=q, in_text=True)).startswith("ERROR: in_text needs")
    assert not route.called


@pytest.mark.asyncio
async def test_search_in_text_no_match_backend_error_and_no_backend():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/history/text-search").mock(return_value=httpx.Response(
            200, json={"videos": [], "searched": 120, "total_videos": 120}))
        assert await search_history(query="nothing", in_text=True) == (
            "No videos contain 'nothing'. Looked through 120 of 120 video(s).")
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/history/text-search").mock(return_value=httpx.Response(500, text="boom"))
        assert (await search_history(query="nothing", in_text=True)).startswith("ERROR 500")
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/history/text-search").mock(side_effect=httpx.ConnectError("down"))
        assert "Cannot connect" in await search_history(query="nothing", in_text=True)


@pytest.mark.asyncio
async def test_a_very_long_query_is_a_clear_error_line_without_a_request():
    with respx.mock(assert_all_called=False) as mock:
        hist = mock.get(f"{BASE}/api/history").mock(return_value=httpx.Response(200, json={"items": []}))
        text = mock.get(f"{BASE}/api/history/text-search").mock(return_value=httpx.Response(200, json={"videos": []}))
        for in_text in (False, True):
            out = await search_history(query="x" * 5000, in_text=in_text)
            assert out == "ERROR: query is too long (5000 chars, at most 200)"
        ok = await search_history(query="я" * 200, in_text=True)
    assert not hist.called and text.called and not ok.startswith("ERROR: query")


# ─── run_summary waits behind the queue (NS-11 stage 3 note) ────────────────────

@pytest.mark.asyncio
async def test_run_summary_tool_text_says_it_may_wait_behind_the_queue_for_300_s():
    import mcp_server
    tools = await mcp_server.mcp.list_tools()
    text = next(t for t in tools if t.name == "run_summary").description
    assert "queue" in text and "300 s" in text and "NOT lost" in text
    assert 'get_result(video_id, parts=["status"])' in text


@pytest.mark.asyncio
async def test_run_summary_timeout_says_the_job_is_not_lost_and_how_to_check_it():
    with respx.mock(assert_all_called=False) as mock, patch("asyncio.sleep", _noop_sleep):
        mock.get(f"{BASE}/api/health").mock(return_value=httpx.Response(200, json={"backend": True, "ollama": True}))
        mock.post(f"{BASE}/api/result/vidQ/summary").mock(return_value=httpx.Response(200, json={"status": "processing"}))
        mock.get(f"{BASE}/api/result/vidQ").mock(
            return_value=httpx.Response(200, json={"summary_status": "processing", "summary_text": None}))
        result = await run_summary("vidQ")
    assert result.startswith("ERROR: Summarization is still not finished after 300s")
    assert "not lost" in result
    assert "get_result(video_id='vidQ', parts=['status'])" in result and "parts=['summary']" in result


# ─── run_cleanup waits behind the queue (NS-11 stage 4a note) ───────────────────

@pytest.mark.asyncio
async def test_run_cleanup_tool_text_says_it_may_wait_behind_the_queue_for_300_s():
    import mcp_server
    tools = await mcp_server.mcp.list_tools()
    text = next(t for t in tools if t.name == "run_cleanup").description
    assert "queue" in text and "300 s" in text and "NOT lost" in text
    assert 'get_result(video_id, parts=["status"])' in text and 'parts=["cleaned"]' in text


@pytest.mark.asyncio
async def test_run_cleanup_timeout_says_the_job_is_not_lost_and_how_to_check_it():
    with respx.mock(assert_all_called=False) as mock, patch("asyncio.sleep", _noop_sleep):
        mock.get(f"{BASE}/api/health").mock(return_value=httpx.Response(200, json={"backend": True, "ollama": True}))
        mock.post(f"{BASE}/api/result/vidC/cleanup").mock(return_value=httpx.Response(200, json={"status": "processing"}))
        mock.get(f"{BASE}/api/result/vidC").mock(
            return_value=httpx.Response(200, json={"cleanup_status": "processing", "cleaned_text": None}))
        result = await run_cleanup("vidC")
    assert result.startswith("ERROR: Cleanup is still not finished after 300s")
    assert "not lost" in result
    assert "get_result(video_id='vidC', parts=['status'])" in result and "parts=['cleaned']" in result
