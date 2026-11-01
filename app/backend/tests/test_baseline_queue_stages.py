"""
NS-11 baseline: pins the CURRENT behaviour of the queue copy of the pipeline
(services/queue_service.py stage runners, the worker loop, /api/queue/*) and of
the BackgroundTasks extract / transcribe entry points (/api/process, /api/process/file).

Where behaviour is clearly a bug it is pinned anyway: `# BASELINE: known bug`.
LLM, yt-dlp and STT calls are faked; the DB is the in-memory test DB.
"""
import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import queue_service as q
from tests.baseline_helpers import (
    VIDEO_ID, Gate, benchmark_rows, clear_router_state, fmt_count, fmt_row,
    reset_benchmarks, reset_queue, set_fmt,
)

YT_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    clear_router_state()
    await reset_benchmarks()
    await reset_queue()
    await client.put("/api/settings/cleanup", json={"model": "m-clean"})
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    clear_router_state()
    await reset_queue()


@pytest_asyncio.fixture
async def full_video_cleanup(seeded_video):
    """seeded_video + removal of every extra row a (re-)extract adds."""
    yield seeded_video
    async with AsyncSessionLocal() as db:
        v = seeded_video["db_id"]
        await db.execute(text("DELETE FROM subtitles_raw WHERE video_id = :v"), {"v": v})
        await db.execute(text("DELETE FROM subtitles_formatted WHERE video_id = :v AND id != :f"),
                         {"v": v, "f": seeded_video["fmt_id"]})
        await db.execute(text("DELETE FROM processing_tasks WHERE video_id = :v"), {"v": v})
        await db.commit()


# ---------------------------------------------------------------------------
# Queue stage runners called directly
# ---------------------------------------------------------------------------

async def test_queue_cleanup_success_writes_same_fields_as_background_copy(seeded_video):
    gate = Gate(result="Cleaned text.", progress=(1, 3))
    with patch("services.text_cleaner.clean_text", gate.llm()):
        task = asyncio.create_task(q._run_cleanup_stage(VIDEO_ID, 7))
        await gate.wait_started()
        assert (await fmt_row())["cleanup_status"] == "processing"
        assert q._QUEUE_PROGRESS[7] == "cleanup: paragraph 1/3"
        gate.release.set()
        await task
    row = await fmt_row()
    assert row["cleanup_status"] == "done" and row["cleaned_text"] == "Cleaned text."
    assert row["cleanup_model"] == "m-clean"
    assert row["cleanup_started_at"] and row["cleanup_finished_at"]
    bench = await benchmark_rows("cleanup")
    assert len(bench) == 1 and bench[0]["triggered_by"] == "main"


async def test_queue_cleanup_cannot_be_cancelled_flag_is_ignored(seeded_video):
    # BASELINE: known gap — is_cancelled is a constant False; the Stop button's flag is never read
    from routers import result as res
    res._CANCEL_SET.add(VIDEO_ID)
    gate = Gate(result="Cleaned text.")
    gate.release.set()
    with patch("services.text_cleaner.clean_text", gate.llm()):
        await q._run_cleanup_stage(VIDEO_ID, 1)
    assert gate.calls[0]["is_cancelled"]() is False
    assert (await fmt_row())["cleanup_status"] == "done"


async def test_queue_cleanup_without_model_or_text_is_silently_skipped(seeded_video):
    # BASELINE: known gap — returns normally, so the queue item would end 'done' with nothing done
    await client_put_cleanup_model(None)
    await q._run_cleanup_stage(VIDEO_ID, 1)
    assert (await fmt_row())["cleanup_status"] is None
    await client_put_cleanup_model("m-clean")
    await set_fmt(formatted_text=None)
    await q._run_cleanup_stage(VIDEO_ID, 1)
    assert (await fmt_row())["cleanup_status"] is None
    await q._run_cleanup_stage("no-such-video", 1)  # unknown video: also silent


async def client_put_cleanup_model(model):
    from httpx import AsyncClient, ASGITransport
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.put("/api/settings/cleanup", json={"model": model})


async def test_queue_cleanup_empty_result_marks_failed_without_raising(seeded_video):
    gate = Gate(result=None)
    gate.release.set()
    with patch("services.text_cleaner.clean_text", gate.llm()):
        await q._run_cleanup_stage(VIDEO_ID, 1)  # no exception -> the queue item would be 'done'
    assert (await fmt_row())["cleanup_status"] == "failed"


async def test_queue_cleanup_exception_marks_failed_and_reraises(seeded_video):
    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("services.text_cleaner.clean_text", boom):
        with pytest.raises(RuntimeError):
            await q._run_cleanup_stage(VIDEO_ID, 1)
    assert (await fmt_row())["cleanup_status"] == "failed"  # differs from the BackgroundTasks copy


async def test_queue_summary_success_progress_and_fields(seeded_video):
    gate = Gate(result=("Sum.", "map_reduce", 3), progress=(2, 6))
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        task = asyncio.create_task(q._run_summary_stage(VIDEO_ID, 8))
        await gate.wait_started()
        assert (await fmt_row())["summary_status"] == "processing"
        assert q._QUEUE_PROGRESS[8] == "summary: chunk 2/6"
        gate.release.set()
        await task
    row = await fmt_row()
    assert row["summary_status"] == "done" and row["summary_text"] == "Sum."
    assert row["summary_mode"] == "map_reduce" and row["summary_chunks_count"] == 3
    assert row["summary_model"] == "m-sum" and row["summary_started_at"] and row["summary_finished_at"]
    assert len(await benchmark_rows("summary")) == 1
    assert gate.calls[0]["is_cancelled"]() is False  # BASELINE: no cancel in the queue copy


async def test_queue_summary_without_model_is_silently_skipped(seeded_video):
    # BASELINE: known gap — same silent skip as cleanup
    from httpx import AsyncClient, ASGITransport
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.put("/api/settings/summarization", json={"model": None})
    await q._run_summary_stage(VIDEO_ID, 1)
    assert (await fmt_row())["summary_status"] is None


async def test_queue_summary_exception_marks_failed_and_reraises(seeded_video):
    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("services.text_summarizer.summarize_text", boom):
        with pytest.raises(RuntimeError):
            await q._run_summary_stage(VIDEO_ID, 1)
    assert (await fmt_row())["summary_status"] == "failed"


async def test_queue_mindmap_success_and_progress(seeded_video):
    gate = Gate(result="# Root")
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        task = asyncio.create_task(q._run_mindmap_stage(VIDEO_ID, 9))
        await gate.wait_started()
        assert (await fmt_row())["mindmap_status"] == "processing"
        assert q._QUEUE_PROGRESS[9] == "mindmap: generating…"
        gate.release.set()
        await task
    row = await fmt_row()
    assert row["mindmap_status"] == "done" and row["mindmap_text"] == "# Root"
    assert gate.calls[0]["language"] == "Russian" and gate.calls[0]["is_cancelled"]() is False


async def test_queue_mindmap_without_model_is_silently_skipped_unlike_background_copy(seeded_video):
    # BASELINE: background copy ends 'failed' here; the queue copy leaves the status untouched
    from httpx import AsyncClient, ASGITransport
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.put("/api/settings/summarization", json={"model": None})
    await q._run_mindmap_stage(VIDEO_ID, 1)
    assert (await fmt_row())["mindmap_status"] is None


async def test_queue_mindmap_empty_result_failed_and_exception_failed_and_reraised(seeded_video):
    gate = Gate(result=None)
    gate.release.set()
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        await q._run_mindmap_stage(VIDEO_ID, 1)
    assert (await fmt_row())["mindmap_status"] == "failed"

    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("services.text_mindmapper.generate_mindmap", boom):
        with pytest.raises(RuntimeError):
            await q._run_mindmap_stage(VIDEO_ID, 1)
    assert (await fmt_row())["mindmap_status"] == "failed"


# ---------------------------------------------------------------------------
# Queue extract / transcribe stages
# ---------------------------------------------------------------------------

def _extraction(video_id=VIDEO_ID, text_="Fresh line.", lang="en"):
    from services.subtitle_extractor import ExtractionResult, SubtitleEntry, VideoMetadata
    meta = VideoMetadata(video_id=video_id, title="Queue Title", author="A", duration=60, channel_id=None,
                         channel_name=None, upload_date=None, view_count=None, description=None,
                         thumbnail_url=None)
    return ExtractionResult(success=True, metadata=meta,
                            subtitles=[SubtitleEntry(timestamp="00:00:01", text=text_)],
                            language=lang, source_type=None)


async def test_queue_extract_of_new_video_creates_video_and_returns_ids():
    vid = "queueNew001"
    with patch("services.subtitle_extractor.extract_subtitles", return_value=_extraction(vid)):
        out = await q._run_extract(f"https://www.youtube.com/watch?v={vid}", language="auto")
    assert out == {"video_id": vid, "db_video_id": None}  # BASELINE: db_video_id is always None
    row = await fmt_row(vid)
    assert row and "Fresh line." in row["formatted_text"] and row["language"] == "en"
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM subtitles_raw WHERE video_id IN (SELECT id FROM videos WHERE video_id=:v)"), {"v": vid})
        await db.execute(text("DELETE FROM subtitles_formatted WHERE video_id IN (SELECT id FROM videos WHERE video_id=:v)"), {"v": vid})
        await db.execute(text("DELETE FROM processing_tasks WHERE video_id IN (SELECT id FROM videos WHERE video_id=:v)"), {"v": vid})
        await db.execute(text("DELETE FROM videos WHERE video_id=:v"), {"v": vid})
        await db.commit()


async def test_queue_extract_on_existing_video_adds_a_second_formatted_row(client, full_video_cleanup):
    # BASELINE: known bug — a forced re-run (History "re-run") does not replace the text like the
    # BackgroundTasks re-extract does; it adds a second subtitles_formatted row and orphans the
    # derived data (cleanup/summary) of the first.
    await set_fmt(cleaned_text="OLD CLEAN", cleanup_status="done")
    with patch("services.subtitle_extractor.extract_subtitles", return_value=_extraction(text_="Second take.")):
        await q._run_extract(YT_URL, language="auto")
    assert await fmt_count() == 2
    newest = await fmt_row()
    assert "Second take." in newest["formatted_text"] and newest["cleaned_text"] is None


async def test_queue_extract_failure_raises_with_message_and_marks_task_failed():
    failed = SimpleNamespace(success=False, error_message="no subs", available_languages=["en"],
                             error_type="x", subtitles=[], metadata=None, language=None)
    with patch("services.subtitle_extractor.extract_subtitles", return_value=failed):
        with pytest.raises(RuntimeError, match="no subs"):
            await q._run_extract("https://www.youtube.com/watch?v=queueFail01", language="auto")
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("SELECT status, error_message FROM processing_tasks pt JOIN videos v "
                                      "ON pt.video_id = v.id WHERE v.video_id = 'queueFail01'"))).all()
        assert rows[0][0] == "failed"
        assert "available_languages" not in (rows[0][1] or "")  # BASELINE: language hints are not kept
        await db.execute(text("DELETE FROM processing_tasks WHERE video_id IN (SELECT id FROM videos WHERE video_id='queueFail01')"))
        await db.execute(text("DELETE FROM videos WHERE video_id='queueFail01'"))
        await db.commit()


async def test_queue_transcribe_stores_no_model_or_device_unlike_file_upload_path():
    # BASELINE: known gap — transcription_model/device are not passed to complete_task here
    from services.subtitle_extractor import AudioExtractionResult
    from services.transcriber import TranscriptionResult
    vid = "queueStt001"
    meta = _extraction(vid).metadata
    audio = AudioExtractionResult(success=True, audio_path="x.m4a", metadata=meta)
    stt = TranscriptionResult(segments=[{"start": 0.0, "end": 1.0, "text": "hello"}],
                              detected_language="en", success=True, device_used="cuda")
    with patch("services.subtitle_extractor.extract_audio", return_value=audio), \
         patch("services.transcriber.transcribe", return_value=stt):
        out = await q._run_transcribe(f"https://www.youtube.com/watch?v={vid}", language="auto", item_id=3)
    assert out == {"video_id": vid, "db_video_id": None}
    row = await fmt_row(vid)
    assert row["subtitle_source"] == "transcript"
    assert row["transcription_model"] is None and row["transcription_device"] is None
    assert row["transcription_started_at"] and row["transcription_finished_at"]
    async with AsyncSessionLocal() as db:
        for t in ("subtitles_raw", "subtitles_formatted", "processing_tasks"):
            await db.execute(text(f"DELETE FROM {t} WHERE video_id IN (SELECT id FROM videos WHERE video_id=:v)"), {"v": vid})
        await db.execute(text("DELETE FROM videos WHERE video_id=:v"), {"v": vid})
        await db.commit()


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

async def _run_worker(item_ids: list[int], timeout: float = 15.0) -> None:
    task = asyncio.create_task(q.queue_worker())
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(text("SELECT status FROM processing_queue WHERE id IN (%s)" %
                                              ",".join(str(i) for i in item_ids)))).all()
            if rows and all(r[0] in ("done", "failed") for r in rows):
                break
            await asyncio.sleep(0.05)
    finally:
        q._WORKER_STOP = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        q._WORKER_STOP = False


async def _add(stages, url=YT_URL, language=None) -> int:
    async with AsyncSessionLocal() as db:
        return (await q.add_items(db, [url], stages, language=language))[0]


async def _item(item_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        return next(i for i in await q.get_queue(db) if i["id"] == item_id)


async def test_worker_runs_stages_in_order_and_marks_item_done(seeded_video):
    calls: list[str] = []

    async def fake_extract(url, language="auto"):
        calls.append(f"extract:{language}")
        return {"video_id": VIDEO_ID, "db_video_id": None}

    async def stage(name):
        async def run(vid, item_id):
            calls.append(name)
            q._QUEUE_PROGRESS[item_id] = name
        return run

    item = await _add(["extract", "cleanup", "summary", "mindmap"], language="ru")
    with patch.object(q, "_run_extract", fake_extract), \
         patch.object(q, "_run_cleanup_stage", await stage("cleanup")), \
         patch.object(q, "_run_summary_stage", await stage("summary")), \
         patch.object(q, "_run_mindmap_stage", await stage("mindmap")):
        await _run_worker([item])
    assert calls == ["extract:ru", "cleanup", "summary", "mindmap"]
    row = await _item(item)
    assert row["status"] == "done" and row["video_id"] == VIDEO_ID
    assert row["started_at"] and row["finished_at"] and row["error_message"] is None
    assert row["progress"] is None  # progress dict cleared on done


async def test_worker_stages_only_item_skips_extract(seeded_video):
    calls: list[str] = []

    async def fake_cleanup(vid, item_id):
        calls.append(vid)

    async def no_extract(*a, **k):
        raise AssertionError("extract must not run for a stages-only item")

    item = await _add(["cleanup"])
    with patch.object(q, "_run_extract", no_extract), patch.object(q, "_run_cleanup_stage", fake_cleanup):
        await _run_worker([item])
    assert calls == [VIDEO_ID] and (await _item(item))["status"] == "done"


async def test_worker_failing_stage_marks_item_failed_and_continues_with_next_item(seeded_video):
    calls: list[str] = []

    async def failing_cleanup(vid, item_id):
        raise RuntimeError("stage broke")

    async def ok_summary(vid, item_id):
        calls.append("summary")

    first = await _add(["cleanup", "summary"])
    second = await _add(["summary"], url="https://www.youtube.com/watch?v=otherVid0001")
    with patch.object(q, "_run_cleanup_stage", failing_cleanup), patch.object(q, "_run_summary_stage", ok_summary):
        await _run_worker([first, second])
    f = await _item(first)
    assert f["status"] == "failed" and "stage broke" in f["error_message"]
    assert (await _item(second))["status"] == "done"
    assert calls == ["summary"]  # later stages of the failed item did not run


async def test_worker_processes_one_item_at_a_time_in_sort_order(seeded_video):
    order: list[str] = []
    running = {"n": 0, "max": 0}

    async def slow_summary(vid, item_id):
        running["n"] += 1
        running["max"] = max(running["max"], running["n"])
        order.append(str(item_id))
        await asyncio.sleep(0.2)
        running["n"] -= 1

    a = await _add(["summary"])
    b = await _add(["summary"], url="https://www.youtube.com/watch?v=otherVid0002")
    with patch.object(q, "_run_summary_stage", slow_summary):
        await _run_worker([a, b])
    assert order == [str(a), str(b)] and running["max"] == 1


async def test_worker_resets_items_stuck_in_processing_to_pending_on_start():
    item = await _add(["summary"])
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE processing_queue SET status='processing' WHERE id=:i"), {"i": item})
        await db.commit()
    await q._reset_stuck_items()
    assert (await _item(item))["status"] == "pending"


# ---------------------------------------------------------------------------
# Queue API: add / dedup / local files / state changes
# ---------------------------------------------------------------------------

async def test_bulk_add_skips_already_processed_video_unless_forced(client, seeded_video):
    r = await client.post("/api/queue/bulk", json={"urls": [YT_URL], "pipeline_stages": ["summary"]})
    assert r.status_code == 200
    assert r.json()["added"] == 0 and r.json()["duplicates"] == [YT_URL]
    r2 = await client.post("/api/queue/bulk", json={"urls": [YT_URL], "pipeline_stages": ["summary"], "force": True})
    assert r2.json()["added"] == 1 and r2.json()["duplicates"] == []


async def test_bulk_add_pending_duplicate_and_same_url_twice_in_one_batch(client):
    url = "https://www.youtube.com/watch?v=dupCheck001"
    r = await client.post("/api/queue/bulk", json={"urls": [url, url]})
    assert r.json()["added"] == 1 and r.json()["invalid"] == [url]  # intra-batch duplicate counted invalid
    r2 = await client.post("/api/queue/bulk", json={"urls": [url]})
    assert r2.json()["added"] == 0 and r2.json()["duplicates"] == [url]  # already pending


async def test_bulk_add_rejects_local_file_urls_so_local_items_cannot_use_the_queue(client, seeded_video):
    # BASELINE: known gap — local:// results (file-*) can only be processed by the BackgroundTasks copy
    r = await client.post("/api/queue/bulk", json={"urls": ["local://talk.m4a"], "pipeline_stages": ["cleanup"], "force": True})
    assert r.status_code == 400
    assert r.json()["detail"]["message"] == "No valid YouTube URLs"


async def test_bulk_add_defaults_stage_language_and_extracts_url_from_line(client):
    r = await client.post("/api/queue/bulk", json={
        "urls": ["https://www.youtube.com/watch?v=lineParse01 | My title,"], "language": "ru"})
    assert r.json()["added"] == 1
    item = (await client.get("/api/queue")).json()["items"][0]
    assert item["url"] == "https://www.youtube.com/watch?v=lineParse01"
    assert item["pipeline_stages"] == ["extract"] and item["language"] == "ru" and item["status"] == "pending"


async def test_queue_item_state_rules_delete_retry_clear(client):
    await client.post("/api/queue/bulk", json={"urls": ["https://www.youtube.com/watch?v=stateRule01",
                                                          "https://www.youtube.com/watch?v=stateRule02",
                                                          "https://www.youtube.com/watch?v=stateRule03"]})
    items = (await client.get("/api/queue")).json()["items"]
    a, b, c = (i["id"] for i in items)
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE processing_queue SET status='processing' WHERE id=:i"), {"i": a})
        await db.execute(text("UPDATE processing_queue SET status='failed', error_message='x' WHERE id=:i"), {"i": b})
        await db.commit()
    assert (await client.delete(f"/api/queue/{a}")).status_code == 409      # cannot delete a running item
    assert (await client.post(f"/api/queue/{c}/retry")).status_code == 409   # only failed items retry
    assert (await client.post("/api/queue/9999/retry")).status_code == 404
    assert (await client.post(f"/api/queue/{b}/retry")).json() == {"retried": b}
    assert (await _item(b))["status"] == "pending" and (await _item(b))["error_message"] is None
    assert (await client.delete("/api/queue/all")).json() == {"cleared": 2}  # pending only
    assert (await _item(a))["status"] == "processing"
    counts = (await client.get("/api/queue/counts")).json()
    assert counts["processing"] == 1 and counts["active"] == 1


# ---------------------------------------------------------------------------
# BackgroundTasks extract and file transcription (/api/process, /api/process/file)
# ---------------------------------------------------------------------------

async def test_process_existing_video_is_409_with_video_id(client, seeded_video):
    r = await client.post("/api/process", json={"url": YT_URL})
    assert r.status_code == 409
    assert r.json()["detail"] == {"message": "Video already processed", "video_id": VIDEO_ID}


async def test_process_default_language_is_ru_while_queue_default_is_auto(client):
    seen = {}

    def fake(url, language, cookies, ytdlp):
        seen["language"] = language
        return _extraction("bgLang00001")

    with patch("routers.process.extract_subtitles", fake):
        r = await client.post("/api/process", json={"url": "https://www.youtube.com/watch?v=bgLang00001"})
    assert r.status_code == 200 and seen["language"] == "ru"
    await client.delete("/api/result/bgLang00001")


async def test_process_failed_extraction_exposes_message_and_available_languages(client):
    failed = SimpleNamespace(success=False, error_message="No subtitles in ru", available_languages=["en", "de"],
                             error_type="x", subtitles=[], metadata=None, language=None)
    with patch("routers.process.extract_subtitles", return_value=failed):
        r = await client.post("/api/process", json={"url": "https://www.youtube.com/watch?v=bgFail00001"})
    st = (await client.get(f"/api/status/{r.json()['task_id']}")).json()
    assert st["status"] == "failed" and st["error_message"] == "No subtitles in ru"
    assert st["available_languages"] == ["en", "de"]  # the queue copy drops these


async def test_process_invalid_url_400_and_unknown_task_404(client):
    assert (await client.post("/api/process", json={"url": "https://example.com/x"})).status_code == 400
    assert (await client.get("/api/status/does-not-exist")).status_code == 404


async def test_process_file_rejects_unsupported_extension(client):
    r = await client.post("/api/process/file", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "Unsupported file type" in r.json()["detail"]


async def test_process_file_transcribes_and_stores_model_device_and_deletes_upload(client, tmp_path, monkeypatch):
    import routers.process as proc
    fake_py = tmp_path / "app" / "backend" / "routers" / "process.py"
    fake_py.parent.mkdir(parents=True)
    monkeypatch.setattr(proc, "__file__", str(fake_py))  # uploads dir -> tmp_path/app/data/uploads
    await client.put("/api/settings/app", json={"stt_model": "base", "stt_device": "cpu",
                                                "upload_auto_delete": "true", "upload_auto_delete_mode": "immediate"})
    from services.transcriber import TranscriptionResult
    release = threading.Event()
    started = threading.Event()

    def fake_transcribe(path, language, model, device, cache_path, on_progress):
        started.set()
        on_progress(2, 5.0, 10.0)
        release.wait(5)
        return TranscriptionResult(segments=[{"start": 0.0, "end": 4.0, "text": "Hello there."}],
                                   detected_language="en", success=True, device_used="cpu")

    with patch("services.transcriber.transcribe", fake_transcribe):
        post = asyncio.create_task(client.post(
            "/api/process/file", files={"file": ("talk.m4a", b"fakeaudio", "audio/mp4")}, data={"language": "auto"}))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        # the BackgroundTasks run inside the request, so the POST only returns when STT is done
        release.set()
        r = await post
    assert r.status_code == 200
    body = r.json()
    assert body["video_id"].startswith("file-")
    st = (await client.get(f"/api/status/{body['task_id']}")).json()
    assert st["status"] == "completed" and st["progress_text"] is None
    row = await fmt_row(body["video_id"])
    assert row["subtitle_source"] == "transcript" and row["language"] == "en"
    assert row["transcription_model"] == "base" and row["transcription_device"] == "cpu"
    uploads = tmp_path / "app" / "data" / "uploads"
    assert list(uploads.iterdir()) == []  # immediate auto-delete
    await client.put("/api/settings/app", json={"upload_auto_delete": "false"})
    async with AsyncSessionLocal() as db:
        vid = body["video_id"]
        for t in ("subtitles_raw", "subtitles_formatted", "processing_tasks"):
            await db.execute(text(f"DELETE FROM {t} WHERE video_id IN (SELECT id FROM videos WHERE video_id=:v)"), {"v": vid})
        await db.execute(text("DELETE FROM videos WHERE video_id=:v"), {"v": vid})
        await db.commit()
