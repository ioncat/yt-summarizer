"""NS-11 stage 7, commit 1 (tests only): what POST /api/process does TODAY, before it queues an item.

It runs the extraction as a BackgroundTask (the POST returns when it is over). Cases the owner decisions change are marked
`# BASELINE:`; they are rewritten in the commit that changes the behaviour.
"""
import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import text

from models.database import AsyncSessionLocal
from services.subtitle_extractor import ExtractionResult, SubtitleEntry, VideoMetadata
from tests.baseline_helpers import fmt_row

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
    async with AsyncSessionLocal() as db:
        for t in ("subtitles_raw", "subtitles_formatted", "processing_tasks"):
            await db.execute(text(f"DELETE FROM {t} WHERE video_id IN (SELECT id FROM videos WHERE video_id = :v)"), {"v": video_id})
        await db.execute(text("DELETE FROM videos WHERE video_id = :v"), {"v": video_id})
        await db.execute(text("DELETE FROM processing_queue WHERE video_id = :v"), {"v": video_id})
        await db.execute(text("DELETE FROM processing_stages WHERE video_id = :v"), {"v": video_id})
        await db.commit()


async def test_a_new_link_is_extracted_and_stored_and_the_task_completes(client):
    with patch("routers.process.extract_subtitles", return_value=extraction()):
        r = await client.post("/api/process", json={"url": URL, "language": "en"})
    assert r.status_code == 200 and r.json()["video_id"] == NEW and r.json()["task_id"]
    st = (await client.get(f"/api/status/{r.json()['task_id']}")).json()
    assert st["status"] == "completed" and st["progress_text"] is None
    assert "Fresh line." in (await fmt_row(NEW))["formatted_text"]
    assert (await client.get(f"/api/result/{NEW}")).status_code == 200
    await forget()


async def test_an_exception_in_the_extractor_fails_the_task_with_its_text(client):
    def boom(*a, **k):
        raise RuntimeError("yt-dlp crashed")

    with patch("routers.process.extract_subtitles", boom):
        r = await client.post("/api/process", json={"url": URL})
    st = (await client.get(f"/api/status/{r.json()['task_id']}")).json()
    assert st["status"] == "failed" and st["error_message"] == "yt-dlp crashed" and st["available_languages"] is None
    assert await fmt_row(NEW) is None
    await forget()


async def test_a_failure_without_languages_has_none(client):
    with patch("routers.process.extract_subtitles", return_value=failed("This video is not accessible.", languages=None)):
        r = await client.post("/api/process", json={"url": URL})
    st = (await client.get(f"/api/status/{r.json()['task_id']}")).json()
    assert st["status"] == "failed" and st["error_message"] == "This video is not accessible."
    await forget()


async def test_the_status_of_a_running_extraction_is_pending_without_progress_text(client):
    release, started = threading.Event(), threading.Event()

    def slow(*a, **k):
        started.set()
        release.wait(5)
        return extraction()

    with patch("routers.process.extract_subtitles", slow):
        post = asyncio.create_task(client.post("/api/process", json={"url": URL}))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        async with AsyncSessionLocal() as db:
            task_id = (await db.execute(text("SELECT t.id FROM processing_tasks t JOIN videos v ON v.id = t.video_id "
                                             "WHERE v.video_id = :v"), {"v": NEW})).scalar()
        st = (await client.get(f"/api/status/{task_id}")).json()
        assert st["status"] == "pending" and st["progress_text"] is None
        release.set()
        await post
    await forget()


async def test_a_second_post_for_a_link_that_is_still_being_extracted_gets_the_same_task(client):
    release, started = threading.Event(), threading.Event()

    def slow(*a, **k):
        started.set()
        release.wait(5)
        return extraction()

    with patch("routers.process.extract_subtitles", slow):
        first = asyncio.create_task(client.post("/api/process", json={"url": URL}))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        second = await client.post("/api/process", json={"url": URL})
        release.set()
        first_response = await first
    assert second.status_code == 200 and second.json()["task_id"] == first_response.json()["task_id"]
    await forget()


async def test_a_url_with_a_playlist_part_or_other_forms_is_reduced_to_the_video_id(client):
    with patch("routers.process.extract_subtitles", return_value=extraction()):
        r = await client.post("/api/process", json={"url": f"https://youtu.be/{NEW}?t=30"})
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

    with patch("routers.process.extract_subtitles", fake):
        await client.post("/api/process", json={"url": URL})
    assert seen["language"] == "ru"
    await forget()


async def test_post_runs_the_extraction_inside_the_request_so_it_answers_only_when_done(client):
    # BASELINE: changes in stage 7 - the POST will answer at once and the work waits its turn in the queue.
    seen = {}

    def quick(*a, **k):
        seen["ran"] = True
        time.sleep(0.01)
        return extraction()

    with patch("routers.process.extract_subtitles", quick):
        await client.post("/api/process", json={"url": URL})
    assert seen == {"ran": True}                                           # already ran when the response arrived
    await forget()
