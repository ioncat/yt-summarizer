"""NS-11 stage 2: /api/result/{id}/mindmap queues the work. The owner's decisions, as tests."""
import asyncio
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import queue_service as q
from services.stage_control import MINDMAP_CANCEL
from tests.baseline_helpers import Gate, VIDEO_ID, add_item, fmt_row, get_item, reset_queue, run_worker, set_fmt

URL = f"/api/result/{VIDEO_ID}"


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    MINDMAP_CANCEL.clear()
    await reset_queue()
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    MINDMAP_CANCEL.clear()
    await reset_queue()


async def _items(video_id=VIDEO_ID):
    async with AsyncSessionLocal() as db:
        return [i for i in await q.get_queue(db) if i["video_id"] == video_id]


# --- decision 3: "processing" is set at once ----------------------------------------------------

async def test_the_status_is_processing_at_once_while_the_item_still_waits_in_the_queue(client, seeded_video):
    r = await client.post(f"{URL}/mindmap")
    assert r.json() == {"status": "processing"}
    assert (await fmt_row())["mindmap_status"] == "processing"      # nobody has started it yet
    items = await _items()
    assert len(items) == 1 and items[0]["status"] == "pending" and items[0]["pipeline_stages"] == ["mindmap"]
    assert (await client.get(URL)).json()["mindmap_status"] == "processing"   # what the result page polls


async def test_a_mind_map_waits_its_turn_behind_an_earlier_item(client, seeded_video):
    first = await add_item(["summary"], video_id="otherVideo01")    # queued earlier (for another video)
    await client.post(f"{URL}/mindmap")
    mind = (await _items())[0]
    assert mind["sort_order"] > (await get_item(first))["sort_order"]   # processed after it, in order
    assert (await fmt_row())["mindmap_status"] == "processing"


# --- decision 4: the saved map until Regenerate -----------------------------------------------------

async def test_the_saved_map_is_returned_until_regenerate_and_survives_the_regeneration_run(client, seeded_video):
    await set_fmt(mindmap_text="SAVED MAP", mindmap_status="done")
    r = await client.post(f"{URL}/mindmap")
    assert r.json() == {"status": "done", "mindmap_text": "SAVED MAP"} and await _items() == []
    gate = Gate(result="NEW MAP")
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        await client.post(f"{URL}/mindmap", params={"force": "true"})       # Regenerate
        item = (await _items())[0]
        worker = asyncio.create_task(run_worker([item["id"]]))
        await gate.wait_started()
        assert (await fmt_row())["mindmap_text"] == "SAVED MAP"             # the old map stays while it runs
        assert (await client.get(URL)).json()["mindmap_status"] == "processing"
        gate.release.set()
        await worker
    assert (await fmt_row())["mindmap_text"] == "NEW MAP"


# --- one item, not two ---------------------------------------------------------------------------

async def test_clicking_twice_queues_one_item(client, seeded_video):
    await client.post(f"{URL}/mindmap")
    await client.post(f"{URL}/mindmap")
    await client.post(f"{URL}/mindmap", params={"force": "true"})
    assert len(await _items()) == 1


async def test_clicks_at_the_same_moment_queue_one_item(client, seeded_video):
    await asyncio.gather(*(client.post(f"{URL}/mindmap", params={"force": "true"}) for _ in range(5)))
    assert len(await _items()) == 1


async def test_an_item_for_other_stages_does_not_stand_in_for_the_mind_map(client, seeded_video):
    await add_item(["cleanup"])                                   # pending, but it has no mind map stage
    await client.post(f"{URL}/mindmap")
    stages = sorted(i["pipeline_stages"] for i in await _items())
    assert stages == [["cleanup"], ["mindmap"]]


async def test_an_item_that_already_includes_the_mind_map_stands_in_for_it(client, seeded_video):
    await add_item(["cleanup", "summary", "mindmap"])
    await client.post(f"{URL}/mindmap")
    assert len(await _items()) == 1


async def test_a_finished_item_does_not_block_a_new_mind_map(client, seeded_video):
    await client.post(f"{URL}/mindmap")
    item = (await _items())[0]
    gate = Gate(result="# M")
    gate.release.set()
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        await run_worker([item["id"]])
    await client.post(f"{URL}/mindmap", params={"force": "true"})
    assert len(await _items()) == 2 and sorted(i["status"] for i in await _items()) == ["done", "pending"]


# --- decision 1: cancel as in the background copy ------------------------------------------------

async def test_stop_on_a_queued_mind_map_takes_it_out_and_resets_the_status_keeping_the_saved_map(client, seeded_video):
    await set_fmt(mindmap_text="SAVED MAP", mindmap_status="done")
    await client.post(f"{URL}/mindmap", params={"force": "true"})
    assert (await fmt_row())["mindmap_status"] == "processing" and len(await _items()) == 1
    assert (await client.delete(f"{URL}/mindmap")).json() == {"status": "cancelling"}
    assert await _items() == []                                   # it never started: gone from the queue
    row = await fmt_row()
    assert row["mindmap_status"] is None and row["mindmap_text"] == "SAVED MAP"
    assert VIDEO_ID not in MINDMAP_CANCEL                         # and no flag is left to stop a later run


async def test_stop_with_nothing_running_is_harmless_and_leaves_no_stale_flag(client, seeded_video):
    assert (await client.delete(f"{URL}/mindmap")).json() == {"status": "cancelling"}
    assert VIDEO_ID not in MINDMAP_CANCEL
    gate = Gate(result="# Later")
    gate.release.set()
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        await client.post(f"{URL}/mindmap")
        await run_worker([(await _items())[0]["id"]])
    assert (await fmt_row())["mindmap_status"] == "done"


async def test_stop_on_a_running_mind_map_sets_the_flag_the_stage_polls(client, seeded_video):
    gate = Gate(result="# Map")
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        await client.post(f"{URL}/mindmap")
        item = (await _items())[0]
        worker = asyncio.create_task(run_worker([item["id"]]))
        await gate.wait_started()
        await client.delete(f"{URL}/mindmap")
        assert VIDEO_ID in MINDMAP_CANCEL and gate.calls[0]["is_cancelled"]() is True
        gate.release.set()
        await worker
    assert (await get_item(item["id"]))["status"] == "skipped"
    assert (await fmt_row())["mindmap_status"] is None


# --- decision 5 and the rest -------------------------------------------------------------------

async def test_a_mind_map_for_a_local_file_goes_through_the_queue(client, db_session):
    from models.models import SubtitleFormatted, Video
    video = Video(url="local://talk.m4a", video_id="file-mm000001", title="talk.m4a", duration=30)
    db_session.add(video)
    await db_session.flush()
    db_session.add(SubtitleFormatted(video_id=video.id, language="en", subtitle_source="transcript",
                                     formatted_text="Hello there.\n\nA local recording.", text_length=30,
                                     processing_status="success"))
    await db_session.commit()
    try:
        r = await client.post("/api/result/file-mm000001/mindmap")
        assert r.json() == {"status": "processing"}
        item = (await _items("file-mm000001"))[0]
        assert item["url"] == "local://talk.m4a" and item["pipeline_stages"] == ["mindmap"]
        gate = Gate(result="# Local")
        gate.release.set()
        with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
            await run_worker([item["id"]])
        assert (await fmt_row("file-mm000001"))["mindmap_text"] == "# Local"
    finally:
        await db_session.execute(text("DELETE FROM subtitles_formatted WHERE video_id = :v"), {"v": video.id})
        await db_session.execute(text("DELETE FROM videos WHERE id = :v"), {"v": video.id})
        await db_session.commit()


async def test_a_locked_database_while_queueing_gives_503_and_no_half_state(client, seeded_video, monkeypatch):
    from services import queue_by_id
    from sqlalchemy.exc import OperationalError
    import sqlite3

    async def always_locked(*a, **k):
        raise OperationalError("INSERT", {}, sqlite3.OperationalError("database is locked"))

    monkeypatch.setattr(queue_by_id, "enqueue_stage", always_locked)
    async def no_sleep(_s):
        return None
    monkeypatch.setattr("services.db_retry.asyncio.sleep", no_sleep)
    r = await client.post(f"{URL}/mindmap")
    assert r.status_code == 503 and r.json() == {"detail": "database busy, try again"}
    assert (await fmt_row())["mindmap_status"] is None and await _items() == []   # nothing was changed
