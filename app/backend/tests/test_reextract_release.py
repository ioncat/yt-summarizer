"""NS-11 stage 6: a re-extract's run is never left 'processing' without an owner (Remove, Clear pending, restart)."""
import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import queue_service as q
from tests.baseline_helpers import VIDEO_ID, fmt_row, reset_queue, run_reextract_items
from tests.test_baseline_reextract import LOCAL_ID, local_video, stt, yt, youtube_video  # noqa: F401
from tests.test_reextract_queue import items_of, runs_of


@pytest.fixture(autouse=True)
async def _clean(client):
    await reset_queue()
    yield
    await reset_queue()


async def _in_progress(client, video_id):
    return bool((await client.get(f"/api/result/{video_id}")).json().get("reextract_in_progress"))


async def test_removing_a_queued_reextract_cancels_its_run_and_frees_the_page(client, local_video):
    await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    (item,) = await items_of(client, LOCAL_ID)
    assert await _in_progress(client, LOCAL_ID)
    assert (await client.delete(f"/api/queue/{item['id']}")).status_code == 200
    (run,) = await runs_of(LOCAL_ID, "transcribe")
    assert (run["status"], run["error_code"]) == ("cancelled", "cancelled")
    assert not await _in_progress(client, LOCAL_ID)
    assert (await fmt_row(LOCAL_ID))["formatted_text"] == "OLD TRANSCRIPT"


async def test_clear_pending_cancels_the_runs_of_every_queued_reextract(client, local_video, youtube_video):
    await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    await client.post(f"/api/result/{VIDEO_ID}/reextract", json={})
    assert (await client.delete("/api/queue/all")).json()["cleared"] == 2
    assert [r["status"] for r in await runs_of(LOCAL_ID, "transcribe")] == ["cancelled"]
    assert [r["status"] for r in await runs_of(VIDEO_ID, "extract")] == ["cancelled"]
    assert not await _in_progress(client, LOCAL_ID) and not await _in_progress(client, VIDEO_ID)


async def test_removing_another_item_leaves_the_reextract_alone(client, local_video):
    await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    async with AsyncSessionLocal() as db:
        other = (await db.execute(
            text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order) "
                 "VALUES ('https://www.youtube.com/watch?v=otherVideo01', 'otherVideo01', 'pending', '[\"extract\"]', datetime('now'), 99)"))).lastrowid
        await db.commit()
    assert (await client.delete(f"/api/queue/{other}")).status_code == 200
    assert [r["status"] for r in await runs_of(LOCAL_ID, "transcribe")] == ["processing"] and await _in_progress(client, LOCAL_ID)


async def test_removing_a_finished_reextract_item_does_not_touch_its_run(client, local_video):
    with patch("services.transcriber.transcribe", stt()):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        (item,) = await run_reextract_items(LOCAL_ID)
    assert (await client.delete(f"/api/queue/{item['id']}")).status_code == 200
    assert [r["status"] for r in await runs_of(LOCAL_ID, "transcribe")] == ["done"]


async def test_a_restart_in_the_middle_runs_the_reextract_again_to_the_end(client, local_video):
    """The backend restarts while the item is processing: it goes back to pending, the open run is closed as a restart, the page still
    shows "in progress" (the item is queued), and the worker finishes the job."""
    import main
    with patch("services.transcriber.transcribe", stt()):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        (item,) = await items_of(client, LOCAL_ID)
        await q._set_processing(item["id"])                 # the worker had taken it ...
        await q._reset_stuck_items()                         # ... and the backend restarted
        await main._reset_stale_statuses()
        (stale,) = await runs_of(LOCAL_ID, "transcribe")
        assert stale["status"] == "cancelled" and json.loads(stale["meta"]) == {"reason": "restart"}
        assert await _in_progress(client, LOCAL_ID)
        (done,) = await run_reextract_items(LOCAL_ID)
    assert done["status"] == "done"
    assert [(r["attempt"], r["status"]) for r in await runs_of(LOCAL_ID, "transcribe")] == [(1, "cancelled"), (2, "done")]
    assert "NEW TRANSCRIPT" in (await fmt_row(LOCAL_ID))["formatted_text"] and not await _in_progress(client, LOCAL_ID)
