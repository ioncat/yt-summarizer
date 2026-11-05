"""NS-25 step 6: adding stages by video id is stage-aware, and the stages of a new item are marked at once."""
import json

import pytest
from sqlalchemy import text

from models.database import AsyncSessionLocal
from tests.baseline_helpers import VIDEO_ID, fmt_row, get_item, reset_queue, run_worker, set_fmt


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


async def add(client, stages):
    r = await client.post("/api/queue/bulk", json={"video_ids": [VIDEO_ID], "pipeline_stages": stages})
    assert r.status_code == 200, r.text
    return r.json()


async def items():
    async with AsyncSessionLocal() as db:
        return [(r[0], json.loads(r[1])) for r in (await db.execute(
            text("SELECT id, pipeline_stages FROM processing_queue ORDER BY id"))).fetchall()]


async def runs(stage):
    async with AsyncSessionLocal() as db:
        return [dict(r) for r in (await db.execute(
            text("SELECT * FROM processing_stages WHERE video_id = :v AND stage = :s ORDER BY id"),
            {"v": VIDEO_ID, "s": stage})).mappings().all()]


async def test_a_queued_mind_map_does_not_block_cleanup_then_summarize(client, seeded_video):
    first = await add(client, ["mindmap"])
    assert first["added"] == 1
    second = await add(client, ["cleanup", "summary"])
    assert second["added"] == 1 and second["duplicates"] == []
    assert [stages for _, stages in await items()] == [["mindmap"], ["cleanup", "summary"]]


async def test_only_the_stages_not_yet_queued_are_added_and_the_response_names_the_covered_ones(client, seeded_video):
    await add(client, ["cleanup"])
    again = await add(client, ["cleanup", "summary"])
    assert again["added"] == 1 and again["duplicates"] == []
    assert [stages for _, stages in await items()] == [["cleanup"], ["summary"]]


async def test_when_every_stage_is_queued_nothing_is_added_and_the_duplicate_names_them(client, seeded_video):
    await add(client, ["cleanup", "summary"])
    again = await add(client, ["summary", "cleanup"])
    assert again["added"] == 0 and again["duplicates"] == [VIDEO_ID]
    assert again["duplicate_details"] == [{"url": None, "video_id": VIDEO_ID, "reason": "in_queue", "stages": ["summary", "cleanup"]}]
    assert len(await items()) == 1


async def test_the_stages_of_a_new_item_are_processing_at_once_and_tied_to_it(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "mc"})
    await client.put("/api/settings/summarization", json={"model": "ms"})
    res = await add(client, ["cleanup", "summary"])
    item = res["ids"][0]
    fmt = await fmt_row()
    assert (fmt["cleanup_status"], fmt["summary_status"]) == ("processing", "processing")
    got = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert (got["cleanup_status"], got["summary_status"], got["mindmap_status"]) == ("processing", "processing", None)
    assert [(r["status"], r["model"], r["queue_item_id"]) for r in await runs("cleanup")] == [("processing", "mc", item)]
    assert [(r["status"], r["model"], r["queue_item_id"]) for r in await runs("summary")] == [("processing", "ms", item)]


async def test_removing_the_item_gives_the_stages_back(client, seeded_video):
    item = (await add(client, ["cleanup", "summary"]))["ids"][0]
    assert (await client.delete(f"/api/queue/{item}")).status_code == 200
    fmt = await fmt_row()
    assert (fmt["cleanup_status"], fmt["summary_status"]) == (None, None)
    assert [r["status"] for r in await runs("summary")] == ["cancelled"]


async def test_when_cleanup_cannot_run_the_summary_of_the_chain_says_an_earlier_stage_failed(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": None})            # cleanup will fail: no model
    await client.put("/api/settings/summarization", json={"model": "ms"})
    item = (await add(client, ["cleanup", "summary"]))["ids"][0]
    await run_worker([item])
    assert (await get_item(item))["status"] == "failed"
    fmt = await fmt_row()
    assert fmt["cleanup_status"] == "failed" and "cleanup model" in fmt["cleanup_error"]
    assert fmt["summary_status"] == "failed" and "an earlier stage failed" in fmt["summary_error"]
    (r,) = await runs("summary")
    assert (r["status"], r["error_code"]) == ("failed", "upstream_failed")
