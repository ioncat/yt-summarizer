"""NS-11 stage 6: a re-extract / re-transcribe is a queue item (stages ["reextract"], url = the video's url)."""
import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from models.database import AsyncSessionLocal
from tests.baseline_helpers import VIDEO_ID, fmt_row, reset_queue, run_reextract_items
from tests.test_baseline_reextract import LOCAL_ID, local_video, stt, yt, youtube_video  # noqa: F401  (fixtures and fakes)


@pytest.fixture(autouse=True)
async def _empty_queue(client):
    await reset_queue()
    yield
    await reset_queue()


async def items_of(client, video_id):
    return [i for i in (await client.get("/api/queue")).json()["items"] if i["video_id"] == video_id]


async def runs_of(video_id, stage):
    async with AsyncSessionLocal() as db:
        return [dict(r) for r in (await db.execute(
            text("SELECT * FROM processing_stages WHERE video_id = :v AND stage = :s ORDER BY id"), {"v": video_id, "s": stage})).mappings().all()]


async def test_the_post_queues_an_item_and_answers_at_once(client, local_video):
    called = []
    with patch("services.transcriber.transcribe", lambda *a, **k: called.append(1)):
        r = await client.post(f"/api/result/{LOCAL_ID}/reextract", json={"language": "de"})
    assert r.status_code == 200 and r.json() == {"status": "reextracting"} and called == []      # nothing ran yet
    (item,) = await items_of(client, LOCAL_ID)
    assert (item["status"], item["url"], item["pipeline_stages"], item["language"]) == ("pending", "local://talk.m4a", ["reextract"], "de")
    assert item["db_video_id"] == local_video["db_id"]


async def test_the_default_language_is_auto(client, local_video):
    await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    (item,) = await items_of(client, LOCAL_ID)
    assert item["language"] == "auto"


async def test_the_language_and_model_of_the_request_reach_the_transcriber(client, local_video):
    seen = {}

    def fake(path, language, model, device, cache_path, on_progress):
        seen.update(language=language, model=model)
        return stt()(path, language, model, device, cache_path, on_progress)

    with patch("services.transcriber.transcribe", fake):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={"language": "uk", "model": "medium"})
        await run_reextract_items(LOCAL_ID)
    assert seen == {"language": "uk", "model": "medium"}


async def test_a_reextract_waits_behind_an_earlier_item(client, local_video, youtube_video):
    async with AsyncSessionLocal() as db:
        await db.execute(text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order) "
                              f"VALUES ('https://www.youtube.com/watch?v={VIDEO_ID}', '{VIDEO_ID}', 'pending', '[\"extract\"]', datetime('now'), 1)"))
        await db.commit()
    await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    order = [i["video_id"] for i in (await client.get("/api/queue")).json()["items"]]
    assert order == [VIDEO_ID, LOCAL_ID]


# --- conflicts the endpoint refuses ------------------------------------------------------------------------------

async def _queue_stages(video_id, stages, status="pending"):
    async with AsyncSessionLocal() as db:
        await db.execute(text("INSERT INTO processing_queue (url, video_id, status, pipeline_stages, added_at, sort_order) "
                              "VALUES ('local://talk.m4a', :v, :st, :s, datetime('now'), 1)"),
                         {"v": video_id, "st": status, "s": json.dumps(stages)})
        await db.commit()


@pytest.mark.parametrize("stages,named", [(["cleanup"], "cleanup"), (["summary"], "summary"), (["mindmap"], "mindmap"),
                                          (["cleanup", "summary"], "cleanup and summary")])
async def test_a_queued_llm_stage_blocks_the_reextract_because_it_would_work_on_the_old_text(client, local_video, stages, named):
    await _queue_stages(LOCAL_ID, stages)
    r = await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    assert r.status_code == 409 and f"A {named} is already queued" in r.json()["detail"] and "old text" in r.json()["detail"]
    assert len(await items_of(client, LOCAL_ID)) == 1                         # nothing was added


async def test_a_queued_extract_item_does_not_block_and_a_second_reextract_is_refused(client, local_video):
    await _queue_stages(LOCAL_ID, ["extract"])
    assert (await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})).status_code == 200
    again = await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    assert again.status_code == 409 and "already in progress" in again.json()["detail"]


# --- the run row that carries the model ------------------------------------------------------------------------------

async def test_a_retranscription_opens_its_transcribe_run_at_once_with_the_model_of_the_request(client, local_video):
    await client.put("/api/settings/app", json={"stt_model": "base"})
    await client.post(f"/api/result/{LOCAL_ID}/reextract", json={"model": "small"})
    (item,) = await items_of(client, LOCAL_ID)
    (run,) = await runs_of(LOCAL_ID, "transcribe")
    assert (run["status"], run["model"], run["queue_item_id"]) == ("processing", "small", item["id"])


async def test_without_a_model_in_the_request_the_run_carries_the_setting(client, local_video):
    await client.put("/api/settings/app", json={"stt_model": "tiny"})
    await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    (run,) = await runs_of(LOCAL_ID, "transcribe")
    assert run["model"] == "tiny"
    await client.put("/api/settings/app", json={"stt_model": "base"})


async def test_a_youtube_reextract_opens_an_extract_run_without_a_model(client, youtube_video):
    await client.post(f"/api/result/{VIDEO_ID}/reextract", json={})
    (run,) = await runs_of(VIDEO_ID, "extract")
    assert (run["status"], run["model"]) == ("processing", None)
    assert await runs_of(VIDEO_ID, "transcribe") == []


# --- the end of the run row and its reason codes ------------------------------------------------------------------

async def test_a_good_retranscription_closes_its_run_done_with_model_device_and_time(client, local_video):
    await client.put("/api/settings/app", json={"stt_device": "cpu"})
    with patch("services.transcriber.transcribe", stt()):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={"model": "small"})
        await run_reextract_items(LOCAL_ID)
    runs = await runs_of(LOCAL_ID, "transcribe")
    run = runs[-1]
    assert (run["status"], run["model"], run["error_code"]) == ("done", "small", None)
    assert json.loads(run["meta"]) == {"device": "cpu"} and run["started_at"] and run["finished_at"]
    assert len([r for r in runs if r["status"] == "processing"]) == 0          # no run left open


async def test_what_was_made_from_the_old_text_loses_its_runs_but_the_transcribe_runs_stay(client, local_video):
    async with AsyncSessionLocal() as db:
        await db.execute(text("INSERT INTO processing_stages (video_id, stage, status, attempt, created_at) "
                              "VALUES (:v, 'cleanup', 'done', 1, datetime('now')), (:v, 'summary', 'done', 1, datetime('now'))"), {"v": LOCAL_ID})
        await db.commit()
    with patch("services.transcriber.transcribe", stt()):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        await run_reextract_items(LOCAL_ID)
    assert await runs_of(LOCAL_ID, "cleanup") == [] and await runs_of(LOCAL_ID, "summary") == []
    assert [r["status"] for r in await runs_of(LOCAL_ID, "transcribe")] == ["done"]


@pytest.mark.parametrize("make,message,code", [
    (lambda: stt(segments=[]), "No speech was found in the file", "no_speech"),
    (lambda: stt(segments=[], ok=False, error="faster-whisper is not installed. Run: pip install faster-whisper"), "faster-whisper is not installed", "model_missing"),
    (lambda: stt(segments=[], ok=False, error="CUDA out of memory"), "CUDA out of memory", "unexpected"),
])
async def test_a_failed_retranscription_keeps_the_message_and_gets_a_reason_code(client, local_video, make, message, code):
    with patch("services.transcriber.transcribe", make()):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        await run_reextract_items(LOCAL_ID)
    (run,) = await runs_of(LOCAL_ID, "transcribe")
    assert run["status"] == "failed" and message in run["error_text"] and run["error_code"] == code
    stages = (await client.get(f"/api/result/{LOCAL_ID}")).json()["stages"]["transcribe"]
    assert stages["status"] == "failed" and stages["error_code"] == code      # the page's steps table gets it


async def test_a_vanished_file_is_file_missing_and_a_failed_extraction_gets_its_own_code(client, local_video, youtube_video):
    real_glob = __import__("glob").glob
    calls = {"n": 0}

    def vanishing(pattern, *a, **k):
        calls["n"] += 1
        return real_glob(pattern, *a, **k) if calls["n"] == 1 else []

    with patch("glob.glob", vanishing), patch("services.transcriber.transcribe", stt()):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        await run_reextract_items(LOCAL_ID)
    assert (await runs_of(LOCAL_ID, "transcribe"))[-1]["error_code"] == "file_missing"
    with patch("services.reextract.extract_subtitles", return_value=yt(ok=False, error="This video has no subtitles available.")):
        await client.post(f"/api/result/{VIDEO_ID}/reextract", json={})
        await run_reextract_items(VIDEO_ID)
    (run,) = await runs_of(VIDEO_ID, "extract")
    assert (run["status"], run["error_code"]) == ("failed", "no_subtitles")


async def test_retry_of_a_failed_reextract_is_a_second_run_that_ends_done(client, local_video):
    calls = {"n": 0}

    def flaky(path, language, model, device, cache_path, on_progress):
        calls["n"] += 1
        if calls["n"] == 1:
            return stt(segments=[], ok=False, error="GPU busy")(path, language, model, device, cache_path, on_progress)
        return stt()(path, language, model, device, cache_path, on_progress)

    with patch("services.transcriber.transcribe", flaky):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        (item,) = await run_reextract_items(LOCAL_ID)
        assert item["status"] == "failed"
        assert (await client.post(f"/api/queue/{item['id']}/retry")).status_code == 200
        (again,) = [i for i in await _items_after_retry(client)]
    assert again["status"] == "done"
    assert [(r["attempt"], r["status"]) for r in await runs_of(LOCAL_ID, "transcribe")] == [(1, "failed"), (2, "done")]
    assert "NEW TRANSCRIPT" in (await fmt_row(LOCAL_ID))["formatted_text"]


async def _items_after_retry(client):
    from tests.baseline_helpers import run_worker
    (item,) = await items_of(client, LOCAL_ID)
    await run_worker([item["id"]])
    return await items_of(client, LOCAL_ID)


# --- progress from the queue item and the run row (NS-11 decision 2) -------------------------------------------------------

async def test_the_page_text_is_waiting_then_starting_then_the_live_segments_then_nothing(client, local_video):
    import asyncio
    import threading
    release, started = threading.Event(), threading.Event()

    def slow(path, language, model, device, cache_path, on_progress):
        on_progress(9, 15.0, 60.0)
        started.set()
        release.wait(5)
        return stt()(path, language, model, device, cache_path, on_progress)

    async def text_now():
        return (await client.get(f"/api/result/{LOCAL_ID}")).json().get("retranscribe_progress")

    with patch("services.transcriber.transcribe", slow):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        assert await text_now() == "waiting in the queue"
        worker = asyncio.create_task(run_reextract_items(LOCAL_ID))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        seen = None
        for _ in range(100):
            seen = await text_now()
            if seen and seen.startswith("segment"):
                break
            await asyncio.sleep(0.02)
        assert seen == "segment 9 · 25%"
        release.set()
        await worker
    assert await text_now() is None
    (run,) = await runs_of(LOCAL_ID, "transcribe")
    assert (run["status"], run["progress_done"], run["progress_total"]) == ("done", 1, 2)       # the last counters stay on the finished run


async def test_a_running_reextract_without_counters_yet_says_starting(client, local_video):
    from services import queue_service as q
    await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    (item,) = await items_of(client, LOCAL_ID)
    await q._set_processing(item["id"])
    got = (await client.get(f"/api/result/{LOCAL_ID}")).json()
    assert got["reextract_in_progress"] is True and got["retranscribe_progress"] == "starting…"


def test_the_in_memory_copies_of_the_background_task_are_gone():
    import routers.result as r
    import services.reextract as rx
    for module in (r, rx):
        assert not hasattr(module, "_REEXTRACT_SET") and not hasattr(module, "_RETRANSCRIBE_PROGRESS")
    assert not hasattr(r, "run_reextract")                       # the router no longer starts the work itself
