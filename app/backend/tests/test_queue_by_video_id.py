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


async def test_worker_still_derives_the_id_from_the_url_for_items_without_a_video_id(seeded_video):
    """Items queued before the video_id column was used for this keep working."""
    async def fake_clean(text_, **kw):
        return "Cleaned."

    item_id = await _insert_item("https://www.youtube.com/watch?v=dQw4w9WgXcQ", None)
    with patch("services.text_cleaner.clean_text", fake_clean):
        item = await _run_worker(item_id)
    assert item["status"] == "done" and item["video_id"] == "dQw4w9WgXcQ"
    assert (await fmt_row("dQw4w9WgXcQ"))["cleaned_text"] == "Cleaned."


async def test_item_for_a_video_that_is_not_in_history_fails_with_a_message_not_done():
    """Deleted after it was queued, or never extracted: the old worker ended 'done' having done nothing."""
    for url, vid in (("https://www.youtube.com/watch?v=neverSeen001", "neverSeen001"), (LOCAL_URL, "file-deleted0")):
        item_id = await _insert_item(url, vid)
        item = await _run_worker(item_id)
        assert item["status"] == "failed", vid
        assert vid in item["error_message"] and "not in History" in item["error_message"]


# --- the endpoint: video_ids ---------------------------------------------------

async def test_bulk_add_queues_a_local_file_by_video_id(client, local_video):
    r = await client.post("/api/queue/bulk", json={"video_ids": [LOCAL_ID], "pipeline_stages": ["cleanup", "summary"]})
    assert r.status_code == 200
    assert r.json() == {"added": 1, "ids": r.json()["ids"], "invalid": [], "duplicates": [],
                        "duplicate_details": [], "missing": []}
    item = (await client.get("/api/queue")).json()["items"][0]
    assert item["video_id"] == LOCAL_ID and item["url"] == LOCAL_URL and item["db_video_id"] == local_video["db_id"]
    assert item["pipeline_stages"] == ["cleanup", "summary"] and item["status"] == "pending"


async def test_bulk_add_by_id_reports_missing_and_pending_duplicates(client, local_video):
    body = {"video_ids": [LOCAL_ID, "file-nosuchfile", LOCAL_ID], "pipeline_stages": ["cleanup"]}
    first = (await client.post("/api/queue/bulk", json=body)).json()
    assert first["added"] == 1 and first["missing"] == ["file-nosuchfile"] and first["duplicates"] == []  # id twice -> once
    again = (await client.post("/api/queue/bulk", json=body)).json()
    assert again["added"] == 0 and again["duplicates"] == [LOCAL_ID] and again["missing"] == ["file-nosuchfile"]


async def test_bulk_add_by_id_refuses_stages_that_need_the_source(client, local_video):
    for stages in (["extract"], ["transcribe", "cleanup"], ["cleanup", "nonsense"], [], None):
        r = await client.post("/api/queue/bulk", json={"video_ids": [LOCAL_ID], "pipeline_stages": stages})
        assert r.status_code == 400, stages
        assert "cleanup, summary, mindmap" in r.json()["detail"]["message"]
    assert (await client.get("/api/queue")).json()["items"] == []


async def test_bulk_add_by_id_keeps_the_order_and_mixes_with_urls(client, local_video, seeded_video):
    r = await client.post("/api/queue/bulk", json={
        "urls": ["https://www.youtube.com/watch?v=mixedUrl001"], "video_ids": [LOCAL_ID, seeded_video["video_id"]],
        "pipeline_stages": ["summary"]})
    assert r.status_code == 200 and r.json()["added"] == 3
    items = (await client.get("/api/queue")).json()["items"]
    assert [i["video_id"] for i in items] == ["mixedUrl001", LOCAL_ID, seeded_video["video_id"]]


async def test_bulk_add_with_neither_urls_nor_ids_is_400_and_bad_urls_still_400(client):
    assert (await client.post("/api/queue/bulk", json={})).status_code == 400
    r = await client.post("/api/queue/bulk", json={"urls": ["https://example.com/x"]})
    assert r.status_code == 400 and r.json()["detail"]["message"] == "No valid YouTube URLs"


async def test_a_local_file_queued_through_the_endpoint_is_processed_end_to_end(client, local_video):
    async def fake_clean(text_, **kw):
        return "Cleaned local text."

    item_id = (await client.post("/api/queue/bulk", json={
        "video_ids": [LOCAL_ID], "pipeline_stages": ["cleanup"]})).json()["ids"][0]
    with patch("services.text_cleaner.clean_text", fake_clean):
        item = await _run_worker(item_id)
    assert item["status"] == "done" and item["video_id"] == LOCAL_ID
    assert (await fmt_row(LOCAL_ID))["cleaned_text"] == "Cleaned local text."


# --- a request is capped at 500 urls and 500 video_ids ---------------------------------

async def test_bulk_add_takes_500_urls_but_refuses_501(client):
    urls = [f"https://www.youtube.com/watch?v=cap{i:08d}" for i in range(501)]
    assert (await client.post("/api/queue/bulk", json={"urls": urls})).status_code == 422
    assert (await client.get("/api/queue")).json()["items"] == []  # nothing half-added
    ok = await client.post("/api/queue/bulk", json={"urls": urls[:500]})
    assert ok.status_code == 200 and ok.json()["added"] == 500


async def test_bulk_add_refuses_501_video_ids(client):
    ids = [f"file-{i:08d}" for i in range(501)]
    r = await client.post("/api/queue/bulk", json={"video_ids": ids, "pipeline_stages": ["cleanup"]})
    assert r.status_code == 422
    ok = await client.post("/api/queue/bulk", json={"video_ids": ids[:500], "pipeline_stages": ["cleanup"]})
    assert ok.status_code == 200 and ok.json()["added"] == 0 and len(ok.json()["missing"]) == 500


async def test_force_does_not_apply_to_video_ids(client, local_video):
    body = {"video_ids": [LOCAL_ID], "pipeline_stages": ["cleanup"], "force": True}
    assert (await client.post("/api/queue/bulk", json=body)).json()["added"] == 1
    again = (await client.post("/api/queue/bulk", json=body)).json()
    assert again["added"] == 0 and again["duplicates"] == [LOCAL_ID]  # as the docstring says


async def test_blank_video_ids_are_a_400_not_a_silent_no_op(client, local_video):
    for ids in ([" "], [""], ["\t\n"], [LOCAL_ID, "  "]):
        r = await client.post("/api/queue/bulk", json={"video_ids": ids, "pipeline_stages": ["cleanup"]})
        assert r.status_code == 400 and "empty id" in r.json()["detail"], ids
    assert (await client.get("/api/queue")).json()["items"] == []  # the valid id next to a blank one is not added


# --- duplicates come back with the video id and the reason (NS-24a) --------------------

async def test_duplicates_carry_the_video_id_for_every_url_form_and_the_reason(client, seeded_video):
    live = "https://www.youtube.com/live/dQw4w9WgXcQ"      # already in History
    short = "https://youtu.be/queuedDup01"                   # will be pending
    shorts = "https://www.youtube.com/shorts/queuedDup02"
    first = await client.post("/api/queue/bulk", json={"urls": [short, shorts]})
    assert first.json()["added"] == 2
    r = await client.post("/api/queue/bulk", json={"urls": [live, short, shorts]})
    body = r.json()
    assert body["added"] == 0 and body["duplicates"] == [live, short, shorts]  # the old key is unchanged
    assert body["duplicate_details"] == [
        {"url": live, "video_id": "dQw4w9WgXcQ", "reason": "processed"},
        {"url": short, "video_id": "queuedDup01", "reason": "in_queue"},
        {"url": shorts, "video_id": "queuedDup02", "reason": "in_queue"},
    ]


async def test_an_id_that_is_both_processed_and_queued_is_reported_as_processed(client, seeded_video):
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    await client.post("/api/queue/bulk", json={"urls": [url], "force": True, "pipeline_stages": ["summary"]})
    d = (await client.post("/api/queue/bulk", json={"urls": [url]})).json()["duplicate_details"]
    assert d == [{"url": url, "video_id": "dQw4w9WgXcQ", "reason": "processed"}]


async def test_video_ids_duplicates_are_listed_in_the_details_and_new_adds_have_none(client, local_video):
    body = {"video_ids": [LOCAL_ID], "pipeline_stages": ["cleanup"]}
    assert (await client.post("/api/queue/bulk", json=body)).json()["duplicate_details"] == []
    again = (await client.post("/api/queue/bulk", json=body)).json()
    assert again["duplicate_details"] == [{"url": None, "video_id": LOCAL_ID, "reason": "in_queue"}]
