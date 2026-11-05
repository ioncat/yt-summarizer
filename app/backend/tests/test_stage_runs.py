"""NS-25 step 2: the writers of processing_stages (services/stage_runs.py) and their wiring into the endpoints and the queue."""
import json

import httpx
import pytest
import pytest_asyncio
import respx
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import stage_runs
from services.stage_control import StageCancelled
from tests.baseline_helpers import VIDEO_ID, fmt_row, reset_queue, run_queued_stage

OLLAMA_CHAT = "http://localhost:11434/api/chat"
TAGS = "http://localhost:11434/api/tags"
ANSWER = {"message": {"role": "assistant", "content": "Answer text."}, "done": True}


@pytest_asyncio.fixture(autouse=True)
async def _clean(client):
    async def wipe():
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM processing_stages"))
            await db.commit()
        await reset_queue()
    await wipe()
    yield
    await wipe()


async def rows(stage=None, video_id=VIDEO_ID) -> list[dict]:
    sql = "SELECT * FROM processing_stages WHERE video_id = :v" + (" AND stage = :s" if stage else "") + " ORDER BY id"
    async with AsyncSessionLocal() as db:
        return [dict(r) for r in (await db.execute(text(sql), {"v": video_id, "s": stage})).mappings().all()]


async def do(fn, *args, **kwargs):
    async with AsyncSessionLocal() as db:
        result = await fn(db, *args, **kwargs)
        await db.commit()
        return result


# --- the writers on their own --------------------------------------------------------------------------

async def test_begin_adds_one_open_row_and_a_second_begin_reuses_it():
    first = await do(stage_runs.begin, "v1", "cleanup", "m1")
    second = await do(stage_runs.begin, "v1", "cleanup", None, 7)       # the worker starting what the endpoint marked
    assert first == second
    (r,) = await rows("cleanup", "v1")
    assert (r["status"], r["attempt"], r["model"], r["queue_item_id"]) == ("processing", 1, "m1", 7)
    assert r["started_at"] is not None and r["finished_at"] is None


async def test_finish_closes_the_open_row_with_meta_and_a_later_run_is_attempt_two():
    await do(stage_runs.begin, "v1", "summary", "m1")
    await do(stage_runs.finish, "v1", "summary", model="m1", meta={"mode": "single", "chunks": 1})
    await do(stage_runs.begin, "v1", "summary", "m2")
    rs = await rows("summary", "v1")
    assert [(r["status"], r["attempt"]) for r in rs] == [("done", 1), ("processing", 2)]
    assert json.loads(rs[0]["meta"]) == {"mode": "single", "chunks": 1} and rs[0]["finished_at"] is not None


async def test_finish_without_an_open_row_adds_a_done_row():
    await do(stage_runs.finish, "v1", "mindmap")
    (r,) = await rows("mindmap", "v1")
    assert (r["status"], r["attempt"]) == ("done", 1)


async def test_fail_records_text_and_reason_code_and_always_has_a_code():
    await do(stage_runs.begin, "v1", "cleanup", "m1")
    await do(stage_runs.fail, "v1", "cleanup", "model returned nothing")
    await do(stage_runs.fail, "v1", "summary", None)                      # no open row: a failed row is added
    (c,) = await rows("cleanup", "v1")
    assert (c["status"], c["error_code"], c["error_text"]) == ("failed", "empty_answer", "model returned nothing")
    (s,) = await rows("summary", "v1")
    assert (s["status"], s["error_code"]) == ("failed", "unexpected")


async def test_cancel_closes_the_open_row_and_does_nothing_without_one():
    await do(stage_runs.begin, "v1", "mindmap")
    assert await do(stage_runs.cancel, "v1", "mindmap") is True
    assert await do(stage_runs.cancel, "v1", "mindmap") is False
    (r,) = await rows("mindmap", "v1")
    assert (r["status"], r["error_code"]) == ("cancelled", "cancelled")


async def test_close_stale_cancels_every_open_row():
    await do(stage_runs.begin, "v1", "cleanup")
    await do(stage_runs.begin, "v2", "summary")
    await do(stage_runs.finish, "v3", "mindmap")
    assert await do(stage_runs.close_stale) == 2
    assert {r["status"] for r in await rows("cleanup", "v1") + await rows("summary", "v2")} == {"cancelled"}
    assert [r["status"] for r in await rows("mindmap", "v3")] == ["done"]


async def test_an_unknown_stage_is_refused():
    with pytest.raises(ValueError):
        await do(stage_runs.begin, "v1", "dance")


# --- through the endpoints and the queue worker -------------------------------------------------------------

@respx.mock
async def test_a_cleanup_run_leaves_one_done_row_tied_to_its_queue_item(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(OLLAMA_CHAT).mock(return_value=httpx.Response(200, json=ANSWER))
    await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    (queued,) = await rows("cleanup")
    assert queued["status"] == "processing" and queued["queue_item_id"] and queued["model"] == "m"   # at enqueue
    await run_queued_stage(VIDEO_ID, "cleanup")
    (done,) = await rows("cleanup")
    assert (done["id"], done["status"], done["attempt"], done["error_code"]) == (queued["id"], "done", 1, None)
    assert done["queue_item_id"] == queued["queue_item_id"] and done["finished_at"] and done["model"] == "m"
    await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    await run_queued_stage(VIDEO_ID, "cleanup")
    assert [(r["status"], r["attempt"]) for r in await rows("cleanup")] == [("done", 1), ("done", 2)]


@respx.mock
async def test_a_failed_summary_run_is_a_failed_row_with_the_same_text_as_the_old_column(client, seeded_video):
    await client.put("/api/settings/summarization", json={"model": "m"})
    respx.post(OLLAMA_CHAT).mock(side_effect=httpx.ConnectError("refused"))
    await client.post(f"/api/result/{VIDEO_ID}/summary")
    await run_queued_stage(VIDEO_ID, "summary")
    (r,) = await rows("summary")
    assert r["status"] == "failed" and r["error_text"] and r["error_text"] == (await fmt_row())["summary_error"]
    assert r["error_code"]


@respx.mock
async def test_a_successful_summary_row_carries_mode_and_chunks(client, seeded_video):
    await client.put("/api/settings/summarization", json={"model": "m"})
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(OLLAMA_CHAT).mock(return_value=httpx.Response(200, json=ANSWER))
    await client.post(f"/api/result/{VIDEO_ID}/summary")
    await run_queued_stage(VIDEO_ID, "summary")
    (r,) = await rows("summary")
    fmt = await fmt_row()
    assert r["status"] == "done" and json.loads(r["meta"]) == {"mode": fmt["summary_mode"], "chunks": fmt["summary_chunks_count"]}


async def test_a_mind_map_that_produces_nothing_is_a_failed_row(client, seeded_video, monkeypatch):
    async def nothing(**kwargs):
        return None
    monkeypatch.setattr("services.text_mindmapper.generate_mindmap", nothing)
    await client.put("/api/settings/summarization", json={"model": "m"})
    await client.post(f"/api/result/{VIDEO_ID}/mindmap")
    await run_queued_stage(VIDEO_ID, "mindmap")
    (r,) = await rows("mindmap")
    assert r["status"] == "failed" and r["error_text"]


async def test_stop_on_a_queued_stage_cancels_its_row(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    await client.delete(f"/api/result/{VIDEO_ID}/cleanup")
    (r,) = await rows("cleanup")
    assert r["status"] == "cancelled"


async def test_removing_a_queued_item_cancels_the_run_it_was_to_do(client, seeded_video):
    from services import queue_service as q
    await client.put("/api/settings/cleanup", json={"model": "m"})
    await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    (queued,) = await rows("cleanup")
    async with AsyncSessionLocal() as db:
        assert await q.delete_item(db, queued["queue_item_id"]) == "deleted"
    assert [r["status"] for r in await rows("cleanup")] == ["cancelled"]


async def test_an_item_whose_earlier_stage_failed_marks_the_unrun_stage_failed(client, seeded_video):
    from services import queue_service as q
    await client.put("/api/settings/summarization", json={"model": "m"})
    from services.video_service import set_summary_processing
    await do(set_summary_processing, VIDEO_ID, "m")
    await q._release_unrun_stages(VIDEO_ID, "u", ["cleanup", "summary"], "cleanup exploded")
    (r,) = await rows("summary")
    assert (r["status"], r["error_code"]) == ("failed", "upstream_failed")


# --- extract / transcribe around the queue item ------------------------------------------------------------

URL = "https://www.youtube.com/watch?v=stgRecord01"


async def test_recorded_writes_a_done_row_for_an_extract_that_worked():
    async def run():
        return {"video_id": "stgRecord01", "db_video_id": None}
    assert (await stage_runs.recorded("extract", URL, 5, run))["video_id"] == "stgRecord01"
    (r,) = await rows("extract", "stgRecord01")
    assert (r["status"], r["queue_item_id"]) == ("done", 5) and r["finished_at"]


async def test_recorded_writes_failed_and_cancelled_rows_and_reraises():
    async def boom():
        raise RuntimeError("No subtitles found for this video")
    async def stop():
        raise StageCancelled("Stopped")
    with pytest.raises(RuntimeError):
        await stage_runs.recorded("extract", URL, 5, boom)
    with pytest.raises(StageCancelled):
        await stage_runs.recorded("transcribe", URL, 6, stop)
    (e,) = await rows("extract", "stgRecord01")
    assert (e["status"], e["error_code"]) == ("failed", "no_subtitles")
    (t,) = await rows("transcribe", "stgRecord01")
    assert t["status"] == "cancelled"


async def test_start_up_closes_runs_cut_off_by_a_restart(client, seeded_video):
    await do(stage_runs.begin, VIDEO_ID, "cleanup")
    import main
    await main._reset_stale_statuses()
    assert [r["status"] for r in await rows("cleanup")] == ["cancelled"]


async def test_a_restart_is_told_from_a_user_stop_by_the_meta_of_the_cancelled_row():
    await do(stage_runs.begin, "v1", "cleanup")
    await do(stage_runs.begin, "v2", "cleanup")
    await do(stage_runs.cancel, "v2", "cleanup")                          # the user pressed Stop
    await do(stage_runs.begin, "v3", "summary")
    assert await do(stage_runs.close_stale) == 2                          # v1 and v3: cut off by a restart
    (restart,) = await rows("cleanup", "v1")
    (stop,) = await rows("cleanup", "v2")
    assert restart["status"] == stop["status"] == "cancelled"
    assert json.loads(restart["meta"]) == {"reason": "restart"} and stop["meta"] is None


async def test_start_up_marks_the_runs_it_closes_as_a_restart(client, seeded_video):
    await do(stage_runs.begin, VIDEO_ID, "cleanup")
    import main
    await main._reset_stale_statuses()
    (r,) = await rows("cleanup")
    assert json.loads(r["meta"]) == {"reason": "restart"}
