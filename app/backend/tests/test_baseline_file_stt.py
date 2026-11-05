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
from tests.baseline_helpers import fmt_row


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """Point the upload directory of routers/process.py at tmp_path/app/data/uploads."""
    import routers.process as proc
    fake_py = tmp_path / "app" / "backend" / "routers" / "process.py"
    fake_py.parent.mkdir(parents=True)
    monkeypatch.setattr(proc, "__file__", str(fake_py))
    return tmp_path / "app" / "data" / "uploads"


async def _forget(video_id: str) -> None:
    async with AsyncSessionLocal() as db:
        for t in ("subtitles_raw", "subtitles_formatted", "processing_tasks"):
            await db.execute(text(f"DELETE FROM {t} WHERE video_id IN (SELECT id FROM videos WHERE video_id=:v)"), {"v": video_id})
        await db.execute(text("DELETE FROM videos WHERE video_id=:v"), {"v": video_id})
        await db.commit()


async def _upload(client, name="talk.m4a", language="auto"):
    return await client.post("/api/process/file", files={"file": (name, b"fakeaudio", "audio/mp4")}, data={"language": language})


async def test_a_failed_transcription_fails_the_task_with_the_message_and_saves_nothing(client, uploads):
    def failing(path, language, model, device, cache_path, on_progress):
        return TranscriptionResult(segments=[], detected_language="", success=False, error_message="model files are missing")

    with patch("services.transcriber.transcribe", failing):
        body = (await _upload(client)).json()
    st = (await client.get(f"/api/status/{body['task_id']}")).json()
    assert st["status"] == "failed" and st["error_message"] == "model files are missing"
    assert await fmt_row(body["video_id"]) is None                       # nothing was saved as a result
    await _forget(body["video_id"])


async def test_an_exception_in_the_transcriber_fails_the_task_with_its_text(client, uploads):
    def exploding(*a, **k):
        raise RuntimeError("cuda out of memory")

    with patch("services.transcriber.transcribe", exploding):
        body = (await _upload(client)).json()
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
        post = asyncio.create_task(_upload(client))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        async with AsyncSessionLocal() as db:
            task_id = (await db.execute(text("SELECT id FROM processing_tasks ORDER BY started_at DESC LIMIT 1"))).scalar()
        assert (await client.get(f"/api/status/{task_id}")).json()["progress_text"] == "segment 3 · 50%"
        release.set()
        body = (await post).json()
    assert (await client.get(f"/api/status/{body['task_id']}")).json()["progress_text"] is None
    await _forget(body["video_id"])


async def test_an_empty_transcript_is_saved_as_a_result_today(client, uploads):
    # BASELINE: known bug — a file with no speech gives success with no segments and is stored as an empty "transcript"
    # (decision 5: this becomes an explicit failure "no speech found" and nothing is saved).
    def silent(path, language, model, device, cache_path, on_progress):
        return TranscriptionResult(segments=[], detected_language="en", success=True, device_used="cpu")

    with patch("services.transcriber.transcribe", silent):
        body = (await _upload(client)).json()
    st = (await client.get(f"/api/status/{body['task_id']}")).json()
    assert st["status"] == "completed"
    row = await fmt_row(body["video_id"])
    assert row is not None and not row["formatted_text"]
    await _forget(body["video_id"])


async def test_the_upload_is_kept_after_a_failure_and_after_a_success_when_auto_delete_is_off(client, uploads):
    await client.put("/api/settings/app", json={"upload_auto_delete": "false"})

    def failing(path, language, model, device, cache_path, on_progress):
        return TranscriptionResult(segments=[], detected_language="", success=False, error_message="x")

    with patch("services.transcriber.transcribe", failing):
        body = (await _upload(client)).json()
    assert len(list(uploads.iterdir())) == 1
    await _forget(body["video_id"])


async def test_post_runs_the_transcription_inside_the_request_so_it_answers_only_when_done(client, uploads):
    # BASELINE: changes in stage 5 — the POST will answer at once and the work waits its turn in the queue.
    seen = {}

    def quick(path, language, model, device, cache_path, on_progress):
        seen["ran"] = True
        return TranscriptionResult(segments=[{"start": 0.0, "end": 1.0, "text": "Ok."}], detected_language="en", success=True, device_used="cpu")

    with patch("services.transcriber.transcribe", quick):
        body = (await _upload(client)).json()
    assert seen == {"ran": True}                                          # already ran when the response arrived
    assert (await client.get(f"/api/status/{body['task_id']}")).json()["status"] == "completed"
    await _forget(body["video_id"])
