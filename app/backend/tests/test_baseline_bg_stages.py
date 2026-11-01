"""
NS-11 baseline: pins the CURRENT behaviour of the BackgroundTasks copy of the
pipeline stages (cleanup, summary, mind map, re-extract) in routers/result.py.

Nothing here is a wish list. Where the current behaviour is a bug it is pinned
anyway and marked `# BASELINE: known bug`. LLM / yt-dlp calls are replaced by
fakes; the DB is the in-memory test DB.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio

from tests.baseline_helpers import (
    VIDEO_ID, Gate, benchmark_rows, clear_router_state, fmt_count, fmt_row, reset_benchmarks, set_fmt,
)

URL = f"/api/result/{VIDEO_ID}"


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    clear_router_state()
    await reset_benchmarks()
    await client.put("/api/settings/cleanup", json={"model": "m-clean"})
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    clear_router_state()


@pytest_asyncio.fixture
async def video_with_raw_cleanup(seeded_video):
    """seeded_video + removal of the subtitles_raw rows a re-extract adds (the base fixture's
    teardown cannot delete a video that still has raw rows)."""
    yield seeded_video
    from sqlalchemy import text
    from models.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM subtitles_raw WHERE video_id = :v"), {"v": seeded_video["db_id"]})
        await db.commit()


async def _run_blocked(client, method, url, gate, **kw):
    """Start a request in the background and wait until the fake LLM call is running."""
    task = asyncio.create_task(getattr(client, method)(url, **kw))
    await gate.wait_started()
    return task


# ---------------------------------------------------------------------------
# Cleanup  (POST/DELETE /api/result/{id}/cleanup -> _run_cleanup)
# ---------------------------------------------------------------------------

async def test_cleanup_success_writes_status_text_model_timestamps_and_benchmark_row(client, seeded_video):
    gate = Gate(result="Cleaned text.")
    gate.release.set()
    with patch("routers.result.clean_text", gate.llm()):
        r = await client.post(f"{URL}/cleanup")
    assert r.status_code == 200 and r.json() == {"status": "processing"}
    row = await fmt_row()
    assert row["cleanup_status"] == "done"
    assert row["cleaned_text"] == "Cleaned text."
    assert row["cleanup_model"] == "m-clean"
    assert row["cleanup_started_at"] and row["cleanup_finished_at"]
    bench = await benchmark_rows("cleanup")
    assert len(bench) == 1 and bench[0]["triggered_by"] == "main" and bench[0]["status"] == "done"
    kw = gate.calls[0]
    assert kw["model"] == "m-clean" and kw["ollama_url"] == "http://localhost:11434"
    assert kw["parallel_workers"] == 1


async def test_cleanup_during_run_status_processing_and_progress_visible_in_result(client, seeded_video):
    gate = Gate(progress=(2, 5))
    with patch("routers.result.clean_text", gate.llm()):
        task = await _run_blocked(client, "post", f"{URL}/cleanup", gate)
        row = await fmt_row()
        assert row["cleanup_status"] == "processing" and row["cleanup_model"] == "m-clean"
        data = (await client.get(URL)).json()
        assert data["cleanup_paragraphs_done"] == 2 and data["cleanup_paragraphs_total"] == 5
        gate.release.set()
        await task
    data = (await client.get(URL)).json()
    assert "cleanup_paragraphs_done" not in data  # progress dict cleared when the run ends


async def test_cleanup_without_model_is_rejected_400(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": None})
    r = await client.post(f"{URL}/cleanup")
    assert r.status_code == 400
    assert (await fmt_row())["cleanup_status"] is None


async def test_cleanup_without_ollama_url_is_rejected_400(client, seeded_video):
    await client.put("/api/settings/app", json={"ollama_url": None})
    r = await client.post(f"{URL}/cleanup")
    assert r.status_code == 400


async def test_cleanup_unknown_video_is_404(client):
    r = await client.post("/api/result/nope-nope/cleanup")
    assert r.status_code == 404


async def test_cleanup_cancel_resets_status_to_null_and_keeps_previous_text(client, seeded_video):
    await set_fmt(cleaned_text="OLD CLEANED", cleanup_status="done", cleanup_model="old-model")
    gate = Gate(result="NEW CLEANED")
    with patch("routers.result.clean_text", gate.llm()):
        task = await _run_blocked(client, "post", f"{URL}/cleanup", gate)
        r = await client.delete(f"{URL}/cleanup")
        assert r.status_code == 200 and r.json() == {"status": "cancelling"}
        assert (await fmt_row())["cleanup_status"] == "processing"  # nothing stops until the fake returns
        gate.release.set()
        await task
    row = await fmt_row()
    assert row["cleanup_status"] is None
    assert row["cleaned_text"] == "OLD CLEANED"
    assert await benchmark_rows("cleanup") == []  # a cancelled run writes no benchmark row


async def test_cleanup_empty_llm_result_ends_failed(client, seeded_video):
    gate = Gate(result=None)
    gate.release.set()
    with patch("routers.result.clean_text", gate.llm()):
        r = await client.post(f"{URL}/cleanup")
    assert r.status_code == 200
    row = await fmt_row()
    assert row["cleanup_status"] == "failed" and row["cleaned_text"] is None


async def test_cleanup_exception_leaves_status_processing_forever(client, seeded_video):
    # BASELINE: known bug — _run_cleanup has no try/except, a crash leaves 'processing'
    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("routers.result.clean_text", boom):
        try:
            await client.post(f"{URL}/cleanup")
        except RuntimeError:
            pass  # the background-task exception surfaces through the ASGI transport
    assert (await fmt_row())["cleanup_status"] == "processing"


async def test_cleanup_second_request_while_running_starts_a_second_concurrent_run(client, seeded_video):
    # BASELINE: known bug — no guard against a second run of the same stage
    gate = Gate()
    with patch("routers.result.clean_text", gate.llm()):
        t1 = await _run_blocked(client, "post", f"{URL}/cleanup", gate)
        t2 = asyncio.create_task(client.post(f"{URL}/cleanup"))
        await asyncio.sleep(0.2)
        assert len(gate.calls) == 2
        gate.release.set()
        r1, r2 = await asyncio.gather(t1, t2)
    assert r1.status_code == 200 and r2.status_code == 200


async def test_cleanup_cancel_when_nothing_runs_is_200_and_stale_flag_is_cleared_by_next_start(client, seeded_video):
    from routers import result as res
    r = await client.delete(f"{URL}/cleanup")
    assert r.status_code == 200 and r.json() == {"status": "cancelling"}
    assert VIDEO_ID in res._CANCEL_SET
    gate = Gate(result="Fresh.")
    gate.release.set()
    with patch("routers.result.clean_text", gate.llm()):
        await client.post(f"{URL}/cleanup")
    assert (await fmt_row())["cleanup_status"] == "done"
    assert VIDEO_ID not in res._CANCEL_SET


# ---------------------------------------------------------------------------
# Summary  (POST/DELETE /api/result/{id}/summary -> _run_summary)
# ---------------------------------------------------------------------------

def _summary_gate(result=("Sum text.", "single", 1)):
    return Gate(result=result)


async def test_summary_success_writes_everything_and_benchmark_row(client, seeded_video):
    gate = _summary_gate(("Sum text.", "map_reduce", 4))
    gate.release.set()
    with patch("routers.result.summarize_text", gate.llm()):
        r = await client.post(f"{URL}/summary")
    assert r.status_code == 200 and r.json() == {"status": "processing"}
    row = await fmt_row()
    assert row["summary_status"] == "done" and row["summary_text"] == "Sum text."
    assert row["summary_mode"] == "map_reduce" and row["summary_chunks_count"] == 4
    assert row["summary_model"] == "m-sum"
    assert row["summary_started_at"] and row["summary_finished_at"]
    bench = await benchmark_rows("summary")
    assert len(bench) == 1 and bench[0]["triggered_by"] == "main" and bench[0]["mode"] == "map_reduce"


async def test_summary_source_is_cleaned_text_when_present_else_formatted(client, seeded_video):
    gate = _summary_gate()
    gate.release.set()
    with patch("routers.result.summarize_text", gate.llm()):
        await client.post(f"{URL}/summary")
    assert gate.calls[0]["args"][0].startswith("Привет всем.")  # formatted text, no cleanup yet
    await set_fmt(cleaned_text="CLEANED SOURCE", cleanup_status="done")
    gate2 = _summary_gate()
    gate2.release.set()
    with patch("routers.result.summarize_text", gate2.llm()):
        await client.post(f"{URL}/summary")
    assert gate2.calls[0]["args"][0] == "CLEANED SOURCE"


async def test_summary_runs_without_cleanup_no_server_side_confirmation(client, seeded_video):
    gate = _summary_gate()
    gate.release.set()
    with patch("routers.result.summarize_text", gate.llm()):
        r = await client.post(f"{URL}/summary")
    assert r.status_code == 200
    assert (await fmt_row())["cleanup_status"] is None


async def test_summary_during_run_status_and_chunk_progress(client, seeded_video):
    gate = Gate(result=("S", "single", 1), progress=(1, 4))
    with patch("routers.result.summarize_text", gate.llm()):
        task = await _run_blocked(client, "post", f"{URL}/summary", gate)
        assert (await fmt_row())["summary_status"] == "processing"
        data = (await client.get(URL)).json()
        assert data["summary_chunks_done"] == 1 and data["summary_chunks_total"] == 4
        gate.release.set()
        await task


async def test_summary_without_model_400_without_ollama_400_unknown_video_404(client, seeded_video):
    await client.put("/api/settings/summarization", json={"model": None})
    assert (await client.post(f"{URL}/summary")).status_code == 400
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": None})
    assert (await client.post(f"{URL}/summary")).status_code == 400
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    assert (await client.post("/api/result/nope-nope/summary")).status_code == 404


async def test_summary_cancel_resets_status_to_null_and_keeps_previous_summary(client, seeded_video):
    await set_fmt(summary_text="OLD SUMMARY", summary_status="done", summary_model="old")
    gate = _summary_gate(("NEW", "single", 1))
    with patch("routers.result.summarize_text", gate.llm()):
        task = await _run_blocked(client, "post", f"{URL}/summary", gate)
        assert (await client.delete(f"{URL}/summary")).json() == {"status": "cancelling"}
        gate.release.set()
        await task
    row = await fmt_row()
    assert row["summary_status"] is None and row["summary_text"] == "OLD SUMMARY"
    assert await benchmark_rows("summary") == []


async def test_summary_empty_result_ends_failed(client, seeded_video):
    gate = _summary_gate(("", "single", 1))
    gate.release.set()
    with patch("routers.result.summarize_text", gate.llm()):
        await client.post(f"{URL}/summary")
    assert (await fmt_row())["summary_status"] == "failed"


async def test_summary_exception_leaves_status_processing_forever(client, seeded_video):
    # BASELINE: known bug — _run_summary has no try/except
    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("routers.result.summarize_text", boom):
        try:
            await client.post(f"{URL}/summary")
        except RuntimeError:
            pass
    assert (await fmt_row())["summary_status"] == "processing"


async def test_summary_uses_full_extract_for_long_text_with_chapters(client, seeded_video):
    from services.text_summarizer import MAP_REDUCE_THRESHOLD
    await set_fmt(formatted_text="x" * (MAP_REDUCE_THRESHOLD + 10))
    async with __import__("models.database", fromlist=["x"]).AsyncSessionLocal() as db:
        from sqlalchemy import text
        await db.execute(text("UPDATE videos SET chapters = :c WHERE video_id = :v"),
                         {"c": '[{"start_time": 0, "end_time": 5, "title": "A"}]', "v": VIDEO_ID})
        await db.commit()
    extract_gate = Gate(result=("Notes", "full_extract", 3))
    extract_gate.release.set()
    plain_gate = _summary_gate()
    plain_gate.release.set()
    with patch("routers.result.extract_notes", extract_gate.llm()), \
         patch("routers.result.summarize_text", plain_gate.llm()):
        await client.post(f"{URL}/summary")
    assert len(extract_gate.calls) == 1 and plain_gate.calls == []
    assert (await fmt_row())["summary_mode"] == "full_extract"


# ---------------------------------------------------------------------------
# Mind map  (POST/DELETE /api/result/{id}/mindmap -> _run_mindmap)
# ---------------------------------------------------------------------------

async def test_mindmap_success_status_done_and_text_saved(client, seeded_video):
    gate = Gate(result="# Root\n## A")
    gate.release.set()
    with patch("routers.result.generate_mindmap", gate.llm()):
        r = await client.post(f"{URL}/mindmap")
    assert r.status_code == 200 and r.json() == {"status": "processing"}
    row = await fmt_row()
    assert row["mindmap_status"] == "done" and row["mindmap_text"] == "# Root\n## A"
    kw = gate.calls[0]
    assert kw["model"] == "m-sum" and kw["language"] == "Russian"  # 'ru' -> name via lang_map


async def test_mindmap_returns_cached_result_unless_forced(client, seeded_video):
    await set_fmt(mindmap_text="CACHED", mindmap_status="done")
    gate = Gate(result="FRESH")
    gate.release.set()
    with patch("routers.result.generate_mindmap", gate.llm()):
        r = await client.post(f"{URL}/mindmap")
        assert r.json() == {"status": "done", "mindmap_text": "CACHED"} and gate.calls == []
        r2 = await client.post(f"{URL}/mindmap", params={"force": "true"})
    assert r2.json() == {"status": "processing"}
    assert (await fmt_row())["mindmap_text"] == "FRESH"


async def test_mindmap_unknown_video_404(client):
    assert (await client.post("/api/result/nope-nope/mindmap")).status_code == 404


async def test_mindmap_without_model_endpoint_says_processing_but_run_ends_failed(client, seeded_video):
    # BASELINE: known bug — no model/Ollama check at the endpoint (cleanup/summary have one)
    await client.put("/api/settings/summarization", json={"model": None})
    r = await client.post(f"{URL}/mindmap")
    assert r.status_code == 200 and r.json() == {"status": "processing"}
    assert (await fmt_row())["mindmap_status"] == "failed"


async def test_mindmap_empty_llm_result_ends_failed(client, seeded_video):
    gate = Gate(result=None)
    gate.release.set()
    with patch("routers.result.generate_mindmap", gate.llm()):
        await client.post(f"{URL}/mindmap")
    assert (await fmt_row())["mindmap_status"] == "failed"


async def test_mindmap_cancel_resets_status_and_keeps_previous_text(client, seeded_video):
    await set_fmt(mindmap_text="OLD MAP", mindmap_status="done")
    gate = Gate(result="NEW MAP")
    with patch("routers.result.generate_mindmap", gate.llm()):
        task = await _run_blocked(client, "post", f"{URL}/mindmap", gate, params={"force": "true"})
        assert (await fmt_row())["mindmap_status"] == "processing"
        assert (await client.delete(f"{URL}/mindmap")).json() == {"status": "cancelling"}
        gate.release.set()
        await task
    row = await fmt_row()
    assert row["mindmap_status"] is None and row["mindmap_text"] == "OLD MAP"


async def test_mindmap_exception_leaves_status_processing_forever(client, seeded_video):
    # BASELINE: known bug — _run_mindmap has no try/except
    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("routers.result.generate_mindmap", boom):
        try:
            await client.post(f"{URL}/mindmap")
        except RuntimeError:
            pass
    assert (await fmt_row())["mindmap_status"] == "processing"


# ---------------------------------------------------------------------------
# Re-extract / re-transcribe  (POST /api/result/{id}/reextract -> _run_reextract)
# ---------------------------------------------------------------------------

def _extraction(text="Fresh subtitle line.", lang="en"):
    from services.subtitle_extractor import ExtractionResult, SubtitleEntry, VideoMetadata
    meta = VideoMetadata(video_id=VIDEO_ID, title="New Title", author="New Author", duration=99,
                         channel_id=None, channel_name=None, upload_date=None, view_count=None,
                         description=None, thumbnail_url=None)
    return ExtractionResult(success=True, metadata=meta,
                            subtitles=[SubtitleEntry(timestamp="00:00:01", text=text)],
                            language=lang, source_type=None)


async def test_reextract_replaces_text_and_clears_all_derived_data(client, video_with_raw_cleanup):
    await set_fmt(cleaned_text="C", cleanup_status="done", cleanup_model="m", summary_text="S",
                  summary_status="done", summary_model="m", summary_mode="single",
                  mindmap_text="M", mindmap_status="done")
    with patch("routers.result.extract_subtitles", return_value=_extraction()):
        r = await client.post(f"{URL}/reextract", json={"language": "en"})
    assert r.status_code == 200 and r.json() == {"status": "reextracting"}
    row = await fmt_row()
    assert "Fresh subtitle line." in row["formatted_text"] and row["language"] == "en"
    for col in ("cleaned_text", "cleanup_status", "cleanup_model", "summary_text", "summary_status",
                "summary_model", "summary_mode", "mindmap_text", "mindmap_status"):
        assert row[col] is None, col
    assert await fmt_count() == 1  # replaced in place


async def test_reextract_refused_409_while_cleanup_or_summary_processing(client, seeded_video):
    await set_fmt(cleanup_status="processing")
    assert (await client.post(f"{URL}/reextract", json={})).status_code == 409
    await set_fmt(cleanup_status=None, summary_status="processing")
    assert (await client.post(f"{URL}/reextract", json={})).status_code == 409


async def test_reextract_failed_extraction_changes_nothing_and_reports_nothing(client, video_with_raw_cleanup):
    # BASELINE: known bug — failure is only a log line; the caller got 200 and the old text stays
    from services.subtitle_extractor import ExtractionResult, VideoMetadata
    failed = SimpleNamespace(success=False, error_type="x", error_message="boom",
                             available_languages=[], language=None, subtitles=[], metadata=None)
    before = (await fmt_row())["formatted_text"]
    with patch("routers.result.extract_subtitles", return_value=failed):
        r = await client.post(f"{URL}/reextract", json={})
    assert r.status_code == 200
    assert (await fmt_row())["formatted_text"] == before
    assert "reextract_in_progress" not in (await client.get(URL)).json()


async def test_reextract_second_request_while_running_is_409_and_flag_visible(client, video_with_raw_cleanup):
    release = asyncio.Event()
    started = asyncio.Event()

    def slow_extract(*a, **k):
        import time
        started.set()
        while not release.is_set():
            time.sleep(0.02)
        return _extraction()

    with patch("routers.result.extract_subtitles", slow_extract):
        t1 = asyncio.create_task(client.post(f"{URL}/reextract", json={}))
        await asyncio.wait_for(started.wait(), 5)
        data = (await client.get(URL)).json()
        assert data["reextract_in_progress"] is True
        assert (await client.post(f"{URL}/reextract", json={})).status_code == 409
        release.set()
        assert (await t1).status_code == 200
    assert "reextract_in_progress" not in (await client.get(URL)).json()


async def test_reextract_unknown_video_404(client):
    assert (await client.post("/api/result/nope-nope/reextract", json={})).status_code == 404
