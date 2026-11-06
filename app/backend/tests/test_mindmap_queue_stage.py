"""NS-11 stage 2: the queue copy of the mind map stage behaves like the background copy did (cancel, saved text)."""
import asyncio
from unittest.mock import patch

import pytest
import pytest_asyncio

from services import queue_service as q
from services.stage_control import MINDMAP_CANCEL, StageCancelled
from tests.baseline_helpers import Gate, VIDEO_ID, add_item, fmt_row, get_item, reset_queue, run_worker, set_fmt


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    MINDMAP_CANCEL.clear()
    await reset_queue()
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    MINDMAP_CANCEL.clear()
    await reset_queue()


def test_the_cancel_set_is_one_object_shared_with_the_result_router():
    from routers import result_stages as r
    assert r._MINDMAP_CANCEL_SET is MINDMAP_CANCEL


async def test_stop_during_generation_resets_the_status_and_keeps_the_saved_map(seeded_video):
    await set_fmt(mindmap_text="OLD MAP", mindmap_status="done")
    gate = Gate(result="NEW MAP")
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        task = asyncio.create_task(q._run_mindmap_stage(VIDEO_ID, 5))
        await gate.wait_started()
        assert (await fmt_row())["mindmap_status"] == "processing"
        assert gate.calls[0]["is_cancelled"]() is False
        MINDMAP_CANCEL.add(VIDEO_ID)                      # what DELETE /api/result/<id>/mindmap does
        assert gate.calls[0]["is_cancelled"]() is True     # the running LLM call sees it
        gate.release.set()
        with pytest.raises(StageCancelled):
            await task
    row = await fmt_row()
    assert row["mindmap_status"] is None and row["mindmap_text"] == "OLD MAP"   # as in the background copy
    assert VIDEO_ID not in MINDMAP_CANCEL                                       # the flag is used up


async def test_a_cancelled_queue_item_ends_skipped_with_a_message_not_done_or_failed(seeded_video):
    gate = Gate(result="NEW MAP")
    item = await add_item(["mindmap"])
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        worker = asyncio.create_task(run_worker([item]))
        await gate.wait_started()
        MINDMAP_CANCEL.add(VIDEO_ID)
        gate.release.set()
        await worker
    row = await get_item(item)
    assert row["status"] == "skipped" and row["error_message"] == "Mind map cancelled"
    assert row["finished_at"] is not None and row["progress"] is None
    assert (await fmt_row())["mindmap_status"] is None


async def test_a_flag_left_over_from_an_earlier_run_does_not_stop_a_new_run(seeded_video):
    MINDMAP_CANCEL.add(VIDEO_ID)                          # stale: nothing was running when it was set
    gate = Gate(result="# Fresh")
    gate.release.set()
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        await q._run_mindmap_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["mindmap_status"] == "done" and row["mindmap_text"] == "# Fresh"


async def test_cancelling_one_video_does_not_touch_another(seeded_video):
    MINDMAP_CANCEL.add("someOtherVid1")
    gate = Gate(result="# Mine")
    gate.release.set()
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        await q._run_mindmap_stage(VIDEO_ID, 1)
    assert (await fmt_row())["mindmap_status"] == "done"
    assert "someOtherVid1" in MINDMAP_CANCEL


async def test_the_next_queue_item_still_runs_after_a_cancelled_one(seeded_video):
    gate = Gate(result="# Map")
    first = await add_item(["mindmap"])
    second = await add_item(["mindmap"])
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        worker = asyncio.create_task(run_worker([first, second]))
        await gate.wait_started()
        MINDMAP_CANCEL.add(VIDEO_ID)
        gate.release.set()
        await worker
    assert (await get_item(first))["status"] == "skipped"
    assert (await get_item(second))["status"] == "done"   # the worker went on; the flag was used up by the first
    assert (await fmt_row())["mindmap_status"] == "done"
