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


def ok(segments=None, language="en"):
    def fake(path, language_arg, model, device, cache_path, on_progress):
        return TranscriptionResult(segments=segments or [{"start": 0.0, "end": 2.0, "text": "Hello."}],
                                   detected_language=language, success=True, device_used="cpu")
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
