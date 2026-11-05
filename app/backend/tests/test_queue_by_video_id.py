"""NS-11 stage 1: the queue works by video_id, so a local file is a normal queue item.

Local files have no YouTube URL (their url is `local://<name>`); an item names the video by `video_id`.
LLM calls are faked; the DB is the in-memory test DB.
"""
import asyncio
import time
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import queue_service as q
from tests.baseline_helpers import fmt_row, reset_queue

LOCAL_ID = "file-1a2b3c4d"
LOCAL_URL = "local://talk.m4a"


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    await reset_queue()
    await client.put("/api/settings/cleanup", json={"model": "m-clean"})
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    await reset_queue()


@pytest_asyncio.fixture
async def local_video(db_session):
    """A transcribed local file, as /api/process/file leaves it."""
    from models.models import SubtitleFormatted, Video
    video = Video(url=LOCAL_URL, video_id=LOCAL_ID, title="talk.m4a", author=None, duration=60)
    db_session.add(video)
    await db_session.flush()
    fmt = SubtitleFormatted(video_id=video.id, language="en", subtitle_source="transcript",
                            formatted_text="Hello there.\n\nThis is a local recording.",
                            text_length=40, processing_status="success")
    db_session.add(fmt)
    await db_session.commit()
    yield {"video_id": LOCAL_ID, "db_id": video.id}
    await db_session.execute(text("DELETE FROM subtitles_formatted WHERE video_id = :v"), {"v": video.id})
    await db_session.execute(text("DELETE FROM videos WHERE id = :v"), {"v": video.id})
    await db_session.commit()


async def _insert_item(url, video_id, stages='["cleanup"]') -> int:
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order) "
                 "VALUES (:u, :v, 'pending', :s, datetime('now'), 1)"),
            {"u": url, "v": video_id, "s": stages})
        await db.commit()
        return res.lastrowid


async def _run_worker(item_id: int, timeout: float = 15.0) -> dict:
    task = asyncio.create_task(q.queue_worker())
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            async with AsyncSessionLocal() as db:
                status = (await db.execute(text("SELECT status FROM processing_queue WHERE id = :i"),
                                           {"i": item_id})).scalar()
            if status in ("done", "failed"):
                break
            await asyncio.sleep(0.05)
    finally:
        q._WORKER_STOP = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        q._WORKER_STOP = False
    async with AsyncSessionLocal() as db:
        return next(i for i in await q.get_queue(db) if i["id"] == item_id)


async def test_worker_cleans_a_local_file_item_by_its_video_id(local_video):
    seen = []

    async def fake_clean(text_, **kw):
        seen.append(text_)
        return "Cleaned local text."

    item_id = await _insert_item(LOCAL_URL, LOCAL_ID)  # the url cannot give a video id; the column does
    with patch("services.text_cleaner.clean_text", fake_clean):
        item = await _run_worker(item_id)
    assert item["status"] == "done" and item["error_message"] is None
    assert item["video_id"] == LOCAL_ID
    assert seen and seen[0].startswith("Hello there.")
    row = await fmt_row(LOCAL_ID)
    assert row["cleanup_status"] == "done" and row["cleaned_text"] == "Cleaned local text."


async def test_worker_still_derives_the_id_from_the_url_for_items_without_a_video_id():
    """Items queued before the video_id column was used for this keep working."""
    item_id = await _insert_item("https://www.youtube.com/watch?v=oldItem0001", None)
    with patch("services.text_cleaner.clean_text", lambda *a, **k: None):
        item = await _run_worker(item_id)
    assert item["video_id"] == "oldItem0001"  # set from the URL, not 'cannot extract video_id'
    assert item["status"] in ("done", "failed")
