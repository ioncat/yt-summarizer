"""NS-11 stage 5, commit 1 (tests only): what file transcription (POST /api/process/file) does TODAY, before it moves to the queue.

The transcription runs as a BackgroundTask: the POST returns only when it is over. Cases the owner decisions change are marked
`# BASELINE: known bug` / `# BASELINE: changes in stage 5`; they are rewritten in the commit that changes the behaviour.
"""
import asyncio
import threading
from unittest.mock import patch

import pytest
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services.transcriber import TranscriptionResult
from tests.baseline_helpers import fmt_row, reset_queue, run_worker


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """Point the upload directory at tmp_path/app/data/uploads (the router saves there, the queue worker finds the file there)."""
    import routers.process as proc
    import services.file_stt as fs
    target = tmp_path / "app" / "data" / "uploads"
    monkeypatch.setattr(fs, "uploads_dir", lambda: str(target))
    monkeypatch.setattr(proc, "uploads_dir", lambda: str(target))
    return target


async def _forget(video_id: str) -> None:
    async with AsyncSessionLocal() as db:
        for t in ("subtitles_raw", "subtitles_formatted", "processing_tasks"):
            await db.execute(text(f"DELETE FROM {t} WHERE video_id IN (SELECT id FROM videos WHERE video_id=:v)"), {"v": video_id})
        await db.execute(text("DELETE FROM videos WHERE video_id=:v"), {"v": video_id})
        await db.execute(text("DELETE FROM processing_queue WHERE video_id = :v"), {"v": video_id})
        await db.commit()


async def _upload(client, name="talk.m4a", language="auto"):
    return await client.post("/api/process/file", files={"file": (name, b"fakeaudio", "audio/mp4")}, data={"language": language})


async def _item(client, video_id):
    return next(i for i in (await client.get("/api/queue")).json()["items"] if i["video_id"] == video_id)


async def _upload_and_run(client, **kw):
    """Upload, then let the queue worker transcribe it. Returns (response body, queue item as the worker left it)."""
    body = (await _upload(client, **kw)).json()
    queued = await _item(client, body["video_id"])
    await run_worker([queued["id"]])
    return body, await _item(client, body["video_id"])


@pytest.fixture(autouse=True)
async def _empty_queue(client):
    await reset_queue()
    yield
    await reset_queue()


async def test_a_failed_transcription_fails_the_task_with_the_message_and_saves_nothing(client, uploads):
    def failing(path, language, model, device, cache_path, on_progress):
        return TranscriptionResult(segments=[], detected_language="", success=False, error_message="model files are missing")

    with patch("services.transcriber.transcribe", failing):
        body, item = await _upload_and_run(client)
    st = (await client.get(f"/api/status/{body['task_id']}")).json()
    assert st["status"] == "failed" and st["error_message"] == "model files are missing"
    assert item["status"] == "failed" and item["error_message"] == "model files are missing"      # the queue item says so too
    assert await fmt_row(body["video_id"]) is None                       # nothing was saved as a result
    await _forget(body["video_id"])


async def test_an_exception_in_the_transcriber_fails_the_task_with_its_text(client, uploads):
    def exploding(*a, **k):
        raise RuntimeError("cuda out of memory")

    with patch("services.transcriber.transcribe", exploding):
        body, item = await _upload_and_run(client)
    assert item["status"] == "failed" and item["error_message"] == "cuda out of memory"
    st = (await client.get(f"/api/status/{body['task_id']}")).json()
    assert st["status"] == "failed" and st["error_message"] == "cuda out of memory"
    await _forget(body["video_id"])


async def test_the_status_shows_the_live_segment_text_while_it_runs_and_none_after(client, uploads):
    release, started = threading.Event(), threading.Event()

    def slow(path, language, model, device, cache_path, on_progress):
        on_progress(3, 5.0, 10.0)
        started.set()
        release.wait(5)
        return TranscriptionResult(segments=[{"start": 0.0, "end": 4.0, "text": "Hi."}], detected_language="en", success=True, device_used="cpu")

    with patch("services.transcriber.transcribe", slow):
        body = (await _upload(client)).json()
        worker = asyncio.create_task(run_worker([(await _item(client, body["video_id"]))["id"]]))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        assert (await client.get(f"/api/status/{body['task_id']}")).json()["progress_text"] == "segment 3 · 50%"
        release.set()
        await worker
    assert (await client.get(f"/api/status/{body['task_id']}")).json()["progress_text"] is None
    await _forget(body["video_id"])


async def test_an_empty_transcript_is_an_explicit_failure_and_nothing_is_saved(client, uploads):
    # NS-11 stage 5 (decision 5): this used to store an empty "transcript" as a result (BASELINE: known bug).
    def silent(path, language, model, device, cache_path, on_progress):
        return TranscriptionResult(segments=[], detected_language="en", success=True, device_used="cpu")

    with patch("services.transcriber.transcribe", silent):
        body, item = await _upload_and_run(client)
    st = (await client.get(f"/api/status/{body['task_id']}")).json()
    assert st["status"] == "failed" and st["error_message"] == "No speech was found in the file"
    assert item["status"] == "failed" and item["error_message"] == "No speech was found in the file"
    assert await fmt_row(body["video_id"]) is None
    await _forget(body["video_id"])


async def test_the_upload_is_kept_after_a_failure_and_after_a_success_when_auto_delete_is_off(client, uploads):
    await client.put("/api/settings/app", json={"upload_auto_delete": "false"})

    def failing(path, language, model, device, cache_path, on_progress):
        return TranscriptionResult(segments=[], detected_language="", success=False, error_message="x")

    with patch("services.transcriber.transcribe", failing):
        body, item = await _upload_and_run(client)
    assert len(list(uploads.iterdir())) == 1
    await _forget(body["video_id"])


async def test_the_post_answers_at_once_and_the_work_waits_for_the_queue_worker(client, uploads):
    # NS-11 stage 5 (decision 6): the upload is a normal queue item; nothing is transcribed until the worker gets to it.
    seen = {}

    def quick(path, language, model, device, cache_path, on_progress):
        seen["ran"] = True
        return TranscriptionResult(segments=[{"start": 0.0, "end": 1.0, "text": "Ok."}], detected_language="en", success=True, device_used="cpu")

    with patch("services.transcriber.transcribe", quick):
        body = (await _upload(client, language="ru")).json()
        assert seen == {}                                                  # the response came before any transcription
        queued = await _item(client, body["video_id"])
        assert (queued["status"], queued["url"], queued["pipeline_stages"]) == ("pending", "local://talk.m4a", ["transcribe"])
        assert (await client.get(f"/api/status/{body['task_id']}")).json()["status"] == "pending"
        await run_worker([queued["id"]])
    assert seen == {"ran": True}
    assert (await client.get(f"/api/status/{body['task_id']}")).json()["status"] == "completed"
    done = await _item(client, body["video_id"])
    assert done["status"] == "done" and done["video_id"] == body["video_id"]
    await _forget(body["video_id"])
