"""NS-25 step 3: GET /api/result/{id} reads the stage table first (`stages` + the old fields derived from it)."""
import httpx
import pytest
import respx
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import stage_runs
from services.stage_view import legacy_fields, stages_view
from tests.baseline_helpers import VIDEO_ID, fmt_row, reset_queue, run_queued_stage, set_fmt

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


def run(stage, status, attempt=1, model=None, started=None, finished=None, error=None, meta=None, **extra):
    return {"stage": stage, "status": status, "attempt": attempt, "model": model, "started_at": started,
            "finished_at": finished, "error_text": error, "error_code": None, "meta": meta, "queue_item_id": None,
            "progress_done": None, "progress_total": None, **extra}


# --- the derivation on its own ----------------------------------------------------------------------------

def test_the_model_and_mode_of_a_saved_result_come_from_the_last_done_run_not_a_failed_attempt():
    runs = {"summary": [
        run("summary", "done", 1, "good", "2026-11-01 10:00:00.000000", "2026-11-01 10:02:30.000000",
            meta='{"mode": "map_reduce", "chunks": 5}'),
        run("summary", "failed", 2, "bad", finished="2026-11-02 10:00:00.000000", error="boom"),
    ]}
    f = legacy_fields(runs)
    assert (f["summary_status"], f["summary_error"], f["summary_model"]) == ("failed", "boom", "good")
    assert (f["summary_mode"], f["summary_chunks_count"], f["summary_duration_seconds"]) == ("map_reduce", 5, 150)
    assert f["summary_finished_at"].startswith("2026-11-01T10:02:30")
    s = stages_view(runs)["summary"]
    assert (s["status"], s["model"], s["attempt"], s["runs"]) == ("failed", "bad", 2, 2)
    assert (s["last_done"]["model"], s["last_done"]["meta"]) == ("good", {"mode": "map_reduce", "chunks": 5})


def test_cancelled_means_nothing_running_and_the_first_running_run_shows_its_model():
    cancelled = legacy_fields({"cleanup": [run("cleanup", "done", 1, "m1"), run("cleanup", "cancelled", 2, "m2")]})
    assert (cancelled["cleanup_status"], cancelled["cleanup_error"], cancelled["cleanup_model"]) == (None, None, "m1")
    first = legacy_fields({"cleanup": [run("cleanup", "processing", 1, "m1")]})
    assert (first["cleanup_status"], first["cleanup_model"], first["cleanup_finished_at"]) == ("processing", "m1", None)
    only_cancelled = legacy_fields({"summary": [run("summary", "cancelled", 1, "m1")]})
    assert (only_cancelled["summary_status"], only_cancelled["summary_model"]) == (None, None)


def test_a_stage_without_runs_is_left_to_the_old_columns():
    assert legacy_fields({}) == {} and stages_view({}) == {}
    assert set(legacy_fields({"mindmap": [run("mindmap", "done")]})) == {"mindmap_status", "mindmap_error"}


# --- through the API ----------------------------------------------------------------------------------------

async def test_a_video_with_no_runs_has_empty_stages_and_the_old_columns_speak(client, seeded_video):
    await set_fmt(cleanup_status="failed", cleanup_error="old column", cleanup_model="legacy")
    data = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert data["stages"] == {}
    assert (data["cleanup_status"], data["cleanup_error"], data["cleanup_model"]) == ("failed", "old column", "legacy")


@respx.mock
async def test_a_failed_rerun_keeps_the_model_of_the_saved_summary(client, seeded_video):
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    route = respx.post(OLLAMA_CHAT).mock(return_value=httpx.Response(200, json=ANSWER))
    await client.put("/api/settings/summarization", json={"model": "model-good"})
    await client.post(f"/api/result/{VIDEO_ID}/summary")
    await run_queued_stage(VIDEO_ID, "summary")
    first = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert (first["summary_status"], first["summary_model"], first["summary_text"]) == ("done", "model-good", "Answer text.")
    assert first["summary_mode"] == "single" and first["summary_chunks_count"] == 1

    await client.put("/api/settings/summarization", json={"model": "model-bad"})
    route.mock(side_effect=httpx.ConnectError("refused"))
    await client.post(f"/api/result/{VIDEO_ID}/summary")
    await run_queued_stage(VIDEO_ID, "summary")
    data = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert data["summary_status"] == "failed" and data["summary_error"] and data["summary_text"] == "Answer text."
    assert data["summary_model"] == "model-good"                         # the model of the text that is shown
    assert (await fmt_row())["summary_model"] == "model-bad"             # (the old column still says the failed attempt)
    s = data["stages"]["summary"]
    assert (s["status"], s["model"], s["attempt"], s["runs"]) == ("failed", "model-bad", 2, 2)
    assert s["error_code"] and s["last_done"]["model"] == "model-good"


async def test_queued_stage_shows_processing_and_its_queue_item(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    data = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert data["cleanup_status"] == "processing" and data["cleanup_model"] == "m"
    assert data["stages"]["cleanup"]["status"] == "processing" and data["stages"]["cleanup"]["queue_item_id"]
    await client.delete(f"/api/result/{VIDEO_ID}/cleanup")
    data = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert data["cleanup_status"] is None and data["stages"]["cleanup"]["status"] == "cancelled"


async def test_deleting_the_video_removes_its_runs(client, seeded_video):
    async with AsyncSessionLocal() as db:
        await stage_runs.begin(db, VIDEO_ID, "cleanup", "m")
        await stage_runs.begin(db, "otherVideo1", "cleanup", "m")
        await db.commit()
    assert (await client.delete(f"/api/result/{VIDEO_ID}")).status_code == 200
    async with AsyncSessionLocal() as db:
        left = {r[0] for r in (await db.execute(text("SELECT video_id FROM processing_stages"))).fetchall()}
    assert left == {"otherVideo1"}


async def test_forgetting_results_after_a_new_text_keeps_extract_runs():
    async with AsyncSessionLocal() as db:
        for stage in ("extract", "cleanup", "summary", "mindmap"):
            await stage_runs.finish(db, "v1", stage)
        assert await stage_runs.forget_results(db, "v1") == 3
        await db.commit()
        left = [r[0] for r in (await db.execute(text("SELECT stage FROM processing_stages WHERE video_id = 'v1'"))).fetchall()]
    assert left == ["extract"]
