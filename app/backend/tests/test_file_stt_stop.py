"""NS-11 stage 5: Stop on a file transcription (decision 1: the status resets, nothing is saved, a saved transcript stays)."""
import asyncio
import threading
import time
from unittest.mock import patch

import pytest
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services import file_stt
from services.stage_control import TRANSCRIBE_CANCEL
from services.transcriber import TranscriptionResult
from tests.baseline_helpers import fmt_row, reset_queue, run_worker
from tests.test_baseline_file_stt import _forget, _item, _upload, uploads  # noqa: F401
from tests.test_file_stt_queue import _forget_runs, _runs, ok


@pytest.fixture(autouse=True)
async def _clean(client):
    TRANSCRIBE_CANCEL.clear()
    await reset_queue()
    yield
    TRANSCRIBE_CANCEL.clear()
    await reset_queue()


def endless(started: threading.Event, calls: list | None = None):
    """A transcriber that keeps working segment by segment until its progress callback raises (the Stop), like the real engines,
    which turn an exception raised by the callback into a failed result."""
    def fake(path, language, model, device, cache_path, on_progress):
        started.set()
        n = 0
        try:
            while n < 400:
                n += 1
                on_progress(n, float(n), 1000.0)
                time.sleep(0.01)
        except Exception as exc:  # noqa: BLE001
            return TranscriptionResult(segments=[], detected_language="", success=False, error_message=str(exc))
        if calls is not None:
            calls.append("finished")
        return TranscriptionResult(segments=[{"start": 0.0, "end": 1.0, "text": "Too late."}], detected_language="en", success=True, device_used="cpu")
    return fake


async def test_stop_on_a_running_transcription_ends_it_and_saves_nothing(client, uploads):
    started = threading.Event()
    with patch("services.transcriber.transcribe", endless(started)):
        body = (await _upload(client)).json()
        queued = await _item(client, body["video_id"])
        worker = asyncio.create_task(run_worker([queued["id"]]))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        r = await client.delete(f"/api/process/file/{body['video_id']}")
        assert r.status_code == 200 and r.json() == {"status": "stopping"}
        await worker
    item = await _item(client, body["video_id"])
    st = (await client.get(f"/api/status/{body['task_id']}")).json()
    assert item["status"] == "skipped" and item["error_message"] == "Transcription stopped"
    assert st["status"] == "failed" and st["error_message"] == "Transcription stopped"
    assert await fmt_row(body["video_id"]) is None                           # nothing was saved
    (run,) = await _runs(body["video_id"])
    assert (run["status"], run["error_code"]) == ("cancelled", "cancelled")
    assert body["video_id"] not in TRANSCRIBE_CANCEL and len(list(uploads.iterdir())) == 1      # the flag is consumed, the file kept
    await _forget(body["video_id"])
    await _forget_runs(body["video_id"])


async def test_stop_on_a_queued_upload_takes_it_out_of_the_queue(client, uploads):
    body = (await _upload(client)).json()
    r = await client.delete(f"/api/process/file/{body['video_id']}")
    assert r.status_code == 200 and r.json() == {"status": "stopped"}
    assert [i for i in (await client.get("/api/queue")).json()["items"] if i["video_id"] == body["video_id"]] == []
    st = (await client.get(f"/api/status/{body['task_id']}")).json()
    assert st["status"] == "failed" and st["error_message"] == "Transcription stopped"
    (run,) = await _runs(body["video_id"])
    assert run["status"] == "cancelled"
    await _forget(body["video_id"])
    await _forget_runs(body["video_id"])


async def test_stop_for_a_file_that_is_not_being_transcribed_is_404(client, uploads):
    assert (await client.delete("/api/process/file/file-unknown0")).status_code == 404
    with patch("services.transcriber.transcribe", ok()):
        body = (await _upload(client)).json()
        await run_worker([(await _item(client, body["video_id"]))["id"]])
    assert (await client.delete(f"/api/process/file/{body['video_id']}")).status_code == 404       # already done
    await _forget(body["video_id"])
    await _forget_runs(body["video_id"])


async def test_a_stop_that_arrives_as_the_transcription_ends_still_wins(client, uploads):
    def finishes_after_the_stop(path, language, model, device, cache_path, on_progress):
        TRANSCRIBE_CANCEL.add(body["video_id"])                               # Stop pressed just before the end, no more segments
        return TranscriptionResult(segments=[{"start": 0.0, "end": 1.0, "text": "Done."}], detected_language="en", success=True, device_used="cpu")

    with patch("services.transcriber.transcribe", finishes_after_the_stop):
        body = (await _upload(client)).json()
        await run_worker([(await _item(client, body["video_id"]))["id"]])
    assert (await _item(client, body["video_id"]))["status"] == "skipped"
    assert await fmt_row(body["video_id"]) is None
    await _forget(body["video_id"])
    await _forget_runs(body["video_id"])


async def test_a_stop_before_the_work_begins_means_the_transcriber_is_never_called(client, uploads):
    called = []
    with patch("services.transcriber.transcribe", lambda *a, **k: called.append(1)):
        body = (await _upload(client)).json()
        TRANSCRIBE_CANCEL.add(body["video_id"])
        await run_worker([(await _item(client, body["video_id"]))["id"]])
    assert called == [] and (await _item(client, body["video_id"]))["status"] == "skipped"
    await _forget(body["video_id"])
    await _forget_runs(body["video_id"])


async def test_stop_keeps_a_saved_transcript(client, seeded_video):
    from tests.baseline_helpers import VIDEO_ID
    before = await fmt_row(VIDEO_ID)
    async with AsyncSessionLocal() as db:
        await db.execute(text("INSERT INTO processing_tasks (id, video_id, status, progress, started_at) "
                              "VALUES ('task-stop', :v, 'pending', 0, datetime('now'))"), {"v": seeded_video["db_id"]})
        await db.commit()
    TRANSCRIBE_CANCEL.add(VIDEO_ID)
    with pytest.raises(file_stt.StageCancelled):
        await file_stt.run_file_transcription("task-stop", VIDEO_ID, "x.m4a", "x.m4a", "auto")
    after = await fmt_row(VIDEO_ID)
    assert (after["formatted_text"], after["subtitle_source"]) == (before["formatted_text"], before["subtitle_source"])
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM processing_tasks WHERE id = 'task-stop'"))
        await db.commit()
