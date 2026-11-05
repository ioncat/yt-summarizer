"""NS-11 stage 3: the queue copy of the summary stage behaves like the background copy did (cancel, progress)."""
import asyncio
from unittest.mock import patch

import pytest
import pytest_asyncio

from services import queue_service as q
from services.stage_control import SUMMARY_CANCEL, SUMMARY_PROGRESS, StageCancelled
from tests.baseline_helpers import (
    Gate, VIDEO_ID, add_item, benchmark_rows, fmt_row, get_item, reset_benchmarks, reset_queue, run_worker, set_fmt,
)

URL = f"/api/result/{VIDEO_ID}"


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    SUMMARY_CANCEL.clear()
    SUMMARY_PROGRESS.clear()
    await reset_queue()
    await reset_benchmarks()
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    SUMMARY_CANCEL.clear()
    SUMMARY_PROGRESS.clear()
    await reset_queue()


def test_the_cancel_set_and_the_progress_dict_are_shared_with_the_result_router():
    from routers import result as r
    assert r._SUMMARY_CANCEL_SET is SUMMARY_CANCEL and r._SUMMARY_PROGRESS is SUMMARY_PROGRESS


async def test_the_result_page_sees_the_chunk_counters_of_a_queue_run_and_they_go_away_after(client, seeded_video):
    gate = Gate(result=("Sum.", "map_reduce", 4), progress=(2, 5))
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        task = asyncio.create_task(q._run_summary_stage(VIDEO_ID, 3))
        await gate.wait_started()
        data = (await client.get(URL)).json()
        assert data["summary_status"] == "processing"
        assert data["summary_chunks_done"] == 2 and data["summary_chunks_total"] == 5     # what the page polls
        assert q._QUEUE_PROGRESS[3] == "summary: chunk 2/5"                               # and what the queue page shows
        gate.release.set()
        await task
    data = (await client.get(URL)).json()
    assert "summary_chunks_done" not in data and VIDEO_ID not in SUMMARY_PROGRESS


async def test_the_counters_are_removed_when_the_stage_fails_or_is_cancelled_too(seeded_video):
    async def boom(*a, **k):
        k["on_progress"](1, 3)
        raise RuntimeError("llm exploded")

    with patch("services.text_summarizer.summarize_text", boom):
        with pytest.raises(RuntimeError):
            await q._run_summary_stage(VIDEO_ID, 1)
    assert VIDEO_ID not in SUMMARY_PROGRESS


async def test_stop_during_generation_resets_the_status_and_keeps_the_previous_summary(seeded_video):
    await set_fmt(summary_text="OLD SUMMARY", summary_status="done", summary_model="old", summary_mode="single")
    gate = Gate(result=("NEW", "single", 1))
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        task = asyncio.create_task(q._run_summary_stage(VIDEO_ID, 5))
        await gate.wait_started()
        assert (await fmt_row())["summary_status"] == "processing"
        assert gate.calls[0]["is_cancelled"]() is False
        SUMMARY_CANCEL.add(VIDEO_ID)                       # what DELETE /api/result/<id>/summary does
        assert gate.calls[0]["is_cancelled"]() is True     # the running LLM call sees it
        gate.release.set()
        with pytest.raises(StageCancelled):
            await task
    row = await fmt_row()
    assert row["summary_status"] is None and row["summary_text"] == "OLD SUMMARY"      # as in the background copy
    assert VIDEO_ID not in SUMMARY_CANCEL and await benchmark_rows("summary") == []     # flag used up, no benchmark row


async def test_stop_reaches_the_full_extract_path_too(seeded_video):
    from services.text_summarizer import MAP_REDUCE_THRESHOLD
    from sqlalchemy import text
    from models.database import AsyncSessionLocal
    await set_fmt(formatted_text="x" * (MAP_REDUCE_THRESHOLD + 10))
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE videos SET chapters = :c WHERE video_id = :v"),
                         {"c": '[{"start_time": 0, "end_time": 5, "title": "A"}]', "v": VIDEO_ID})
        await db.commit()
    gate = Gate(result=("Notes", "full_extract", 3))
    with patch("services.text_summarizer.extract_notes", gate.llm()):
        task = asyncio.create_task(q._run_summary_stage(VIDEO_ID, 5))
        await gate.wait_started()
        SUMMARY_CANCEL.add(VIDEO_ID)
        assert gate.calls[0]["is_cancelled"]() is True
        gate.release.set()
        with pytest.raises(StageCancelled):
            await task
    assert (await fmt_row())["summary_status"] is None


async def test_a_cancelled_queue_item_ends_skipped_with_a_message(seeded_video):
    gate = Gate(result=("NEW", "single", 1))
    item = await add_item(["summary"])
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        worker = asyncio.create_task(run_worker([item]))
        await gate.wait_started()
        SUMMARY_CANCEL.add(VIDEO_ID)
        gate.release.set()
        await worker
    row = await get_item(item)
    assert row["status"] == "skipped" and row["error_message"] == "Summary cancelled" and row["progress"] is None
    assert (await fmt_row())["summary_status"] is None


async def test_a_flag_left_over_from_an_earlier_run_does_not_stop_a_new_run(seeded_video):
    SUMMARY_CANCEL.add(VIDEO_ID)                           # stale: nothing was running when it was set
    gate = Gate(result=("Fresh.", "single", 1))
    gate.release.set()
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        await q._run_summary_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["summary_status"] == "done" and row["summary_text"] == "Fresh."


async def test_cancelling_one_video_does_not_touch_another(seeded_video):
    SUMMARY_CANCEL.add("someOtherVid1")
    gate = Gate(result=("Mine.", "single", 1))
    gate.release.set()
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        await q._run_summary_stage(VIDEO_ID, 1)
    assert (await fmt_row())["summary_status"] == "done" and "someOtherVid1" in SUMMARY_CANCEL


async def test_the_next_queue_item_still_runs_after_a_cancelled_one(seeded_video):
    gate = Gate(result=("Sum.", "single", 1))
    first = await add_item(["summary"])
    second = await add_item(["summary"])
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        worker = asyncio.create_task(run_worker([first, second]))
        await gate.wait_started()
        SUMMARY_CANCEL.add(VIDEO_ID)
        gate.release.set()
        await worker
    assert (await get_item(first))["status"] == "skipped" and (await get_item(second))["status"] == "done"
    assert (await fmt_row())["summary_status"] == "done"
