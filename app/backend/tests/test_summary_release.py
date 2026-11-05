"""NS-11 stage 3: a summary marked 'processing' never stays that way without a queue item to end it (like the mind map)."""
from unittest.mock import patch

import pytest
import pytest_asyncio

from models.database import AsyncSessionLocal
from services import queue_service as q
from services.queue_by_id import STAGE_COLUMNS, release_stage_status, release_summary_status
from services.stage_control import MINDMAP_CANCEL, SUMMARY_CANCEL
from tests.baseline_helpers import VIDEO_ID, add_item, fmt_row, get_item, reset_queue, run_worker, set_fmt


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    SUMMARY_CANCEL.clear()
    MINDMAP_CANCEL.clear()
    await reset_queue()
    await client.put("/api/settings/cleanup", json={"model": "m-clean"})
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    SUMMARY_CANCEL.clear()
    MINDMAP_CANCEL.clear()
    await reset_queue()


def test_only_the_stages_whose_status_the_endpoint_sets_are_known():
    assert set(STAGE_COLUMNS) == {"summary", "mindmap"}


async def test_remove_on_the_queue_page_resets_a_summary_status_and_keeps_the_saved_summary(client, seeded_video):
    await set_fmt(summary_text="SAVED SUMMARY", summary_status="processing")
    item = await add_item(["summary"])
    assert (await client.delete(f"/api/queue/{item}")).json() == {"deleted": item}
    row = await fmt_row()
    assert row["summary_status"] is None and row["summary_text"] == "SAVED SUMMARY"


async def test_clear_pending_resets_summary_and_mind_map_statuses_of_the_removed_items(client, seeded_video):
    await set_fmt(summary_status="processing", mindmap_status="processing")
    await add_item(["cleanup", "summary", "mindmap"])
    assert (await client.delete("/api/queue/all")).json() == {"cleared": 1}
    row = await fmt_row()
    assert row["summary_status"] is None and row["mindmap_status"] is None


async def test_removing_one_of_two_items_that_include_the_summary_keeps_the_status_for_the_other(client, seeded_video):
    await set_fmt(summary_status="processing")
    first = await add_item(["summary"])
    await add_item(["cleanup", "summary"])
    await client.delete(f"/api/queue/{first}")
    assert (await fmt_row())["summary_status"] == "processing"


async def test_removing_an_item_without_the_summary_stage_leaves_a_running_summarys_status_alone(client, seeded_video):
    await set_fmt(summary_status="processing")
    other = await add_item(["cleanup"])
    await client.delete(f"/api/queue/{other}")
    assert (await fmt_row())["summary_status"] == "processing"


async def test_done_and_failed_summary_statuses_are_never_changed_by_removing_an_item(client, seeded_video):
    for status in ("done", "failed"):
        await set_fmt(summary_status=status, summary_text="S")
        item = await add_item(["summary"])
        await client.delete(f"/api/queue/{item}")
        row = await fmt_row()
        assert row["summary_status"] == status and row["summary_text"] == "S"


async def test_a_multi_stage_item_failing_early_ends_the_queued_summarys_status_with_a_message(client, seeded_video):
    await set_fmt(summary_status="processing")                   # the user pressed Summarize: the full item stands in
    full = await add_item(["cleanup", "summary"])

    async def boom(*a, **k):
        raise RuntimeError("cleanup exploded")

    with patch("services.text_cleaner.clean_text", boom):
        await run_worker([full])
    assert (await get_item(full))["status"] == "failed"
    row = await fmt_row()
    assert row["summary_status"] == "failed"
    assert row["summary_error"] == "Summary did not run: an earlier stage failed (cleanup exploded)"


async def test_both_a_queued_summary_and_a_queued_mind_map_are_released_when_the_item_fails_early(client, seeded_video):
    await set_fmt(summary_status="processing", mindmap_status="processing")
    full = await add_item(["cleanup", "summary", "mindmap"])

    async def boom(*a, **k):
        raise RuntimeError("cleanup exploded")

    with patch("services.text_cleaner.clean_text", boom):
        await run_worker([full])
    row = await fmt_row()
    assert row["summary_status"] == "failed" and row["summary_error"].startswith("Summary did not run")
    assert row["mindmap_status"] == "failed" and row["mindmap_error"].startswith("Mind map did not run")


async def test_the_same_failure_changes_nothing_when_nobody_pressed_summarize(client, seeded_video):
    full = await add_item(["cleanup", "summary"])                 # the Home pipeline: the status is idle

    async def boom(*a, **k):
        raise RuntimeError("cleanup exploded")

    with patch("services.text_cleaner.clean_text", boom):
        await run_worker([full])
    assert (await fmt_row())["summary_status"] is None


async def test_release_changes_nothing_when_another_item_still_owns_the_status(seeded_video):
    await set_fmt(summary_status="processing")
    await add_item(["summary"])
    async with AsyncSessionLocal() as db:
        assert await release_summary_status(db, VIDEO_ID) is False
        assert await release_stage_status(db, VIDEO_ID, "mindmap") is False     # the mind map was idle anyway
    assert (await fmt_row())["summary_status"] == "processing"


async def test_an_unknown_stage_is_refused_instead_of_building_sql_from_it(seeded_video):
    async with AsyncSessionLocal() as db:
        with pytest.raises(KeyError):
            await release_stage_status(db, VIDEO_ID, "cleanup; DROP TABLE videos")
