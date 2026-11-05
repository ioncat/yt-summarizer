"""NS-11 stage 4a: a cleanup run that produces nothing keeps the saved cleaned text and writes no benchmark row."""
from unittest.mock import patch

import pytest
import pytest_asyncio

from models.database import AsyncSessionLocal
from services import queue_service as q
from services.video_service import finish_cleanup
from tests.baseline_helpers import Gate, VIDEO_ID, benchmark_rows, fmt_row, reset_benchmarks, set_fmt

SAVED = dict(cleaned_text="SAVED CLEANED TEXT", cleanup_status="done", cleanup_model="old-model",
             cleanup_started_at="2026-11-01 10:00:00.000000", cleanup_finished_at="2026-11-01 10:05:00.000000")
KEPT = ("cleaned_text", "cleanup_started_at", "cleanup_finished_at")   # cleanup_model follows the last run, as for the summary


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    await reset_benchmarks()
    await client.put("/api/settings/cleanup", json={"model": "m-clean"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    await reset_benchmarks()


async def _kept():
    row = await fmt_row()
    return {k: row[k] for k in KEPT}


@pytest.mark.parametrize("empty", [None, ""])
async def test_finish_with_nothing_keeps_the_saved_cleaned_text_and_its_timestamps(seeded_video, empty):
    await set_fmt(**SAVED)
    before = await _kept()
    async with AsyncSessionLocal() as db:
        await finish_cleanup(db, VIDEO_ID, empty, error="model returned nothing")
    row = await fmt_row()
    assert row["cleanup_status"] == "failed" and row["cleanup_error"] == "model returned nothing"
    assert {k: row[k] for k in KEPT} == before
    assert await benchmark_rows("cleanup") == []                    # no benchmark row for a run that failed


async def test_a_failed_first_run_leaves_no_cleaned_text_and_no_benchmark_row(seeded_video):
    async with AsyncSessionLocal() as db:
        await finish_cleanup(db, VIDEO_ID, None, error="boom")
    row = await fmt_row()
    assert row["cleanup_status"] == "failed" and row["cleaned_text"] is None and row["cleanup_started_at"] is None
    assert await benchmark_rows("cleanup") == []


async def test_a_successful_run_still_replaces_the_text_clears_the_error_and_mirrors_into_benchmark(seeded_video):
    await set_fmt(**SAVED, cleanup_error="old error")
    async with AsyncSessionLocal() as db:
        await finish_cleanup(db, VIDEO_ID, "NEW CLEANED")
    row = await fmt_row()
    assert row["cleanup_status"] == "done" and row["cleaned_text"] == "NEW CLEANED" and row["cleanup_error"] is None
    assert row["cleanup_started_at"] != SAVED["cleanup_started_at"]
    bench = await benchmark_rows("cleanup")
    assert len(bench) == 1 and bench[0]["status"] == "done" and bench[0]["output_text"] == "NEW CLEANED"


async def test_the_queue_stage_keeps_the_saved_text_when_the_rerun_comes_back_empty(seeded_video):
    await set_fmt(**SAVED)
    before = await _kept()
    gate = Gate(result=None)
    gate.release.set()
    with patch("services.text_cleaner.clean_text", gate.llm()):
        await q._run_cleanup_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["cleanup_status"] == "failed"
    assert row["cleanup_error"] == "No cleaned text was produced: Ollama may be unreachable, or the model returned nothing"
    assert {k: row[k] for k in KEPT} == before and await benchmark_rows("cleanup") == []


async def test_the_queue_stage_keeps_the_saved_text_when_the_rerun_raises(seeded_video):
    await set_fmt(**SAVED)
    before = await _kept()

    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("services.text_cleaner.clean_text", boom):
        with pytest.raises(RuntimeError):
            await q._run_cleanup_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["cleanup_status"] == "failed" and {k: row[k] for k in KEPT} == before


async def test_both_ways_of_failing_give_the_same_saved_state(seeded_video):
    await set_fmt(**SAVED)
    gate = Gate(result=None)
    gate.release.set()
    with patch("services.text_cleaner.clean_text", gate.llm()):
        await q._run_cleanup_stage(VIDEO_ID, 1)
    returned_nothing = await _kept()
    await set_fmt(**SAVED)

    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("services.text_cleaner.clean_text", boom):
        with pytest.raises(RuntimeError):
            await q._run_cleanup_stage(VIDEO_ID, 1)
    assert await _kept() == returned_nothing
