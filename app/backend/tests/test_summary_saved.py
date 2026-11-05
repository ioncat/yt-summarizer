"""NS-11 stage 3 review: a summary run that produces nothing keeps the saved summary and writes no benchmark row."""
from unittest.mock import patch

import pytest
import pytest_asyncio

from models.database import AsyncSessionLocal
from services import queue_service as q
from services.video_service import finish_summary
from tests.baseline_helpers import Gate, VIDEO_ID, benchmark_rows, fmt_row, reset_benchmarks, set_fmt

SAVED = dict(summary_text="SAVED SUMMARY", summary_status="done", summary_model="old-model", summary_mode="map_reduce",
             summary_chunks_count=7, summary_started_at="2026-11-01 10:00:00.000000",
             summary_finished_at="2026-11-01 10:05:00.000000")
# summary_model is not in this list on purpose: set_summary_processing records the model of the RUN when it starts (the page
# shows it while the run is going on), so after a failed run it names the model that was tried. The reviewer asked for the
# summary itself and its details; the model column follows the last run.
KEPT = ("summary_text", "summary_mode", "summary_chunks_count", "summary_started_at", "summary_finished_at")


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    await reset_benchmarks()
    await client.put("/api/settings/summarization", json={"model": "m-sum"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    yield
    await reset_benchmarks()


async def _kept_values():
    row = await fmt_row()
    return {k: row[k] for k in KEPT}


@pytest.mark.parametrize("empty", [None, ""])
async def test_finish_with_nothing_keeps_the_saved_summary_and_all_its_details(seeded_video, empty):
    await set_fmt(**SAVED)
    before = await _kept_values()
    async with AsyncSessionLocal() as db:
        await finish_summary(db, VIDEO_ID, empty, mode="single", chunks_count=1, error="model returned nothing")
    row = await fmt_row()
    assert row["summary_status"] == "failed" and row["summary_error"] == "model returned nothing"
    assert {k: row[k] for k in KEPT} == before                      # text, mode, chunks and both timestamps
    assert await benchmark_rows("summary") == []                     # and no benchmark row for a run that failed


async def test_a_failed_first_run_leaves_no_summary_and_no_benchmark_row(seeded_video):
    async with AsyncSessionLocal() as db:
        await finish_summary(db, VIDEO_ID, None, error="boom")
    row = await fmt_row()
    assert row["summary_status"] == "failed" and row["summary_text"] is None and row["summary_started_at"] is None
    assert await benchmark_rows("summary") == []


async def test_a_successful_run_still_replaces_everything_and_mirrors_into_benchmark(seeded_video):
    await set_fmt(**SAVED, summary_error="old error")
    async with AsyncSessionLocal() as db:
        await finish_summary(db, VIDEO_ID, "NEW SUMMARY", mode="single", chunks_count=2)
    row = await fmt_row()
    assert row["summary_status"] == "done" and row["summary_text"] == "NEW SUMMARY" and row["summary_error"] is None
    assert row["summary_mode"] == "single" and row["summary_chunks_count"] == 2
    assert row["summary_started_at"] != SAVED["summary_started_at"]
    bench = await benchmark_rows("summary")
    assert len(bench) == 1 and bench[0]["status"] == "done" and bench[0]["output_text"] == "NEW SUMMARY"


async def test_the_queue_stage_keeps_the_saved_summary_when_the_regeneration_comes_back_empty(seeded_video):
    await set_fmt(**SAVED)
    before = await _kept_values()
    gate = Gate(result=(None, "single", 1))
    gate.release.set()
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        await q._run_summary_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["summary_status"] == "failed"
    assert row["summary_error"] == "No summary was produced: Ollama may be unreachable, or the model returned nothing"
    assert {k: row[k] for k in KEPT} == before and await benchmark_rows("summary") == []


async def test_the_queue_stage_keeps_the_saved_summary_when_the_regeneration_raises(seeded_video):
    await set_fmt(**SAVED)
    before = await _kept_values()

    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("services.text_summarizer.summarize_text", boom):
        with pytest.raises(RuntimeError):
            await q._run_summary_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["summary_status"] == "failed" and {k: row[k] for k in KEPT} == before


async def test_both_ways_of_failing_give_the_same_saved_state(seeded_video):
    """Raising and returning nothing used to leave different data behind; now the saved summary survives both."""
    await set_fmt(**SAVED)
    gate = Gate(result=(None, "single", 1))
    gate.release.set()
    with patch("services.text_summarizer.summarize_text", gate.llm()):
        await q._run_summary_stage(VIDEO_ID, 1)
    returned_nothing = await _kept_values()

    await set_fmt(**SAVED)

    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("services.text_summarizer.summarize_text", boom):
        with pytest.raises(RuntimeError):
            await q._run_summary_stage(VIDEO_ID, 1)
    assert await _kept_values() == returned_nothing
