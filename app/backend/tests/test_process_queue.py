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


async def test_a_burst_of_enqueue_calls_on_a_file_database_inserts_exactly_one_item_and_one_run(tmp_path):
    """Real concurrency: separate connections to a database file."""
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker
    from models.database import create_engine_for
    from models.models import ProcessingQueueItem, ProcessingStage
    from services.extract_queue import enqueue_extract

    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path / 'burst.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: ProcessingQueueItem.__table__.create(c))
        await conn.run_sync(lambda c: ProcessingStage.__table__.create(c))
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def one():
        async with factory() as db:
            return await enqueue_extract(db, URL, NEW, "db-id", "auto")

    results = await asyncio.gather(*[one() for _ in range(10)])
    assert len([r for r in results if r is not None]) == 1 and results.count(None) == 9
    async with factory() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM processing_queue"))).scalar() == 1
        assert (await db.execute(text("SELECT COUNT(*) FROM processing_stages WHERE status = 'processing' AND stage = 'extract'"))).scalar() == 1
        await db.execute(text("UPDATE processing_queue SET status = 'done'"))
        await db.commit()
    assert await one() is not None                         # once the item is over, a new request is accepted
    await engine.dispose()


# --- the extract run row (decision: stage rows in processing_stages) -----------------------------------------------------

async def _runs(video_id=NEW):
    async with AsyncSessionLocal() as db:
        return [dict(r) for r in (await db.execute(
            text("SELECT * FROM processing_stages WHERE video_id = :v AND stage = 'extract' ORDER BY id"), {"v": video_id})).mappings().all()]


async def test_the_request_opens_the_extract_run_and_the_worker_closes_it_done(client):
    r = await client.post("/api/process", json={"url": URL})
    (item,) = await _items(client)
    (run,) = await _runs()
    assert (run["status"], run["queue_item_id"], run["attempt"]) == ("processing", item["id"], 1)
    with patch("services.subtitle_extractor.extract_subtitles", return_value=extraction()):
        await run_extract_items(NEW)
    (run,) = await _runs()                                       # the same row, now closed
    assert (run["status"], run["error_code"]) == ("done", None) and run["finished_at"]
    assert r.status_code == 200


async def test_a_failed_extraction_closes_the_run_failed_with_a_reason_code(client):
    with patch("services.subtitle_extractor.extract_subtitles", return_value=failed("This video has no subtitles available.", ["en"])):
        await client.post("/api/process", json={"url": URL})
        await run_extract_items(NEW)
    (run,) = await _runs()
    assert (run["status"], run["error_code"]) == ("failed", "no_subtitles") and "no subtitles" in run["error_text"]


async def test_removing_the_queued_item_cancels_its_run(client):
    await client.post("/api/process", json={"url": URL})
    (item,) = await _items(client)
    await client.delete(f"/api/queue/{item['id']}")
    assert [r["status"] for r in await _runs()] == ["cancelled"]


async def test_clear_pending_cancels_the_runs_of_the_queued_links(client):
    await client.post("/api/process", json={"url": URL})
    await client.delete("/api/queue/all")
    assert [r["status"] for r in await _runs()] == ["cancelled"]


async def test_the_status_text_for_a_bulk_added_item_is_not_invented(client):
    """A bulk add makes its task only when the worker starts: before that no task exists, so there is nothing to report."""
    await client.post("/api/queue/bulk", json={"urls": [URL], "pipeline_stages": ["extract"]})
    assert (await client.get("/api/status/no-such-task")).status_code == 404


def test_the_background_copy_of_the_extraction_is_gone():
    import routers.process as proc
    assert not hasattr(proc, "_run_processing")
    assert not hasattr(proc, "BackgroundTasks") and not hasattr(proc, "extract_subtitles")        # the router no longer runs any work itself


# --- simultaneous twins of a NEW link (stage 7 review) ----------------------------------------------------------------------

async def test_simultaneous_posts_for_a_new_link_all_get_the_same_task(client):
    import asyncio
    answers = await asyncio.gather(*[client.post("/api/process", json={"url": URL}) for _ in range(5)])
    assert [a.status_code for a in answers] == [200] * 5, [a.status_code for a in answers]
    assert len({a.json()["task_id"] for a in answers}) == 1
    assert {a.json()["video_id"] for a in answers} == {NEW}


async def test_twins_of_a_link_whose_earlier_task_failed_also_get_one_new_task(client):
    """A failed attempt leaves its placeholder behind; the next attempt reuses/replaces it, and twins of that attempt agree."""
    import asyncio
    with patch("services.subtitle_extractor.extract_subtitles", return_value=failed("No subtitles in ru", ["en"])):
        first = await client.post("/api/process", json={"url": URL})
        await run_extract_items(NEW)
    assert (await _status(client, first.json()["task_id"]))["status"] == "failed"
    answers = await asyncio.gather(*[client.post("/api/process", json={"url": URL}) for _ in range(4)])
    assert [a.status_code for a in answers] == [200] * 4
    ids = {a.json()["task_id"] for a in answers}
    assert len(ids) == 1 and first.json()["task_id"] not in ids
    assert (await _status(client, ids.pop()))["status"] == "pending"


async def test_twins_on_a_file_database_get_one_task_and_one_placeholder(tmp_path):
    """Real concurrency: separate connections to a database file."""
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker
    from models.database import create_engine_for
    from models.models import ProcessingTask, Video
    from services.video_service import create_pending_task

    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path / 'twins.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Video.__table__.create(c))
        await conn.run_sync(lambda c: ProcessingTask.__table__.create(c))
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def one():
        async with factory() as db:
            return (await create_pending_task(db, URL, NEW)).id

    ids = await asyncio.gather(*[one() for _ in range(10)])
    assert len(set(ids)) == 1
    async with factory() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM videos"))).scalar() == 1
        assert (await db.execute(text("SELECT COUNT(*) FROM processing_tasks"))).scalar() == 1
    # after that task failed, the next attempt gets a NEW task on a clean placeholder
    async with factory() as db:
        await db.execute(text("UPDATE processing_tasks SET status = 'failed'"))
        await db.commit()
    again = await asyncio.gather(*[one() for _ in range(6)])
    assert len(set(again)) == 1 and again[0] != ids[0]
    async with factory() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM videos"))).scalar() == 1
        assert (await db.execute(text("SELECT COUNT(*) FROM processing_tasks WHERE status = 'pending'"))).scalar() == 1
    await engine.dispose()
