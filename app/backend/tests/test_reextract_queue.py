"""NS-11 stage 6: a re-extract / re-transcribe is a queue item (stages ["reextract"], url = the video's url)."""
import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from models.database import AsyncSessionLocal
from tests.baseline_helpers import VIDEO_ID, reset_queue, run_reextract_items
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
