"""NS-11 stage 5: an upload's task and run never stay 'processing' without an owner (Remove, Clear pending, restart)."""
import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import queue_service as q
from tests.baseline_helpers import reset_queue, run_worker
from tests.test_baseline_file_stt import _forget, _item, _upload, uploads  # noqa: F401
from tests.test_file_stt_queue import _forget_runs, _runs, ok


@pytest.fixture(autouse=True)
async def _clean(client):
    await reset_queue()
    yield
    await reset_queue()


async def _status(client, body):
    return (await client.get(f"/api/status/{body['task_id']}")).json()


async def _done(*bodies):
    for b in bodies:
        await _forget(b["video_id"])
        await _forget_runs(b["video_id"])


async def test_removing_a_queued_upload_ends_its_task_and_its_run(client, uploads):
    body = (await _upload(client)).json()
    item = await _item(client, body["video_id"])
    assert (await client.delete(f"/api/queue/{item['id']}")).status_code == 200
    st = await _status(client, body)
    assert st["status"] == "failed" and st["error_message"] == "Removed from the queue"
    (run,) = await _runs(body["video_id"])
    assert (run["status"], run["error_code"]) == ("cancelled", "cancelled")
    await _done(body)


async def test_clear_pending_ends_the_tasks_and_runs_of_every_queued_upload(client, uploads):
    first = (await _upload(client, name="a.m4a")).json()
    second = (await _upload(client, name="b.m4a")).json()
    assert (await client.delete("/api/queue/all")).json()["cleared"] == 2
    for body in (first, second):
        st = await _status(client, body)
        assert st["status"] == "failed" and st["error_message"] == "Removed from the queue"
        assert [r["status"] for r in await _runs(body["video_id"])] == ["cancelled"]
    await _done(first, second)


async def test_removing_another_item_leaves_the_uploads_alone(client, uploads):
    body = (await _upload(client)).json()
    async with AsyncSessionLocal() as db:
        other = (await db.execute(
            text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order) "
                 "VALUES ('https://www.youtube.com/watch?v=otherVideo01', 'otherVideo01', 'pending', '[\"extract\"]', datetime('now'), 99)"))).lastrowid
        await db.commit()
    assert (await client.delete(f"/api/queue/{other}")).status_code == 200
    assert (await _status(client, body))["status"] == "pending"
    assert [r["status"] for r in await _runs(body["video_id"])] == ["processing"]
    await _done(body)


async def test_removing_a_finished_upload_item_does_not_touch_its_task(client, uploads):
    with patch("services.transcriber.transcribe", ok()):
        body = (await _upload(client)).json()
        item = await _item(client, body["video_id"])
        await run_worker([item["id"]])
    assert (await client.delete(f"/api/queue/{item['id']}")).status_code == 200
    assert (await _status(client, body))["status"] == "completed"
    assert [r["status"] for r in await _runs(body["video_id"])] == ["done"]
    await _done(body)


async def test_a_restart_in_the_middle_of_a_transcription_runs_it_again_to_the_end(client, uploads):
    """The backend restarts while the item is processing: the item goes back to pending, the open run is closed as a restart, and the
    worker transcribes the file again - the task is never left 'pending' for good."""
    import main
    with patch("services.transcriber.transcribe", ok()):
        body = (await _upload(client)).json()
        item = await _item(client, body["video_id"])
        await q._set_processing(item["id"])                 # the worker had taken it ...
        await q._reset_stuck_items()                         # ... and the backend restarted
        await main._reset_stale_statuses()
        assert (await _item(client, body["video_id"]))["status"] == "pending"
        (stale,) = await _runs(body["video_id"])
        assert stale["status"] == "cancelled" and json.loads(stale["meta"]) == {"reason": "restart"}
        await run_worker([item["id"]])
    assert (await _item(client, body["video_id"]))["status"] == "done"
    assert (await _status(client, body))["status"] == "completed"
    assert [(r["attempt"], r["status"]) for r in await _runs(body["video_id"])] == [(1, "cancelled"), (2, "done")]
    await _done(body)
