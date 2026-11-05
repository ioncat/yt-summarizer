"""NS-11 stage 2 review: a mind map marked 'processing' never stays that way without a queue item that will end it."""
from unittest.mock import patch

import pytest
import pytest_asyncio

from models.database import AsyncSessionLocal
from services import queue_service as q
from services.queue_by_id import release_mindmap_status
from services.stage_control import MINDMAP_CANCEL
from tests.baseline_helpers import Gate, VIDEO_ID, add_item, fmt_row, get_item, reset_queue, run_worker, set_fmt

URL = f"/api/result/{VIDEO_ID}"


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    MINDMAP_CANCEL.clear()
    await reset_queue()
    await client.put("/api/settings/cleanup", json={"model": "m-clean"})
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    MINDMAP_CANCEL.clear()
    await reset_queue()


async def _only_item():
    async with AsyncSessionLocal() as db:
        items = await q.get_queue(db)
    assert len(items) == 1
    return items[0]


# --- the two buttons on the queue page ---------------------------------------------------------

async def test_remove_on_the_queue_page_resets_the_mind_map_status_and_keeps_the_saved_map(client, seeded_video):
    await set_fmt(mindmap_text="SAVED MAP", mindmap_status="done")
    await client.post(f"{URL}/mindmap", params={"force": "true"})
    assert (await fmt_row())["mindmap_status"] == "processing"
    item = await _only_item()
    assert (await client.delete(f"/api/queue/{item['id']}")).json() == {"deleted": item["id"]}
    row = await fmt_row()
    assert row["mindmap_status"] is None and row["mindmap_text"] == "SAVED MAP"   # not stuck, map kept


async def test_clear_pending_resets_the_mind_map_status_of_every_removed_item(client, seeded_video):
    await client.post(f"{URL}/mindmap")
    assert (await fmt_row())["mindmap_status"] == "processing"
    assert (await client.delete("/api/queue/all")).json() == {"cleared": 1}
    assert (await fmt_row())["mindmap_status"] is None


async def test_removing_an_item_without_a_mind_map_stage_leaves_a_running_mind_maps_status_alone(client, seeded_video):
    await set_fmt(mindmap_status="processing")            # a mind map is running for this video (owned by another item)
    other = await add_item(["cleanup"])
    assert (await client.delete(f"/api/queue/{other}")).status_code == 200
    assert (await fmt_row())["mindmap_status"] == "processing"


async def test_removing_one_of_two_items_that_include_the_mind_map_keeps_the_status_for_the_other(client, seeded_video):
    await set_fmt(mindmap_status="processing")
    first = await add_item(["mindmap"])
    await add_item(["cleanup", "mindmap"])
    await client.delete(f"/api/queue/{first}")
    assert (await fmt_row())["mindmap_status"] == "processing"   # the second item will still run it


async def test_a_done_or_failed_status_is_never_changed_by_removing_an_item(client, seeded_video):
    for status in ("done", "failed"):
        await set_fmt(mindmap_status=status, mindmap_text="MAP")
        item = await add_item(["mindmap"])
        await client.delete(f"/api/queue/{item}")
        row = await fmt_row()
        assert row["mindmap_status"] == status and row["mindmap_text"] == "MAP"


async def test_clear_pending_leaves_other_videos_and_other_stages_alone(client, seeded_video):
    await set_fmt(mindmap_status="processing")            # running, owned by a processing item, not by a pending one
    async with AsyncSessionLocal() as db:
        await q.add_items(db, ["https://www.youtube.com/watch?v=someOther001"], ["cleanup"])
    assert (await client.delete("/api/queue/all")).json() == {"cleared": 1}
    assert (await fmt_row())["mindmap_status"] == "processing"


# --- a multi-stage item that fails before it reaches the mind map -----------------------------------

async def test_a_multi_stage_item_failing_early_ends_the_queued_mind_maps_status_with_a_message(client, seeded_video):
    full = await add_item(["cleanup", "summary", "mindmap"])      # e.g. the Home page's full pipeline
    r = await client.post(f"{URL}/mindmap")                        # the user presses Generate: that item stands in for it
    assert r.json() == {"status": "processing"} and (await fmt_row())["mindmap_status"] == "processing"
    async def boom(*a, **k):
        raise RuntimeError("cleanup exploded")
    with patch("services.text_cleaner.clean_text", boom):
        await run_worker([full])
    assert (await get_item(full))["status"] == "failed"
    row = await fmt_row()
    assert row["mindmap_status"] == "failed"
    assert row["mindmap_error"] == "Mind map did not run: an earlier stage failed (cleanup exploded)"


async def test_the_same_failure_changes_nothing_when_no_mind_map_was_pending(client, seeded_video):
    full = await add_item(["cleanup", "summary", "mindmap"])      # nobody pressed Generate: the status is idle
    async def boom(*a, **k):
        raise RuntimeError("cleanup exploded")
    with patch("services.text_cleaner.clean_text", boom):
        await run_worker([full])
    assert (await fmt_row())["mindmap_status"] is None


async def test_a_failure_of_the_mind_map_stage_itself_keeps_its_own_message(client, seeded_video):
    await client.post(f"{URL}/mindmap")
    gate = Gate(result=None)
    gate.release.set()
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        await run_worker([(await _only_item())["id"]])
    row = await fmt_row()
    assert row["mindmap_status"] == "failed" and row["mindmap_error"] == "No mind map was produced: Ollama may be unreachable, or the model returned nothing"


async def test_a_failing_item_without_a_mind_map_stage_does_not_touch_the_status(client, seeded_video):
    await set_fmt(mindmap_status="processing")
    item = await add_item(["cleanup"])
    async def boom(*a, **k):
        raise RuntimeError("cleanup exploded")
    with patch("services.text_cleaner.clean_text", boom):
        await run_worker([item])
    assert (await fmt_row())["mindmap_status"] == "processing"


# --- the helper itself ----------------------------------------------------------------------------------

async def test_release_changes_nothing_when_another_item_still_owns_the_status(seeded_video):
    await set_fmt(mindmap_status="processing")
    await add_item(["summary", "mindmap"])
    async with AsyncSessionLocal() as db:
        assert await release_mindmap_status(db, VIDEO_ID) is False
    assert (await fmt_row())["mindmap_status"] == "processing"


async def test_release_unknown_video_is_a_no_op():
    async with AsyncSessionLocal() as db:
        assert await release_mindmap_status(db, "no-such-video") is False
