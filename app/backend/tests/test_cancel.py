"""NS-16: one cancel path. POST /api/queue/{id}/cancel (the Queue page's button) and POST /api/result/{id}/cancel (the result
page's Stop) both go through services/cancel.py: a waiting item leaves the queue, a running item is told to stop and ends
`skipped` with its run `cancelled`."""
import asyncio
import threading
from unittest.mock import patch

import pytest
import pytest_asyncio

from services import queue_service as q
from services.stage_control import (
    CLEANUP_CANCEL, ITEM_CANCEL, MINDMAP_CANCEL, SUMMARY_CANCEL, TRANSCRIBE_CANCEL,
)
from tests.baseline_helpers import Gate, VIDEO_ID, add_item, fmt_row, get_item, reset_queue, run_worker, set_fmt
from tests.test_baseline_reextract import LOCAL_ID, local_video, stt, yt, youtube_video  # noqa: F401
from tests.test_reextract_stop import endless


def _clear():
    for s in (CLEANUP_CANCEL, SUMMARY_CANCEL, MINDMAP_CANCEL, TRANSCRIBE_CANCEL, ITEM_CANCEL):
        s.clear()


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    _clear()
    await reset_queue()
    await client.put("/api/settings/cleanup", json={"model": "m-clean"})
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    _clear()
    await reset_queue()


# --- a waiting item ------------------------------------------------------------------------------------------------------------

async def test_cancel_of_a_waiting_item_removes_it_and_gives_the_status_back(client, seeded_video):
    item = await add_item(["cleanup"])
    await set_fmt(cleanup_status="processing")                     # what the cleanup button sets at once
    r = await client.post(f"/api/queue/{item}/cancel")
    assert r.status_code == 200 and r.json() == {"status": "removed", "id": item}
    assert (await client.get("/api/queue")).json()["count"] == 0
    assert (await fmt_row())["cleanup_status"] is None


async def test_cancel_of_an_unknown_item_is_404_and_of_a_finished_one_409(client, seeded_video):
    assert (await client.post("/api/queue/987654/cancel")).status_code == 404
    item = await add_item(["cleanup"])
    gate = Gate(result="NEW")
    gate.release.set()
    with patch("services.text_cleaner.clean_text", gate.llm()):
        await run_worker([item])
    assert (await get_item(item))["status"] == "done"
    r = await client.post(f"/api/queue/{item}/cancel")
    assert r.status_code == 409
    assert (await client.get("/api/queue")).json()["count"] == 1     # a finished row is not touched


# --- a running item, every stage -----------------------------------------------------------------------------------------------

STAGES = {
    "cleanup": ("services.text_cleaner.clean_text", "NEW", "cleanup_status", CLEANUP_CANCEL),
    "summary": ("services.text_summarizer.summarize_text", ("NEW", "single", 1), "summary_status", SUMMARY_CANCEL),
    "mindmap": ("services.text_mindmapper.generate_mindmap", "NEW MAP", "mindmap_status", MINDMAP_CANCEL),
}


@pytest.mark.parametrize("stage", list(STAGES))
async def test_cancel_of_a_running_item_stops_its_stage_and_ends_it_skipped(client, seeded_video, stage):
    target, result, status_col, flags = STAGES[stage]
    gate = Gate(result=result)
    item = await add_item([stage])
    with patch(target, gate.llm()):
        worker = asyncio.create_task(run_worker([item]))
        await gate.wait_started()
        assert gate.calls[0]["is_cancelled"]() is False
        r = await client.post(f"/api/queue/{item}/cancel")
        assert r.status_code == 200 and r.json()["status"] == "stopping"
        assert gate.calls[0]["is_cancelled"]() is True               # the running LLM call sees it
        gate.release.set()
        await worker
    row = await get_item(item)
    assert row["status"] == "skipped" and "cancelled" in row["error_message"].lower()
    assert (await fmt_row())[status_col] is None
    shown = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert shown["stages"][stage]["status"] == "cancelled"
    assert not ITEM_CANCEL and VIDEO_ID not in flags                 # nothing is left over for the next run


async def test_cancel_of_a_running_multi_stage_item_gives_the_stages_that_never_ran_back(client, seeded_video):
    gate = Gate(result="NEW")
    item = await add_item(["cleanup", "summary"])
    await set_fmt(cleanup_status="processing", summary_status="processing")    # both were marked when the item was queued
    with patch("services.text_cleaner.clean_text", gate.llm()):
        worker = asyncio.create_task(run_worker([item]))
        await gate.wait_started()
        assert (await client.post(f"/api/queue/{item}/cancel")).json()["status"] == "stopping"
        gate.release.set()
        await worker
    row = await fmt_row()
    assert row["cleanup_status"] is None and row["summary_status"] is None     # the summary did not stay "processing"
    assert (await get_item(item))["status"] == "skipped"


async def test_a_stop_during_a_step_that_cannot_be_cut_short_ends_the_item_before_the_next_stage(client, seeded_video):
    """yt-dlp cannot be interrupted: the Stop is kept on the item and checked when the step returns."""
    ran = []

    async def slow_extract(url, language="auto"):
        item_id = (await client.get("/api/queue")).json()["items"][0]["id"]
        assert (await client.post(f"/api/queue/{item_id}/cancel")).json()["status"] == "stopping"
        return {"video_id": VIDEO_ID, "db_video_id": None}

    async def cleanup(*a, **k):
        ran.append("cleanup")
        return "NEW"

    item = await add_item(["extract", "cleanup"])
    await set_fmt(cleanup_status="processing")
    with patch.object(q, "_run_extract", slow_extract), patch("services.text_cleaner.clean_text", cleanup):
        await run_worker([item])
    assert ran == []                                                   # the cleanup never started
    assert (await get_item(item))["status"] == "skipped"
    assert (await fmt_row())["cleanup_status"] is None and not ITEM_CANCEL


async def test_a_stop_flag_left_for_an_item_does_not_stop_the_next_run_of_the_same_id(client, seeded_video):
    item = await add_item(["cleanup"])
    ITEM_CANCEL.add(item)                                               # e.g. a Stop that came after the last stage
    gate = Gate(result="FRESH")
    gate.release.set()
    with patch("services.text_cleaner.clean_text", gate.llm()):
        await run_worker([item])
    assert (await get_item(item))["status"] == "done" and not ITEM_CANCEL


# --- an uploaded / re-extracted file --------------------------------------------------------------------------------------------

async def test_cancel_of_a_running_retranscription_replaces_nothing(client, local_video):
    started = threading.Event()
    with patch("services.transcriber.transcribe", endless(started)):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        from tests.baseline_helpers import run_reextract_items
        worker = asyncio.create_task(run_reextract_items(LOCAL_ID))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        item_id = (await client.get("/api/queue")).json()["items"][0]["id"]
        r = await client.post(f"/api/queue/{item_id}/cancel")
        assert r.json()["status"] == "stopping"
        (item,) = await worker
    assert item["status"] == "skipped"
    assert (await fmt_row(LOCAL_ID))["formatted_text"] == "OLD TRANSCRIPT"
    assert LOCAL_ID not in TRANSCRIBE_CANCEL


async def test_cancel_of_a_waiting_retranscription_removes_it_and_cancels_its_run(client, local_video):
    await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    item_id = (await client.get("/api/queue")).json()["items"][0]["id"]
    assert (await client.post(f"/api/queue/{item_id}/cancel")).json()["status"] == "removed"
    assert (await client.get("/api/queue")).json()["count"] == 0
    assert (await client.get(f"/api/result/{LOCAL_ID}")).json().get("reextract_in_progress") is None


# --- the result page's Stop ----------------------------------------------------------------------------------------------------

async def test_the_result_page_stop_cancels_every_waiting_job_of_the_video(client, seeded_video):
    assert (await client.post(f"/api/result/{VIDEO_ID}/cleanup")).status_code == 200
    assert (await client.post(f"/api/result/{VIDEO_ID}/summary")).status_code == 200
    assert (await client.get("/api/queue")).json()["count"] == 2
    r = await client.post(f"/api/result/{VIDEO_ID}/cancel")
    assert r.json() == {"status": "cancelling", "removed": 2, "stopping": 0}
    assert (await client.get("/api/queue")).json()["count"] == 0
    row = await fmt_row()
    assert row["cleanup_status"] is None and row["summary_status"] is None
    again = await client.post(f"/api/result/{VIDEO_ID}/cancel")          # nothing left: not an error (the job may have just ended)
    assert again.status_code == 200 and again.json() == {"status": "idle", "removed": 0, "stopping": 0}


async def test_the_result_page_stop_tells_the_running_job_to_stop_and_removes_the_waiting_one(client, seeded_video):
    gate = Gate(result="NEW")
    await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    item = (await client.get("/api/queue")).json()["items"][0]["id"]
    with patch("services.text_cleaner.clean_text", gate.llm()):
        worker = asyncio.create_task(run_worker([item]))
        await gate.wait_started()
        await client.post(f"/api/result/{VIDEO_ID}/summary")             # queued behind the running cleanup
        r = await client.post(f"/api/result/{VIDEO_ID}/cancel")
        assert r.json() == {"status": "cancelling", "removed": 1, "stopping": 1}
        assert gate.calls[0]["is_cancelled"]() is True
        gate.release.set()
        await worker
    assert (await get_item(item))["status"] == "skipped"
    row = await fmt_row()
    assert row["cleanup_status"] is None and row["summary_status"] is None


async def test_the_result_page_stop_leaves_other_videos_alone(client, seeded_video):
    other = await add_item(["cleanup"], video_id="someOtherVid1")
    await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    await client.post(f"/api/result/{VIDEO_ID}/cancel")
    assert [i["id"] for i in (await client.get("/api/queue")).json()["items"]] == [other]


# --- the old per-stage Stop endpoints are aliases of the same path (commit 2) -------------------------------------------------------

@pytest.mark.parametrize("stage", ["cleanup", "summary", "mindmap"])
async def test_the_per_stage_stop_removes_a_waiting_multi_stage_item_and_gives_every_status_back(client, seeded_video, stage):
    item = await add_item(["cleanup", "summary", "mindmap"])
    await set_fmt(cleanup_status="processing", summary_status="processing", mindmap_status="processing")
    r = await client.delete(f"/api/result/{VIDEO_ID}/{stage}")
    assert r.status_code == 200 and r.json() == {"status": "cancelling"}
    assert (await client.get("/api/queue")).json()["count"] == 0
    row = await fmt_row()
    assert (row["cleanup_status"], row["summary_status"], row["mindmap_status"]) == (None, None, None)


async def test_the_per_stage_stop_does_not_touch_an_item_without_that_stage(client, seeded_video):
    item = await add_item(["summary"])
    await client.delete(f"/api/result/{VIDEO_ID}/cleanup")
    assert [i["id"] for i in (await client.get("/api/queue")).json()["items"]] == [item]


async def test_the_per_stage_stop_of_a_running_stage_stops_it(client, seeded_video):
    gate = Gate(result="NEW")
    item = await add_item(["cleanup"])
    with patch("services.text_cleaner.clean_text", gate.llm()):
        worker = asyncio.create_task(run_worker([item]))
        await gate.wait_started()
        assert (await client.delete(f"/api/result/{VIDEO_ID}/cleanup")).json() == {"status": "cancelling"}
        assert gate.calls[0]["is_cancelled"]() is True
        gate.release.set()
        await worker
    assert (await get_item(item))["status"] == "skipped"
