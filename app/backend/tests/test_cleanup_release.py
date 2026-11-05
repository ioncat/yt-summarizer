"""NS-11 stage 4a: a cleanup marked 'processing' never stays that way without a queue item to end it."""
from unittest.mock import patch

import pytest
import pytest_asyncio

from models.database import AsyncSessionLocal
from services import queue_service as q
from services.queue_by_id import release_cleanup_status, release_stage_status
from services.stage_control import CLEANUP_CANCEL
from tests.baseline_helpers import VIDEO_ID, add_item, fmt_row, get_item, reset_queue, run_worker, set_fmt


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    CLEANUP_CANCEL.clear()
    await reset_queue()
    await client.put("/api/settings/cleanup", json={"model": "m-clean"})
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    CLEANUP_CANCEL.clear()
    await reset_queue()


async def test_remove_on_the_queue_page_resets_a_cleanup_status_and_keeps_the_saved_cleaned_text(client, seeded_video):
    await set_fmt(cleaned_text="SAVED CLEANED", cleanup_status="processing")
    item = await add_item(["cleanup"])
    assert (await client.delete(f"/api/queue/{item}")).json() == {"deleted": item}
    row = await fmt_row()
    assert row["cleanup_status"] is None and row["cleaned_text"] == "SAVED CLEANED"


async def test_clear_pending_resets_the_cleanup_status_of_the_removed_items(client, seeded_video):
    await set_fmt(cleanup_status="processing")
    await add_item(["extract", "cleanup", "summary"])
    assert (await client.delete("/api/queue/all")).json() == {"cleared": 1}
    assert (await fmt_row())["cleanup_status"] is None


async def test_removing_one_of_two_items_that_include_the_cleanup_keeps_the_status_for_the_other(client, seeded_video):
    await set_fmt(cleanup_status="processing")
    first = await add_item(["cleanup"])
    await add_item(["cleanup", "summary"])
    await client.delete(f"/api/queue/{first}")
    assert (await fmt_row())["cleanup_status"] == "processing"


async def test_removing_an_item_without_the_cleanup_stage_leaves_a_running_cleanups_status_alone(client, seeded_video):
    await set_fmt(cleanup_status="processing")
    other = await add_item(["summary"])
    await client.delete(f"/api/queue/{other}")
    assert (await fmt_row())["cleanup_status"] == "processing"


async def test_done_and_failed_cleanup_statuses_are_never_changed_by_removing_an_item(client, seeded_video):
    for status in ("done", "failed"):
        await set_fmt(cleanup_status=status, cleaned_text="C")
        item = await add_item(["cleanup"])
        await client.delete(f"/api/queue/{item}")
        row = await fmt_row()
        assert row["cleanup_status"] == status and row["cleaned_text"] == "C"


async def test_an_item_failing_before_its_cleanup_stage_ends_the_queued_cleanups_status_with_a_message(client, seeded_video):
    await set_fmt(cleanup_status="processing")                   # the user pressed Clean: the full item stands in
    item = await add_item(["extract", "cleanup"])

    async def boom(*a, **k):
        raise RuntimeError("extract exploded")

    with patch.object(q, "_run_extract", boom):
        await run_worker([item])
    assert (await get_item(item))["status"] == "failed"
    row = await fmt_row()
    assert row["cleanup_status"] == "failed"
    assert row["cleanup_error"] == "Cleanup did not run: an earlier stage failed (extract exploded)"


async def test_the_same_failure_changes_nothing_when_nobody_pressed_clean(client, seeded_video):
    item = await add_item(["extract", "cleanup"])                # the Home pipeline: the status is idle

    async def boom(*a, **k):
        raise RuntimeError("extract exploded")

    with patch.object(q, "_run_extract", boom):
        await run_worker([item])
    assert (await fmt_row())["cleanup_status"] is None


async def test_a_failure_of_the_cleanup_stage_itself_keeps_its_own_message(client, seeded_video):
    await set_fmt(cleanup_status="processing")
    item = await add_item(["cleanup"])

    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("services.text_cleaner.clean_text", boom):
        await run_worker([item])
    row = await fmt_row()
    assert row["cleanup_status"] == "failed" and row["cleanup_error"] == "llm exploded"


async def test_release_changes_nothing_when_another_item_still_owns_the_status(seeded_video):
    await set_fmt(cleanup_status="processing")
    await add_item(["cleanup"])
    async with AsyncSessionLocal() as db:
        assert await release_cleanup_status(db, VIDEO_ID) is False
        assert await release_stage_status(db, VIDEO_ID, "summary") is False
    assert (await fmt_row())["cleanup_status"] == "processing"
