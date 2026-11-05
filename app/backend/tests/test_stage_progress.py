"""NS-25 / NS-11 stage 4b: live counters on the stage's run row, written throttled through a short session."""
import asyncio
import json
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import queue_service as q
from services import stage_progress, stage_runs
from services.stage_control import CLEANUP_CANCEL, SUMMARY_CANCEL
from services.stage_progress import ProgressWriter, set_progress
from tests.baseline_helpers import Gate, VIDEO_ID, reset_queue


@pytest_asyncio.fixture(autouse=True)
async def _clean(client):
    async def wipe():
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM processing_stages"))
            await db.commit()
        await reset_queue()
    CLEANUP_CANCEL.clear()
    SUMMARY_CANCEL.clear()
    await wipe()
    yield
    await wipe()


async def row(stage="cleanup", video_id=VIDEO_ID):
    async with AsyncSessionLocal() as db:
        r = (await db.execute(text("SELECT * FROM processing_stages WHERE video_id = :v AND stage = :s ORDER BY id DESC LIMIT 1"),
                              {"v": video_id, "s": stage})).mappings().first()
        return dict(r) if r else None


async def begin(stage="cleanup", video_id=VIDEO_ID):
    async with AsyncSessionLocal() as db:
        await stage_runs.begin(db, video_id, stage, "m")
        await db.commit()


# --- the writer ---------------------------------------------------------------------------------------------

async def test_set_progress_writes_the_open_run_only_and_keeps_the_unit_in_meta():
    await begin()
    assert await set_progress(VIDEO_ID, "cleanup", 2, 9, "paragraph") is True
    r = await row()
    assert (r["progress_done"], r["progress_total"]) == (2, 9) and json.loads(r["meta"]) == {"unit": "paragraph"}
    async with AsyncSessionLocal() as db:
        await stage_runs.finish(db, VIDEO_ID, "cleanup")
        await db.commit()
    assert await set_progress(VIDEO_ID, "cleanup", 5, 9) is False            # the run is over: nothing is touched
    assert (await row())["progress_done"] == 2


async def test_many_rapid_updates_are_coalesced_and_the_last_value_always_lands():
    await begin()
    writes: list[tuple[int, int]] = []
    real = stage_progress.set_progress

    async def counting(video_id, stage, done, total, unit=None):
        writes.append((done, total))
        return await real(video_id, stage, done, total, unit)

    w = ProgressWriter(VIDEO_ID, "cleanup", "paragraph", min_interval=0.3)
    with patch.object(stage_progress, "set_progress", counting):
        for i in range(1, 101):
            w.update(i, 100)
            if i % 20 == 0:
                await asyncio.sleep(0.05)
        await w.close()
    assert 1 <= len(writes) <= 4                                           # not one write per call
    assert writes[-1] == (100, 100)
    assert (await row())["progress_done"] == 100


async def test_nothing_is_written_after_close_and_close_twice_is_harmless():
    await begin()
    w = ProgressWriter(VIDEO_ID, "cleanup", min_interval=0.0)
    w.update(1, 4)
    await w.close()
    w.update(3, 4)                                                          # after close: ignored
    await asyncio.sleep(0.05)
    await w.close()
    assert (await row())["progress_done"] == 1


async def test_a_failing_write_is_logged_and_never_raises():
    await begin()

    async def broken(*a, **k):
        raise RuntimeError("database is locked")

    w = ProgressWriter(VIDEO_ID, "cleanup", min_interval=0.0)
    with patch.object(stage_progress, "set_progress", broken):
        w.update(1, 2)
        await asyncio.sleep(0.05)
        await w.close()                                                     # no exception
    assert (await row())["progress_done"] is None


def test_update_without_a_running_loop_does_not_raise():
    ProgressWriter("v", "cleanup").update(1, 2)


# --- through the stage runners -------------------------------------------------------------------------------

async def test_a_running_cleanup_has_its_counters_on_the_row_and_keeps_the_last_ones_when_done(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m-clean"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    gate = Gate(result="Cleaned.", progress=(2, 3))
    with patch("services.text_cleaner.clean_text", gate.llm()):
        task = asyncio.create_task(q._run_cleanup_stage(VIDEO_ID, 3))
        await gate.wait_started()
        for _ in range(50):                                                 # the first write is not delayed
            r = await row()
            if r and r["progress_done"] is not None:
                break
            await asyncio.sleep(0.02)
        assert (r["status"], r["progress_done"], r["progress_total"]) == ("processing", 2, 3)
        assert json.loads(r["meta"])["unit"] == "paragraph" and r["queue_item_id"] == 3
        gate.release.set()
        await task
    r = await row()
    assert (r["status"], r["progress_done"], r["progress_total"]) == ("done", 2, 3)


async def test_a_summary_run_records_chunks_and_a_stopped_run_keeps_the_last_counters(client, seeded_video):
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    gate = Gate(result=("S", "single", 1), progress=(1, 5))
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        task = asyncio.create_task(q._run_summary_stage(VIDEO_ID, 4))
        await gate.wait_started()
        await asyncio.sleep(0.1)
        SUMMARY_CANCEL.add(VIDEO_ID)                                        # Stop
        gate.release.set()
        with pytest.raises(q.StageCancelled):
            await task
    r = await row("summary")
    assert (r["status"], r["progress_done"], r["progress_total"]) == ("cancelled", 1, 5)
    assert json.loads(r["meta"])["unit"] == "chunk"


# --- what the API says, read from the row ------------------------------------------------------------------------

async def test_the_result_shows_the_counters_of_a_running_run_from_the_row_and_drops_them_when_it_ends(client, seeded_video):
    await begin("cleanup")
    await begin("summary")
    await set_progress(VIDEO_ID, "cleanup", 4, 10, "paragraph")
    await set_progress(VIDEO_ID, "summary", 1, 3, "chapter")
    data = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert (data["cleanup_paragraphs_done"], data["cleanup_paragraphs_total"]) == (4, 10)
    assert (data["summary_chunks_done"], data["summary_chunks_total"]) == (1, 3)
    async with AsyncSessionLocal() as db:
        await stage_runs.finish(db, VIDEO_ID, "cleanup")
        await stage_runs.cancel(db, VIDEO_ID, "summary")
        await db.commit()
    data = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert "cleanup_paragraphs_done" not in data and "summary_chunks_done" not in data
    assert (data["stages"]["cleanup"]["progress_done"], data["stages"]["cleanup"]["progress_total"]) == (4, 10)   # kept on the row


async def test_a_run_without_counters_yet_has_none_in_the_result(client, seeded_video):
    await begin("cleanup")
    data = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert data["cleanup_status"] == "processing" and "cleanup_paragraphs_done" not in data


async def test_the_queue_page_progress_of_a_running_item_comes_from_its_run_row(client, seeded_video):
    async with AsyncSessionLocal() as db:
        item = (await db.execute(
            text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order) "
                 f"VALUES ('https://www.youtube.com/watch?v={VIDEO_ID}', '{VIDEO_ID}', 'processing', '[\"cleanup\"]', datetime('now'), 1)"))).lastrowid
        await stage_runs.begin(db, VIDEO_ID, "cleanup", "m", item)
        await db.commit()
    await set_progress(VIDEO_ID, "cleanup", 3, 7, "paragraph")
    items = {i["id"]: i for i in (await client.get("/api/queue")).json()["items"]}
    assert items[item]["progress"] == "cleanup: paragraph 3/7"
    await set_progress(VIDEO_ID, "cleanup", 4, 7)
    items = {i["id"]: i for i in (await client.get("/api/queue")).json()["items"]}
    assert items[item]["progress"] == "cleanup: paragraph 4/7"                 # the unit word stays
