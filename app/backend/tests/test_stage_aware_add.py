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


async def test_a_queued_extract_does_not_block_cleanup_then_summarize(client, seeded_video):
    async with AsyncSessionLocal() as db:
        await db.execute(text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order) "
                              f"VALUES ('https://www.youtube.com/watch?v={VIDEO_ID}', '{VIDEO_ID}', 'pending', '[\"extract\"]', datetime('now'), 1)"))
        await db.commit()
    second = await add(client, ["cleanup", "summary"])
    assert second["added"] == 1 and second["duplicates"] == []
    assert [stages for _, stages in await items()] == [["extract"], ["cleanup", "summary"]]


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


# --- the order the user asked for is never reversed ------------------------------------------------------------

async def test_a_queued_summary_blocks_cleanup_then_summarize_instead_of_running_it_on_the_raw_text(client, seeded_video):
    await add(client, ["summary"])
    again = await add(client, ["cleanup", "summary"])
    assert again["added"] == 0 and again["duplicates"] == [VIDEO_ID]
    (detail,) = again["duplicate_details"]
    assert (detail["reason"], detail["stages"]) == ("order", ["summary"])
    assert detail["message"] == ("A summary is already queued and would run before the cleanup and summary: "
                                 "wait for it or remove it on the Queue page, then try again.")
    assert [stages for _, stages in await items()] == [["summary"]]              # nothing was queued behind it
    fmt = await fmt_row()
    assert fmt["cleanup_status"] is None                                          # and no stage was marked


async def test_a_queued_mind_map_blocks_summarize_then_map_the_same_way(client, seeded_video):
    await add(client, ["mindmap"])
    again = await add(client, ["summary", "mindmap"])
    assert again["added"] == 0
    assert again["duplicate_details"][0]["reason"] == "order" and again["duplicate_details"][0]["stages"] == ["mindmap"]


async def test_a_queued_stage_does_not_block_when_what_must_come_before_it_is_not_asked_for(client, seeded_video):
    await add(client, ["summary"])
    again = await add(client, ["summary", "mindmap"])                 # summary is queued; mindmap after it is in order
    assert again["added"] == 1 and again["duplicates"] == []
    assert [stages for _, stages in await items()] == [["summary"], ["mindmap"]]


async def test_a_queued_cleanup_never_blocks_anything_after_it(client, seeded_video):
    await add(client, ["cleanup"])
    again = await add(client, ["cleanup", "summary", "mindmap"])
    assert again["added"] == 1
    assert [stages for _, stages in await items()] == [["cleanup"], ["summary", "mindmap"]]


async def test_a_queued_mind_map_blocks_cleanup_then_summarize_even_though_it_was_not_asked_for(client, seeded_video):
    await add(client, ["mindmap"])
    again = await add(client, ["cleanup", "summary"])
    assert again["added"] == 0 and again["duplicates"] == [VIDEO_ID]
    (detail,) = again["duplicate_details"]
    assert (detail["reason"], detail["stages"]) == ("order", ["mindmap"])
    assert "mind map is already queued and would run before the cleanup and summary" in detail["message"]
    assert [stages for _, stages in await items()] == [["mindmap"]]


async def test_a_queued_summary_blocks_a_new_cleanup_but_a_queued_cleanup_does_not_block_a_new_summary(client, seeded_video):
    await add(client, ["summary"])
    blocked = await add(client, ["cleanup"])
    assert blocked["added"] == 0 and blocked["duplicate_details"][0]["reason"] == "order"
    await reset_queue()
    await add(client, ["cleanup"])
    assert (await add(client, ["summary", "mindmap"]))["added"] == 1


# --- the single-stage buttons follow the same rule -----------------------------------------------------------

async def test_the_cleanup_button_is_refused_while_a_summary_or_mind_map_is_queued(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    await add(client, ["summary"])
    r = await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    assert r.status_code == 409 and "summary is already queued and would run before the cleanup" in r.json()["detail"]
    assert [stages for _, stages in await items()] == [["summary"]]
    assert (await fmt_row())["cleanup_status"] is None


async def test_the_summary_button_is_refused_while_a_mind_map_is_queued_but_not_while_a_cleanup_is(client, seeded_video):
    await client.put("/api/settings/summarization", json={"model": "m"})
    await add(client, ["mindmap"])
    r = await client.post(f"/api/result/{VIDEO_ID}/summary")
    assert r.status_code == 409 and "mind map is already queued and would run before the summary" in r.json()["detail"]
    await reset_queue()
    await add(client, ["cleanup"])
    assert (await client.post(f"/api/result/{VIDEO_ID}/summary")).status_code == 200


async def test_a_button_whose_stage_is_already_queued_adds_nothing_and_is_not_refused(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    await add(client, ["cleanup", "summary"])
    r = await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    assert r.status_code == 200 and len(await items()) == 1


# --- a click that adds nothing sets no status (review of 4b) -----------------------------------------------------

async def _running_item(stages):
    async with AsyncSessionLocal() as db:
        item = (await db.execute(
            text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order, started_at) "
                 f"VALUES ('https://www.youtube.com/watch?v={VIDEO_ID}', '{VIDEO_ID}', 'processing', :s, datetime('now'), 1, datetime('now'))"),
            {"s": json.dumps(stages)})).lastrowid
        await db.commit()
    return item


async def test_the_cleanup_button_while_a_running_item_has_passed_its_cleanup_changes_nothing(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    await _running_item(["cleanup", "summary"])                      # the worker is past the cleanup: no open run, status idle
    r = await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    assert r.status_code == 409 and "already part of the item that is running" in r.json()["detail"]
    assert (await fmt_row())["cleanup_status"] is None               # not stuck on 'processing'
    assert len(await items()) == 1 and await runs("cleanup") == []


async def test_the_summary_and_mind_map_buttons_follow_the_same_rule(client, seeded_video):
    await client.put("/api/settings/summarization", json={"model": "m"})
    await _running_item(["summary", "mindmap"])
    for stage in ("summary", "mindmap"):
        r = await client.post(f"/api/result/{VIDEO_ID}/{stage}")
        assert r.status_code == 409, stage
    fmt = await fmt_row()
    assert (fmt["summary_status"], fmt["mindmap_status"]) == (None, None)
    assert len(await items()) == 1


async def test_a_running_item_whose_cleanup_run_is_still_open_answers_200_and_keeps_one_run(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    item = await _running_item(["cleanup", "summary"])
    async with AsyncSessionLocal() as db:
        from services import stage_runs
        await stage_runs.begin(db, VIDEO_ID, "cleanup", "m", item)       # the cleanup is running right now
        await db.commit()
    r = await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    assert r.status_code == 200
    assert [x["status"] for x in await runs("cleanup")] == ["processing"] and len(await items()) == 1


async def test_a_pending_item_with_the_stage_still_to_run_answers_200_and_marks_it(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    async with AsyncSessionLocal() as db:
        await db.execute(text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order) "
                              f"VALUES ('https://www.youtube.com/watch?v={VIDEO_ID}', '{VIDEO_ID}', 'pending', '[\"cleanup\"]', datetime('now'), 1)"))
        await db.commit()
    assert (await client.post(f"/api/result/{VIDEO_ID}/cleanup")).status_code == 200
    assert (await fmt_row())["cleanup_status"] == "processing" and len(await items()) == 1
