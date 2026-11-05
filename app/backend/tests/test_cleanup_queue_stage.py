"""NS-11 stage 4a: the queue copy of the cleanup stage behaves like the background copy did (cancel, progress)."""
import asyncio
from unittest.mock import patch

import pytest
import pytest_asyncio

from services import queue_service as q
from services.stage_control import CLEANUP_CANCEL, StageCancelled
from tests.baseline_helpers import (
    Gate, VIDEO_ID, add_item, benchmark_rows, fmt_row, get_item, reset_benchmarks, reset_queue, run_worker, set_fmt,
)

URL = f"/api/result/{VIDEO_ID}"


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    CLEANUP_CANCEL.clear()
    await reset_queue()
    await reset_benchmarks()
    await client.put("/api/settings/cleanup", json={"model": "m-clean"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    CLEANUP_CANCEL.clear()
    await reset_queue()


def test_the_cancel_set_is_shared_with_the_result_router():
    from routers import result as r
    assert r._CANCEL_SET is CLEANUP_CANCEL


async def test_the_result_page_sees_the_paragraph_counters_of_a_queue_run_and_they_go_away_after(client, seeded_video):
    gate = Gate(result="Cleaned.", progress=(2, 3))
    with patch("services.text_cleaner.clean_text", gate.llm()):
        task = asyncio.create_task(q._run_cleanup_stage(VIDEO_ID, 3))
        await gate.wait_started()
        for _ in range(100):                                   # the counters are written a moment after the callback
            data = (await client.get(URL)).json()
            if data.get("cleanup_paragraphs_done") is not None:
                break
            await asyncio.sleep(0.02)
        assert data["cleanup_status"] == "processing"
        assert data["cleanup_paragraphs_done"] == 2 and data["cleanup_paragraphs_total"] == 3   # what the page polls
        from models.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            assert (await q._live_progress(db, [3])) == {3: "cleanup: paragraph 2/3"}                                  # and the queue page
        gate.release.set()
        await task
    data = (await client.get(URL)).json()
    assert "cleanup_paragraphs_done" not in data           # the run is over: no live counters


async def test_the_counters_are_removed_when_the_stage_fails_too(client, seeded_video):
    async def boom(*a, **k):
        k["on_progress"](1, 3)
        raise RuntimeError("llm exploded")

    with patch("services.text_cleaner.clean_text", boom):
        with pytest.raises(RuntimeError):
            await q._run_cleanup_stage(VIDEO_ID, 1)
    data = (await client.get(URL)).json()
    assert "cleanup_paragraphs_done" not in data and data["stages"]["cleanup"]["status"] in ("failed", "cancelled")


async def test_stop_during_cleanup_resets_the_status_and_keeps_the_previous_cleaned_text(seeded_video):
    await set_fmt(cleaned_text="OLD CLEANED", cleanup_status="done", cleanup_model="old")
    gate = Gate(result="NEW CLEANED")
    with patch("services.text_cleaner.clean_text", gate.llm()):
        task = asyncio.create_task(q._run_cleanup_stage(VIDEO_ID, 5))
        await gate.wait_started()
        assert (await fmt_row())["cleanup_status"] == "processing"
        assert gate.calls[0]["is_cancelled"]() is False
        CLEANUP_CANCEL.add(VIDEO_ID)                         # what DELETE /api/result/<id>/cleanup does
        assert gate.calls[0]["is_cancelled"]() is True       # the running LLM call sees it
        gate.release.set()
        with pytest.raises(StageCancelled):
            await task
    row = await fmt_row()
    assert row["cleanup_status"] is None and row["cleaned_text"] == "OLD CLEANED"       # as in the background copy
    assert VIDEO_ID not in CLEANUP_CANCEL and await benchmark_rows("cleanup") == []      # flag used up, no benchmark row


async def test_a_cancelled_queue_item_ends_skipped_with_a_message(seeded_video):
    gate = Gate(result="NEW")
    item = await add_item(["cleanup"])
    with patch("services.text_cleaner.clean_text", gate.llm()):
        worker = asyncio.create_task(run_worker([item]))
        await gate.wait_started()
        CLEANUP_CANCEL.add(VIDEO_ID)
        gate.release.set()
        await worker
    row = await get_item(item)
    assert row["status"] == "skipped" and row["error_message"] == "Cleanup cancelled" and row["progress"] is None
    assert (await fmt_row())["cleanup_status"] is None


async def test_the_real_clean_text_stops_between_paragraphs_when_the_flag_is_set(seeded_video):
    """End to end through text_cleaner: paragraphs after the flag are not sent to the model."""
    import httpx
    import respx
    sent = []
    await set_fmt(formatted_text="\n\n".join(f"Абзац номер {i}." for i in range(6)))

    def handler(request):
        import json
        sent.append(json.loads(request.content)["messages"][-1]["content"])
        if len(sent) == 2:
            CLEANUP_CANCEL.add(VIDEO_ID)                      # Stop pressed while the 2nd paragraph is out
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Чисто."}, "done": True})

    with respx.mock:
        respx.get("http://localhost:11434/api/tags").mock(return_value=httpx.Response(200, json={"models": []}))
        respx.post("http://localhost:11434/api/chat").mock(side_effect=handler)
        with pytest.raises(StageCancelled):
            await q._run_cleanup_stage(VIDEO_ID, 1)
    assert len(sent) == 2                                     # 4 paragraphs were never sent
    assert (await fmt_row())["cleanup_status"] is None


async def test_a_flag_left_over_from_an_earlier_run_does_not_stop_a_new_run(seeded_video):
    CLEANUP_CANCEL.add(VIDEO_ID)
    gate = Gate(result="Fresh.")
    gate.release.set()
    with patch("services.text_cleaner.clean_text", gate.llm()):
        await q._run_cleanup_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["cleanup_status"] == "done" and row["cleaned_text"] == "Fresh."


async def test_cancelling_one_video_does_not_touch_another(seeded_video):
    CLEANUP_CANCEL.add("someOtherVid1")
    gate = Gate(result="Mine.")
    gate.release.set()
    with patch("services.text_cleaner.clean_text", gate.llm()):
        await q._run_cleanup_stage(VIDEO_ID, 1)
    assert (await fmt_row())["cleanup_status"] == "done" and "someOtherVid1" in CLEANUP_CANCEL


async def test_the_next_queue_item_still_runs_after_a_cancelled_one(seeded_video):
    gate = Gate(result="Cleaned.")
    first = await add_item(["cleanup"])
    second = await add_item(["cleanup"])
    with patch("services.text_cleaner.clean_text", gate.llm()):
        worker = asyncio.create_task(run_worker([first, second]))
        await gate.wait_started()
        CLEANUP_CANCEL.add(VIDEO_ID)
        gate.release.set()
        await worker
    assert (await get_item(first))["status"] == "skipped" and (await get_item(second))["status"] == "done"
    assert (await fmt_row())["cleanup_status"] == "done"
