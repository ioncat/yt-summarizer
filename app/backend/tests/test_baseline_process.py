"""NS-11 stage 7: POST /api/process.

Written as a baseline of the BackgroundTask version (the POST returned when the extraction was over); since the endpoint queues an
item (commit 2) the worker does the work, and the cases the owner decisions changed are marked in their comments.
"""
import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import text

from models.database import AsyncSessionLocal
from services.subtitle_extractor import ExtractionResult, SubtitleEntry, VideoMetadata
from tests.baseline_helpers import fmt_row, reset_queue, run_extract_items

NEW = "stg7Proc001"
URL = f"https://www.youtube.com/watch?v={NEW}"


def extraction(video_id=NEW, line="Fresh line."):
    meta = VideoMetadata(video_id=video_id, title="T", author="A", duration=60, channel_id=None, channel_name=None, upload_date=None,
                         view_count=None, description=None, thumbnail_url=None)
    return ExtractionResult(success=True, metadata=meta, subtitles=[SubtitleEntry(timestamp="00:00:01", text=line)],
                            language="en", source_type=None)


def failed(message="No subtitles in ru", languages=("en", "de")):
    return SimpleNamespace(success=False, error_message=message, available_languages=list(languages) if languages is not None else None,
                           error_type="x", subtitles=[], metadata=None, language=None)


async def forget(video_id=NEW):
    await reset_queue()
    async with AsyncSessionLocal() as db:
        for t in ("subtitles_raw", "subtitles_formatted", "processing_tasks"):
            await db.execute(text(f"DELETE FROM {t} WHERE video_id IN (SELECT id FROM videos WHERE video_id = :v)"), {"v": video_id})
        await db.execute(text("DELETE FROM videos WHERE video_id = :v"), {"v": video_id})
        await db.execute(text("DELETE FROM processing_queue WHERE video_id = :v"), {"v": video_id})
        await db.execute(text("DELETE FROM processing_stages WHERE video_id = :v"), {"v": video_id})
        await db.commit()


async def test_a_new_link_is_extracted_and_stored_and_the_task_completes(client):
    with patch("services.subtitle_extractor.extract_subtitles", return_value=extraction()):
        r = await client.post("/api/process", json={"url": URL, "language": "en"})
        await run_extract_items(NEW)             # NS-11 stage 7: a queue item, the worker does it
    assert r.status_code == 200 and r.json()["video_id"] == NEW and r.json()["task_id"]
    st = (await client.get(f"/api/status/{r.json()['task_id']}")).json()
    assert st["status"] == "completed" and st["progress_text"] is None
    assert "Fresh line." in (await fmt_row(NEW))["formatted_text"]
    assert (await client.get(f"/api/result/{NEW}")).status_code == 200
    await forget()


async def test_an_exception_in_the_extractor_fails_the_task_with_its_text(client):
    def boom(*a, **k):
        raise RuntimeError("yt-dlp crashed")

    with patch("services.subtitle_extractor.extract_subtitles", boom):
        r = await client.post("/api/process", json={"url": URL})
        (item,) = await run_extract_items(NEW)
    st = (await client.get(f"/api/status/{r.json()['task_id']}")).json()
    assert st["status"] == "failed" and st["error_message"] == "yt-dlp crashed" and st["available_languages"] is None
    assert item["status"] == "failed" and item["error_message"] == "yt-dlp crashed"       # the queue item says so too
    assert await fmt_row(NEW) is None
    await forget()


async def test_a_failure_without_languages_has_none(client):
    with patch("services.subtitle_extractor.extract_subtitles", return_value=failed("This video is not accessible.", languages=None)):
        r = await client.post("/api/process", json={"url": URL})
        await run_extract_items(NEW)
    st = (await client.get(f"/api/status/{r.json()['task_id']}")).json()
    assert st["status"] == "failed" and st["error_message"] == "This video is not accessible."
    await forget()


async def test_the_status_says_waiting_in_the_queue_then_extracting_and_nothing_when_over(client):
    # NS-11 stage 7: this used to be "pending, no progress text" at all times (BASELINE)
    release, started = threading.Event(), threading.Event()

    def slow(*a, **k):
        started.set()
        release.wait(5)
        return extraction()

    with patch("services.subtitle_extractor.extract_subtitles", slow):
        task_id = (await client.post("/api/process", json={"url": URL})).json()["task_id"]
        st = (await client.get(f"/api/status/{task_id}")).json()
        assert st["status"] == "pending" and st["progress_text"] == "waiting in the queue"
        worker = asyncio.create_task(run_extract_items(NEW))
        try:
            await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
            st = (await client.get(f"/api/status/{task_id}")).json()
            assert st["status"] == "pending" and st["progress_text"] == "extracting subtitles…"
        finally:
            release.set()
        await worker
    st = (await client.get(f"/api/status/{task_id}")).json()
    assert st["status"] == "completed" and st["progress_text"] is None
    await forget()


async def test_a_second_post_for_a_link_that_is_queued_or_running_gets_the_same_task_and_adds_no_item(client):
    release, started = threading.Event(), threading.Event()

    def slow(*a, **k):
        started.set()
        release.wait(5)
        return extraction()

    with patch("services.subtitle_extractor.extract_subtitles", slow):
        first = await client.post("/api/process", json={"url": URL})
        queued_again = await client.post("/api/process", json={"url": URL})            # while it waits ...
        worker = asyncio.create_task(run_extract_items(NEW))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        running_again = await client.post("/api/process", json={"url": URL})           # ... and while it runs
        assert (await client.get("/api/queue")).json()["count"] == 1
        release.set()
        await worker
    assert queued_again.json()["task_id"] == running_again.json()["task_id"] == first.json()["task_id"]
    await forget()


async def test_a_url_with_a_playlist_part_or_other_forms_is_reduced_to_the_video_id(client):
    with patch("services.subtitle_extractor.extract_subtitles", return_value=extraction()):
        r = await client.post("/api/process", json={"url": f"https://youtu.be/{NEW}?t=30"})
        await run_extract_items(NEW)
    assert r.status_code == 200 and r.json()["video_id"] == NEW
    await forget()


async def test_an_invalid_link_is_400_and_an_unknown_task_404(client):
    assert (await client.post("/api/process", json={"url": "https://example.com/x"})).status_code == 400
    assert (await client.get("/api/status/no-such-task")).status_code == 404


async def test_the_default_language_of_the_request_is_ru(client):
    # BASELINE: changes in stage 7 (decision 8: default language auto everywhere)
    seen = {}

    def fake(url, language, cookies, ytdlp):
        seen["language"] = language
        return extraction()

    with patch("services.subtitle_extractor.extract_subtitles", fake):
        await client.post("/api/process", json={"url": URL})
        await run_extract_items(NEW)
    assert seen["language"] == "ru"
    await forget()


async def test_the_post_answers_at_once_and_the_work_waits_for_the_queue_worker(client):
    # NS-11 stage 7 (decision 6): the link is a normal queue item; nothing is extracted until the worker gets to it.
    seen = {}

    def quick(*a, **k):
        seen["ran"] = True
        time.sleep(0.01)
        return extraction()

    with patch("services.subtitle_extractor.extract_subtitles", quick):
        r = await client.post("/api/process", json={"url": URL, "language": "de"})
        assert seen == {}                                                  # the response came before any extraction
        (queued,) = (await client.get("/api/queue")).json()["items"]
        assert (queued["status"], queued["url"], queued["pipeline_stages"], queued["language"]) == ("pending", URL, ["extract"], "de")
        assert (await client.get(f"/api/status/{r.json()['task_id']}")).json()["status"] == "pending"
        await run_extract_items(NEW)
    assert seen == {"ran": True}
    assert (await client.get(f"/api/status/{r.json()['task_id']}")).json()["status"] == "completed"
    await forget()
