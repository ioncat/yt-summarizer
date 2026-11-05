"""NS-25 step 4: a queue item whose stage failed without raising is 'partial', not 'done'; retry restarts only failed stages."""
import json

import httpx
import pytest
import respx
from sqlalchemy import text

from models.database import AsyncSessionLocal
from tests.baseline_helpers import VIDEO_ID, add_item, get_item, reset_queue, run_worker

OLLAMA_CHAT = "http://localhost:11434/api/chat"
TAGS = "http://localhost:11434/api/tags"
ANSWER = {"message": {"role": "assistant", "content": "Answer text."}, "done": True}


@pytest.fixture(autouse=True)
async def _clean(client):
    async def wipe():
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM processing_stages"))
            await db.commit()
        await reset_queue()
    await wipe()
    yield
    await wipe()


async def _stage_rows(stage):
    async with AsyncSessionLocal() as db:
        return [dict(r) for r in (await db.execute(
            text("SELECT * FROM processing_stages WHERE video_id = :v AND stage = :s ORDER BY id"),
            {"v": VIDEO_ID, "s": stage})).mappings().all()]


async def _models(client):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    await client.put("/api/settings/summarization", json={"model": "m"})


@respx.mock
async def test_an_item_whose_stages_all_worked_is_done(client, seeded_video):
    await _models(client)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(OLLAMA_CHAT).mock(return_value=httpx.Response(200, json=ANSWER))
    item = await add_item(["cleanup", "summary"])
    await run_worker([item])
    got = await get_item(item)
    assert got["status"] == "done" and got["error_message"] is None


@respx.mock
async def test_an_item_with_failed_stages_that_did_not_raise_is_partial_and_names_them(client, seeded_video):
    await _models(client)
    respx.post(OLLAMA_CHAT).mock(side_effect=httpx.ConnectError("refused"))
    item = await add_item(["cleanup", "summary"])
    await run_worker([item])
    got = await get_item(item)
    assert got["status"] == "partial" and got["finished_at"]
    assert got["error_message"].startswith("Cleanup failed: ") and "; Summary failed: " in got["error_message"]
    assert [r["status"] for r in await _stage_rows("cleanup")] == ["failed"]
    assert (await _stage_rows("cleanup"))[0]["queue_item_id"] == item


async def _partial_item(stages=("cleanup", "summary"), done=("cleanup",), failed=("summary",)):
    """A finished partial item as the worker leaves it: some stages done, some failed, all tied to the item."""
    async with AsyncSessionLocal() as db:
        item = (await db.execute(
            text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order, error_message) "
                 "VALUES (:u, :v, 'partial', :s, datetime('now'), 1, 'Summary failed: x')"),
            {"u": f"https://www.youtube.com/watch?v={VIDEO_ID}", "v": VIDEO_ID, "s": json.dumps(list(stages))})).lastrowid
        for st, status in [(s, "done") for s in done] + [(s, "failed") for s in failed]:
            await db.execute(
                text("INSERT INTO processing_stages (video_id, stage, status, queue_item_id, attempt, error_text, created_at) "
                     "VALUES (:v, :s, :st, :q, 1, :e, datetime('now'))"),
                {"v": VIDEO_ID, "s": st, "st": status, "q": item, "e": "x" if status == "failed" else None})
        await db.commit()
    return item


async def test_retry_of_a_partial_item_restarts_only_its_failed_stages(client, seeded_video):
    item = await _partial_item()
    r = await client.post(f"/api/queue/{item}/retry")
    assert r.status_code == 200
    got = await get_item(item)
    assert (got["status"], got["pipeline_stages"], got["error_message"]) == ("pending", ["summary"], None)


async def test_retry_failed_takes_partial_items_too_and_leaves_a_plain_failed_item_whole(client, seeded_video):
    partial = await _partial_item(stages=("cleanup", "summary", "mindmap"), done=("cleanup",), failed=("summary", "mindmap"))
    async with AsyncSessionLocal() as db:
        failed = (await db.execute(
            text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order, error_message) "
                 "VALUES ('https://www.youtube.com/watch?v=failedItem01', 'failedItem01', 'failed', :s, datetime('now'), 2, 'boom')"),
            {"s": json.dumps(["extract", "cleanup"])})).lastrowid
        await db.commit()
    r = await client.post("/api/queue/failed/retry")
    assert r.status_code == 200 and r.json()["retried"] == 2
    assert (await get_item(partial))["pipeline_stages"] == ["summary", "mindmap"]
    got = await get_item(failed)
    assert (got["status"], got["pipeline_stages"]) == ("pending", ["extract", "cleanup"])


async def test_clear_failed_does_not_delete_partial_items(client, seeded_video):
    partial = await _partial_item()
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order) "
            "VALUES ('https://www.youtube.com/watch?v=failedItem02', 'failedItem02', 'failed', '[\"extract\"]', datetime('now'), 2)"))
        await db.commit()
    r = await client.delete("/api/queue/failed")
    assert r.status_code == 200
    assert (await get_item(partial))["status"] == "partial"
    async with AsyncSessionLocal() as db:
        left = (await db.execute(text("SELECT COUNT(*) FROM processing_queue WHERE video_id = 'failedItem02'"))).scalar()
    assert left == 0


async def test_a_partial_item_whose_failures_are_gone_is_not_retried(client, seeded_video):
    item = await _partial_item(failed=(), done=("cleanup", "summary"))
    r = await client.post(f"/api/queue/{item}/retry")
    assert r.status_code == 409
    assert (await get_item(item))["status"] == "partial"


@respx.mock
async def test_a_retried_partial_item_runs_the_failed_stage_and_ends_done(client, seeded_video):
    await _models(client)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    route = respx.post(OLLAMA_CHAT).mock(side_effect=httpx.ConnectError("refused"))
    item = await add_item(["summary"])
    await run_worker([item])
    assert (await get_item(item))["status"] == "partial"
    route.mock(return_value=httpx.Response(200, json=ANSWER))
    assert (await client.post(f"/api/queue/{item}/retry")).status_code == 200
    await run_worker([item])
    got = await get_item(item)
    assert got["status"] == "done" and got["error_message"] is None
    assert [r["status"] for r in await _stage_rows("summary")] == ["failed", "done"]


async def test_the_queue_counts_show_partial(client, seeded_video):
    await _partial_item()
    body = (await client.get("/api/queue/counts")).json()
    assert body["counts"]["partial"] == 1 and body["active"] == 0     # a partial item is finished: not "active"
