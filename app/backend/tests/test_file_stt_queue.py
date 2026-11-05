"""NS-11 stage 5: an uploaded file is a queue item (url local://<name>, video_id file-xxxxxxxx, stages ["transcribe"])."""
import os
from unittest.mock import patch

import pytest

from services import file_stt
from services.transcriber import TranscriptionResult
from tests.baseline_helpers import reset_queue, run_worker
from tests.test_baseline_file_stt import _forget, _item, _upload, uploads  # noqa: F401  (the shared helpers and fixture)


@pytest.fixture(autouse=True)
async def _empty_queue(client):
    await reset_queue()
    yield
    await reset_queue()


def ok(segments=None, detected="en"):
    def fake(path, language, model, device, cache_path, on_progress):
        return TranscriptionResult(segments=segments or [{"start": 0.0, "end": 2.0, "text": "Hello."}],
                                   detected_language=detected, success=True, device_used="cpu")
    return fake


def test_find_upload_matches_the_first_eight_characters_of_the_saved_name(tmp_path, monkeypatch):
    monkeypatch.setattr(file_stt, "uploads_dir", lambda: str(tmp_path))
    (tmp_path / "0123abcd9999.m4a").write_bytes(b"x")
    (tmp_path / "ffff00001111.mp3").write_bytes(b"x")
    assert file_stt.find_upload("file-0123abcd") == str(tmp_path / "0123abcd9999.m4a")
    assert file_stt.find_upload("file-ffff0000") == str(tmp_path / "ffff00001111.mp3")
    assert file_stt.find_upload("file-nothere0") is None
    assert file_stt.find_upload("file-") is None


async def test_the_language_of_the_upload_reaches_the_transcriber(client, uploads):
    seen = {}

    def fake(path, language, model, device, cache_path, on_progress):
        seen["language"], seen["path_exists"] = language, os.path.exists(path)
        return ok()(path, language, model, device, cache_path, on_progress)

    with patch("services.transcriber.transcribe", fake):
        body = (await _upload(client, language="de")).json()
        queued = await _item(client, body["video_id"])
        await run_worker([queued["id"]])
    assert seen == {"language": "de", "path_exists": True}
    await _forget(body["video_id"])


async def test_the_upload_waits_behind_an_earlier_queue_item(client, uploads):
    order = []

    def fake(path, language, model, device, cache_path, on_progress):
        order.append(os.path.basename(path))
        return ok()(path, language, model, device, cache_path, on_progress)

    with patch("services.transcriber.transcribe", fake):
        first = (await _upload(client, name="a.m4a")).json()
        second = (await _upload(client, name="b.m4a")).json()
        ids = [(await _item(client, first["video_id"]))["id"], (await _item(client, second["video_id"]))["id"]]
        await run_worker(ids)
    assert len(order) == 2 and order[0].startswith(first["video_id"][len("file-"):])        # first in, first out
    await _forget(first["video_id"])
    await _forget(second["video_id"])


async def test_a_file_that_is_gone_from_disk_fails_the_item_and_the_task_with_a_clear_message(client, uploads):
    with patch("services.transcriber.transcribe", ok()):
        body = (await _upload(client)).json()
        for f in uploads.iterdir():
            f.unlink()                                                      # e.g. removed by the auto-delete setting
        queued = await _item(client, body["video_id"])
        await run_worker([queued["id"]])
    failed = await _item(client, body["video_id"])
    st = (await client.get(f"/api/status/{body['task_id']}")).json()
    assert failed["status"] == "failed" and "no longer on disk" in failed["error_message"]
    assert st["status"] == "failed" and "no longer on disk" in st["error_message"]
    await _forget(body["video_id"])


async def test_retry_of_a_failed_upload_runs_it_again_and_completes_the_same_task(client, uploads):
    calls = {"n": 0}

    def flaky(path, language, model, device, cache_path, on_progress):
        calls["n"] += 1
        if calls["n"] == 1:
            return TranscriptionResult(segments=[], detected_language="", success=False, error_message="GPU busy")
        return ok()(path, language, model, device, cache_path, on_progress)

    with patch("services.transcriber.transcribe", flaky):
        body = (await _upload(client)).json()
        queued = await _item(client, body["video_id"])
        await run_worker([queued["id"]])
        assert (await _item(client, body["video_id"]))["status"] == "failed"
        assert (await client.post(f"/api/queue/{queued['id']}/retry")).status_code == 200
        await run_worker([queued["id"]])
    assert (await _item(client, body["video_id"]))["status"] == "done"
    assert (await client.get(f"/api/status/{body['task_id']}")).json()["status"] == "completed"
    await _forget(body["video_id"])


# --- the stage's run rows and error codes (decision: stage rows in processing_stages) -----------------------------

async def _runs(video_id):
    from sqlalchemy import text
    from models.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        return [dict(r) for r in (await db.execute(
            text("SELECT * FROM processing_stages WHERE video_id = :v AND stage = 'transcribe' ORDER BY id"), {"v": video_id})).mappings().all()]


async def _forget_runs(video_id):
    from sqlalchemy import text
    from models.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM processing_stages WHERE video_id = :v"), {"v": video_id})
        await db.commit()


async def test_the_upload_opens_its_run_at_once_with_the_model_and_ties_it_to_the_item(client, uploads):
    await client.put("/api/settings/app", json={"stt_model": "small"})
    body = (await _upload(client)).json()
    (run,) = await _runs(body["video_id"])
    queued = await _item(client, body["video_id"])
    assert (run["status"], run["model"], run["queue_item_id"], run["attempt"]) == ("processing", "small", queued["id"], 1)
    await client.put("/api/settings/app", json={"stt_model": "base"})
    await _forget(body["video_id"])
    await _forget_runs(body["video_id"])


async def test_a_good_run_is_done_with_model_device_and_time(client, uploads):
    import json
    await client.put("/api/settings/app", json={"stt_model": "base", "stt_device": "cpu"})
    with patch("services.transcriber.transcribe", ok()):
        body = (await _upload(client)).json()
        await run_worker([(await _item(client, body["video_id"]))["id"]])
    (run,) = await _runs(body["video_id"])               # the same row that was opened at the request
    assert (run["status"], run["model"], run["error_code"]) == ("done", "base", None)
    assert json.loads(run["meta"]) == {"device": "cpu"} and run["started_at"] and run["finished_at"]
    got = (await client.get(f"/api/result/{body['video_id']}")).json()
    assert got["stages"]["transcribe"]["status"] == "done" and got["stages"]["transcribe"]["last_done"]["model"] == "base"
    await _forget(body["video_id"])
    await _forget_runs(body["video_id"])


@pytest.mark.parametrize("make,message,code", [
    (lambda: TranscriptionResult(segments=[], detected_language="", success=False,
                                 error_message="faster-whisper is not installed. Run: pip install faster-whisper"),
     "faster-whisper is not installed", "model_missing"),
    (lambda: TranscriptionResult(segments=[], detected_language="en", success=True, device_used="cpu"),
     "No speech was found in the file", "no_speech"),
    (lambda: TranscriptionResult(segments=[], detected_language="", success=False, error_message="CUDA out of memory"),
     "CUDA out of memory", "unexpected"),
])
async def test_a_failed_run_keeps_the_message_and_gets_a_reason_code(client, uploads, make, message, code):
    def fake(*a, **k):
        return make()

    with patch("services.transcriber.transcribe", fake):
        body = (await _upload(client)).json()
        await run_worker([(await _item(client, body["video_id"]))["id"]])
    (run,) = await _runs(body["video_id"])
    assert run["status"] == "failed" and message in run["error_text"] and run["error_code"] == code
    await _forget(body["video_id"])
    await _forget_runs(body["video_id"])


async def test_a_file_that_is_gone_is_a_failed_run_with_the_file_missing_code(client, uploads):
    body = (await _upload(client)).json()
    for f in uploads.iterdir():
        f.unlink()
    with patch("services.transcriber.transcribe", ok()):
        await run_worker([(await _item(client, body["video_id"]))["id"]])
    (run,) = await _runs(body["video_id"])
    assert (run["status"], run["error_code"]) == ("failed", "file_missing")
    await _forget(body["video_id"])
    await _forget_runs(body["video_id"])


async def test_a_retry_is_a_second_run_and_the_failed_one_stays_in_the_history(client, uploads):
    calls = {"n": 0}

    def flaky(path, language, model, device, cache_path, on_progress):
        calls["n"] += 1
        if calls["n"] == 1:
            return TranscriptionResult(segments=[], detected_language="", success=False, error_message="GPU busy")
        return ok()(path, language, model, device, cache_path, on_progress)

    with patch("services.transcriber.transcribe", flaky):
        body = (await _upload(client)).json()
        queued = await _item(client, body["video_id"])
        await run_worker([queued["id"]])
        await client.post(f"/api/queue/{queued['id']}/retry")
        await run_worker([queued["id"]])
    assert [(r["attempt"], r["status"]) for r in await _runs(body["video_id"])] == [(1, "failed"), (2, "done")]
    await _forget(body["video_id"])
    await _forget_runs(body["video_id"])


async def test_a_failed_or_empty_run_leaves_a_saved_transcript_as_it_was(client, seeded_video):
    """The result of an earlier run is written only by a run that worked and found speech (complete_task is the only writer)."""
    from sqlalchemy import text
    from models.database import AsyncSessionLocal
    from tests.baseline_helpers import VIDEO_ID, fmt_row as fmt
    before = await fmt(VIDEO_ID)
    async with AsyncSessionLocal() as db:
        await db.execute(text("INSERT INTO processing_tasks (id, video_id, status, progress, started_at) "
                              "VALUES ('task-keep', :v, 'pending', 0, datetime('now'))"), {"v": seeded_video["db_id"]})
        await db.commit()
    for result in (TranscriptionResult(segments=[], detected_language="", success=False, error_message="boom"),
                   TranscriptionResult(segments=[], detected_language="en", success=True, device_used="cpu")):
        with patch("services.transcriber.transcribe", lambda *a, _r=result, **k: _r):
            with pytest.raises(file_stt.FileTranscriptionFailed):
                await file_stt.run_file_transcription("task-keep", VIDEO_ID, "x.m4a", "x.m4a", "auto")
    after = await fmt(VIDEO_ID)
    assert (after["formatted_text"], after["subtitle_source"], after["language"]) == (
        before["formatted_text"], before["subtitle_source"], before["language"])
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM processing_tasks WHERE id = 'task-keep'"))
        await db.commit()
