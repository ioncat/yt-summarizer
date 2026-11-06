"""NS-11 stage 7: POST /api/process queues an extract item (url = the canonical link, stages ["extract"], db_video_id = the task's video)."""
from unittest.mock import patch

import pytest
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import queue_service as q
from tests.baseline_helpers import reset_queue, run_extract_items, run_worker
from tests.test_baseline_process import NEW, URL, extraction, failed, forget


@pytest.fixture(autouse=True)
async def _clean(client):
    await reset_queue()
    yield
    await forget()


async def _items(client):
    return (await client.get("/api/queue")).json()["items"]


async def _status(client, task_id):
    return (await client.get(f"/api/status/{task_id}")).json()


async def test_removing_the_queued_item_ends_its_task_so_the_page_does_not_wait_for_ever(client):
    r = await client.post("/api/process", json={"url": URL})
    (item,) = await _items(client)
    assert (await client.delete(f"/api/queue/{item['id']}")).status_code == 200
    st = await _status(client, r.json()["task_id"])
    assert st["status"] == "failed" and st["error_message"] == "Removed from the queue"


async def test_clear_pending_ends_the_tasks_of_the_queued_links(client):
    first = await client.post("/api/process", json={"url": URL})
    second = await client.post("/api/process", json={"url": "https://www.youtube.com/watch?v=stg7Proc002"})
    assert (await client.delete("/api/queue/all")).json()["cleared"] == 2
    for r in (first, second):
        assert (await _status(client, r.json()["task_id"]))["error_message"] == "Removed from the queue"
    await forget("stg7Proc002")


async def test_removing_an_item_without_a_task_still_works(client):
    """Bulk adds have no task (the worker makes it when it starts): nothing to release, nothing breaks."""
    r = await client.post("/api/queue/bulk", json={"urls": [URL], "pipeline_stages": ["extract"]})
    (item,) = [i for i in await _items(client)]
    assert (await client.delete(f"/api/queue/{item['id']}")).status_code == 200
    assert r.status_code == 200 and await _items(client) == []


async def test_a_link_already_queued_by_the_bulk_add_is_not_queued_twice_and_its_run_completes_the_task(client):
    await client.post("/api/queue/bulk", json={"urls": [URL], "pipeline_stages": ["extract"]})
    r = await client.post("/api/process", json={"url": URL})                  # same video, already queued by the bulk add
    assert len(await _items(client)) == 1
    with patch("services.subtitle_extractor.extract_subtitles", return_value=extraction()):
        (queue_item,) = [i for i in await _items(client)]
        await run_worker([queue_item["id"]])
    assert (await _status(client, r.json()["task_id"]))["status"] == "completed"


async def test_a_restart_in_the_middle_runs_the_extraction_again_to_the_end(client):
    with patch("services.subtitle_extractor.extract_subtitles", return_value=extraction()):
        r = await client.post("/api/process", json={"url": URL})
        (item,) = await _items(client)
        await q._set_processing(item["id"])                # the worker had taken it ...
        await q._reset_stuck_items()                        # ... and the backend restarted
        assert (await _items(client))[0]["status"] == "pending"
        (done,) = await run_extract_items(NEW)
    assert done["status"] == "done"
    assert (await _status(client, r.json()["task_id"]))["status"] == "completed"


async def test_a_failure_keeps_the_languages_the_video_has_for_the_processing_page(client):
    with patch("services.subtitle_extractor.extract_subtitles", return_value=failed("No subtitles in ru", ["en", "uk"])):
        r = await client.post("/api/process", json={"url": URL, "language": "ru"})
        (item,) = await run_extract_items(NEW)
    st = await _status(client, r.json()["task_id"])
    assert (st["status"], st["error_message"], st["available_languages"]) == ("failed", "No subtitles in ru", ["en", "uk"])
    assert item["status"] == "failed" and item["error_message"] == "No subtitles in ru"


async def test_a_known_video_is_still_409_and_queues_nothing(client, seeded_video):
    r = await client.post("/api/process", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert r.status_code == 409 and r.json()["detail"]["video_id"] == "dQw4w9WgXcQ"
    assert await _items(client) == []


async def test_a_burst_of_enqueue_calls_on_a_file_database_inserts_exactly_one_item(tmp_path):
    """Real concurrency: separate connections to a database file."""
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker
    from models.database import create_engine_for
    from models.models import ProcessingQueueItem
    from services.extract_queue import enqueue_extract

    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path / 'burst.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: ProcessingQueueItem.__table__.create(c))
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def one():
        async with factory() as db:
            return await enqueue_extract(db, URL, NEW, "db-id", "auto")

    results = await asyncio.gather(*[one() for _ in range(10)])
    assert len([r for r in results if r is not None]) == 1 and results.count(None) == 9
    async with factory() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM processing_queue"))).scalar() == 1
        await db.execute(text("UPDATE processing_queue SET status = 'done'"))
        await db.commit()
    assert await one() is not None                         # once the item is over, a new request is accepted
    await engine.dispose()
