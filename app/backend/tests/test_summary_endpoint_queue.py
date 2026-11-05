"""NS-11 stage 3: /api/result/{id}/summary queues the work. The owner's decisions, as tests."""
import asyncio
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import queue_service as q
from services.stage_control import SUMMARY_CANCEL, SUMMARY_PROGRESS
from tests.baseline_helpers import Gate, VIDEO_ID, add_item, fmt_row, get_item, reset_queue, run_worker, set_fmt

URL = f"/api/result/{VIDEO_ID}"


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    SUMMARY_CANCEL.clear()
    SUMMARY_PROGRESS.clear()
    await reset_queue()
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    SUMMARY_CANCEL.clear()
    SUMMARY_PROGRESS.clear()
    await reset_queue()


async def _items(video_id=VIDEO_ID):
    async with AsyncSessionLocal() as db:
        return [i for i in await q.get_queue(db) if i["video_id"] == video_id]


# --- decision 3: "processing" is set at once ------------------------------------------------------

async def test_the_status_is_processing_at_once_while_the_item_still_waits_in_the_queue(client, seeded_video):
    r = await client.post(f"{URL}/summary")
    assert r.json() == {"status": "processing"}
    row = await fmt_row()
    assert row["summary_status"] == "processing" and row["summary_model"] == "m-sum"   # nobody has started it yet
    items = await _items()
    assert len(items) == 1 and items[0]["status"] == "pending" and items[0]["pipeline_stages"] == ["summary"]
    assert (await client.get(URL)).json()["summary_status"] == "processing"            # what the result page polls


async def test_a_summary_waits_its_turn_behind_an_earlier_item(client, seeded_video):
    first = await add_item(["summary"], video_id="otherVideo01")
    await client.post(f"{URL}/summary")
    mine = (await _items())[0]
    assert mine["sort_order"] > (await get_item(first))["sort_order"]


async def test_the_run_through_the_queue_finishes_the_summary(client, seeded_video):
    gate = Gate(result=("Sum text.", "single", 1))
    gate.release.set()
    await client.post(f"{URL}/summary")
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        await run_worker([(await _items())[0]["id"]])
    row = await fmt_row()
    assert row["summary_status"] == "done" and row["summary_text"] == "Sum text."


# --- one item, not two --------------------------------------------------------------------------------

async def test_clicking_twice_queues_one_item(client, seeded_video):
    await client.post(f"{URL}/summary")
    await client.post(f"{URL}/summary")
    assert len(await _items()) == 1


async def test_clicks_at_the_same_moment_queue_one_item(client, seeded_video):
    await asyncio.gather(*(client.post(f"{URL}/summary") for _ in range(5)))
    assert len(await _items()) == 1


async def test_an_item_for_other_stages_does_not_stand_in_for_the_summary(client, seeded_video):
    await add_item(["cleanup"])
    await client.post(f"{URL}/summary")
    assert sorted(i["pipeline_stages"] for i in await _items()) == [["cleanup"], ["summary"]]


async def test_an_item_that_already_includes_the_summary_stage_stands_in_for_it(client, seeded_video):
    await add_item(["cleanup", "summary"])
    r = await client.post(f"{URL}/summary")
    assert r.json() == {"status": "processing"} and len(await _items()) == 1
    assert (await fmt_row())["summary_status"] == "processing"


async def test_a_summary_and_a_mind_map_requested_together_are_two_items(client, seeded_video):
    await client.post(f"{URL}/summary")
    await client.post(f"{URL}/mindmap")
    assert sorted(i["pipeline_stages"] for i in await _items()) == [["mindmap"], ["summary"]]


async def test_a_finished_item_does_not_block_a_new_summary(client, seeded_video):
    await client.post(f"{URL}/summary")
    gate = Gate(result=("S", "single", 1))
    gate.release.set()
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        await run_worker([(await _items())[0]["id"]])
    await client.post(f"{URL}/summary")                       # "Re-run summary": the old summary is replaced when it ends
    assert sorted(i["status"] for i in await _items()) == ["done", "pending"]


# --- refusals change nothing --------------------------------------------------------------------------

async def test_refused_requests_queue_nothing_and_leave_the_status_alone(client, seeded_video):
    await client.put("/api/settings/summarization", json={"model": None})
    assert (await client.post(f"{URL}/summary")).status_code == 400
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    assert (await client.post("/api/result/nope-nope/summary")).status_code == 404
    assert await _items() == [] and (await fmt_row())["summary_status"] is None


async def test_a_locked_database_while_queueing_gives_503_and_nothing_changed(client, seeded_video, monkeypatch):
    from services import queue_by_id
    from sqlalchemy.exc import OperationalError
    import sqlite3

    async def always_locked(*a, **k):
        raise OperationalError("INSERT", {}, sqlite3.OperationalError("database is locked"))

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(queue_by_id, "enqueue_stage", always_locked)
    monkeypatch.setattr("services.db_retry.asyncio.sleep", no_sleep)
    r = await client.post(f"{URL}/summary")
    assert r.status_code == 503 and r.json() == {"detail": "database busy, try again"}
    assert (await fmt_row())["summary_status"] is None and await _items() == []


# --- decision 1: cancel as in the background copy ---------------------------------------------------

async def test_stop_on_a_queued_summary_takes_it_out_and_resets_the_status_keeping_the_previous_summary(client, seeded_video):
    await set_fmt(summary_text="OLD SUMMARY", summary_status="done", summary_model="old")
    await client.post(f"{URL}/summary")
    assert (await fmt_row())["summary_status"] == "processing" and len(await _items()) == 1
    assert (await client.delete(f"{URL}/summary")).json() == {"status": "cancelling"}
    assert await _items() == []                                # it never started: gone from the queue
    row = await fmt_row()
    assert row["summary_status"] is None and row["summary_text"] == "OLD SUMMARY"
    assert VIDEO_ID not in SUMMARY_CANCEL                      # and no flag is left to stop a later run


async def test_stop_with_nothing_running_is_harmless_and_leaves_no_stale_flag(client, seeded_video):
    assert (await client.delete(f"{URL}/summary")).json() == {"status": "cancelling"}
    assert VIDEO_ID not in SUMMARY_CANCEL
    gate = Gate(result=("Later.", "single", 1))
    gate.release.set()
    await client.post(f"{URL}/summary")
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        await run_worker([(await _items())[0]["id"]])
    assert (await fmt_row())["summary_status"] == "done"


async def test_stop_on_a_running_summary_sets_the_flag_the_stage_polls(client, seeded_video):
    gate = Gate(result=("S", "single", 1))
    await client.post(f"{URL}/summary")
    item = (await _items())[0]
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        worker = asyncio.create_task(run_worker([item["id"]]))
        await gate.wait_started()
        await client.delete(f"{URL}/summary")
        assert VIDEO_ID in SUMMARY_CANCEL and gate.calls[0]["is_cancelled"]() is True
        gate.release.set()
        await worker
    assert (await get_item(item["id"]))["status"] == "skipped"
    assert (await fmt_row())["summary_status"] is None


# --- local files ---------------------------------------------------------------------------------------

async def test_a_summary_for_a_local_file_goes_through_the_queue(client, db_session):
    from models.models import SubtitleFormatted, Video
    video = Video(url="local://talk.m4a", video_id="file-sm000001", title="talk.m4a", duration=30)
    db_session.add(video)
    await db_session.flush()
    db_session.add(SubtitleFormatted(video_id=video.id, language="en", subtitle_source="transcript",
                                     formatted_text="Hello there.\n\nA local recording.", text_length=30,
                                     processing_status="success"))
    await db_session.commit()
    try:
        r = await client.post("/api/result/file-sm000001/summary")
        assert r.json() == {"status": "processing"}
        item = (await _items("file-sm000001"))[0]
        assert item["url"] == "local://talk.m4a" and item["pipeline_stages"] == ["summary"]
        gate = Gate(result=("Local summary.", "single", 1))
        gate.release.set()
        with patch("services.text_summarizer.summarize_text", gate.llm()):
            await run_worker([item["id"]])
        assert (await fmt_row("file-sm000001"))["summary_text"] == "Local summary."
    finally:
        await db_session.execute(text("DELETE FROM benchmark_runs WHERE video_id = 'file-sm000001'"))
        await db_session.execute(text("DELETE FROM subtitles_formatted WHERE video_id = :v"), {"v": video.id})
        await db_session.execute(text("DELETE FROM videos WHERE id = :v"), {"v": video.id})
        await db_session.commit()
