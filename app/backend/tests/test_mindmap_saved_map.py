"""NS-11 decision 4: the saved mind map is kept until a regeneration succeeds (a failed one must not wipe it)."""
from unittest.mock import patch

import pytest
import pytest_asyncio

from models.database import AsyncSessionLocal
from services import queue_service as q
from services.video_service import finish_mindmap
from tests.baseline_helpers import Gate, VIDEO_ID, fmt_row, set_fmt


@pytest_asyncio.fixture(autouse=True)
async def _models(client):
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})


async def test_a_failed_run_keeps_the_saved_map_and_records_the_error(seeded_video):
    await set_fmt(mindmap_text="SAVED MAP", mindmap_status="processing")
    async with AsyncSessionLocal() as db:
        await finish_mindmap(db, VIDEO_ID, None, error="model returned nothing")
    row = await fmt_row()
    assert row["mindmap_status"] == "failed" and row["mindmap_error"] == "model returned nothing"
    assert row["mindmap_text"] == "SAVED MAP"


async def test_a_failed_first_run_leaves_no_map(seeded_video):
    async with AsyncSessionLocal() as db:
        await finish_mindmap(db, VIDEO_ID, None, error="boom")
    row = await fmt_row()
    assert row["mindmap_status"] == "failed" and row["mindmap_text"] is None


async def test_a_successful_run_replaces_the_saved_map_and_clears_the_error(seeded_video):
    await set_fmt(mindmap_text="SAVED MAP", mindmap_status="failed", mindmap_error="old error")
    async with AsyncSessionLocal() as db:
        await finish_mindmap(db, VIDEO_ID, "# New map")
    row = await fmt_row()
    assert row["mindmap_status"] == "done" and row["mindmap_text"] == "# New map" and row["mindmap_error"] is None


async def test_the_queue_stage_keeps_the_saved_map_when_the_regeneration_comes_back_empty(seeded_video):
    await set_fmt(mindmap_text="SAVED MAP", mindmap_status="done")
    gate = Gate(result=None)
    gate.release.set()
    with patch("services.text_mindmapper.generate_mindmap", gate.llm()):
        await q._run_mindmap_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["mindmap_status"] == "failed" and row["mindmap_error"] == "The model returned no mind map"
    assert row["mindmap_text"] == "SAVED MAP"


async def test_the_queue_stage_keeps_the_saved_map_when_the_regeneration_raises(seeded_video):
    await set_fmt(mindmap_text="SAVED MAP", mindmap_status="done")

    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("services.text_mindmapper.generate_mindmap", boom):
        with pytest.raises(RuntimeError):
            await q._run_mindmap_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["mindmap_status"] == "failed" and row["mindmap_text"] == "SAVED MAP"
