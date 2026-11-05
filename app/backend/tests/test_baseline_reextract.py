"""NS-11 stage 6: re-extract / re-transcribe (POST /api/result/{id}/reextract).

Written as a baseline of the BackgroundTask version (the POST returned when it was over; a failure was only a log line); the cases the
owner decisions changed are marked in their comments and now describe the queue behaviour.
"""
import asyncio
import os
import threading
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from models.database import AsyncSessionLocal
from services.subtitle_extractor import ExtractionResult, ExtractionErrorType, SubtitleEntry, VideoMetadata
from services.transcriber import TranscriptionResult
from tests import conftest as ct
from tests.baseline_helpers import VIDEO_ID, fmt_count, fmt_row, run_reextract_items, set_fmt

LOCAL_ID = "file-abcd1234"


@pytest_asyncio.fixture
async def local_video(db_session):
    """A transcribed local file with cleaned text, a summary and a mind map, and its upload on disk (temp uploads folder)."""
    from models.models import SubtitleFormatted, Video
    path = os.path.join(ct.TEST_UPLOADS, "abcd1234ef56.m4a")
    with open(path, "wb") as f:
        f.write(b"fakeaudio")
    video = Video(url="local://talk.m4a", video_id=LOCAL_ID, title="talk", duration=60)
    db_session.add(video)
    await db_session.flush()
    fmt = SubtitleFormatted(video_id=video.id, language="ru", formatted_text="OLD TRANSCRIPT", text_length=14,
                            processing_status="success", subtitle_source="transcript", transcription_model="tiny",
                            transcription_device="cpu", cleaned_text="OLD CLEAN", cleanup_status="done",
                            summary_text="OLD SUMMARY", summary_status="done", mindmap_text="OLD MAP", mindmap_status="done")
    db_session.add(fmt)
    await db_session.commit()
    ids = {"video_id": LOCAL_ID, "db_id": video.id, "fmt_id": fmt.id}
    yield ids
    async with AsyncSessionLocal() as db:
        for t in ("subtitles_raw", "subtitles_formatted"):
            await db.execute(text(f"DELETE FROM {t} WHERE video_id = :v"), {"v": ids["db_id"]})
        await db.execute(text("DELETE FROM videos WHERE id = :v"), {"v": ids["db_id"]})
        await db.execute(text("DELETE FROM processing_stages WHERE video_id = :v"), {"v": LOCAL_ID})
        await db.execute(text("DELETE FROM processing_queue WHERE video_id = :v"), {"v": LOCAL_ID})
        await db.commit()
    if os.path.exists(path):
        os.remove(path)


@pytest_asyncio.fixture
async def youtube_video(seeded_video):
    """The seeded YouTube video; a re-extract adds a raw-subtitles row, which the seeded_video teardown does not know."""
    yield seeded_video
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM subtitles_raw WHERE video_id = :v"), {"v": seeded_video["db_id"]})
        await db.execute(text("DELETE FROM processing_queue WHERE video_id = :v"), {"v": VIDEO_ID})
        await db.commit()


def stt(segments=None, ok=True, error=None):
    def fake(path, language, model, device, cache_path, on_progress):
        on_progress(1, 1.0, 2.0)
        return TranscriptionResult(segments=segments if segments is not None else [{"start": 0.0, "end": 2.0, "text": "NEW TRANSCRIPT."}],
                                   detected_language="en", success=ok, error_message=error, device_used="cpu")
    return fake


def yt(entries=None, ok=True, error="No subtitles found"):
    if not ok:
        return ExtractionResult(success=False, error_type=ExtractionErrorType.NO_SUBTITLES, error_message=error)
    meta = VideoMetadata(video_id=VIDEO_ID, title="T", author="A", duration=10, channel_id=None, channel_name=None, upload_date=None,
                         view_count=None, description=None, thumbnail_url=None, chapters=None)
    return ExtractionResult(success=True, metadata=meta, subtitles=entries or [SubtitleEntry(timestamp="00:00:01", text="NEW YT TEXT")],
                            language="en", source_type=None)


# --- re-transcribe a local file -------------------------------------------------------------------------------

async def test_retranscribe_replaces_the_text_in_place_and_clears_what_was_made_from_the_old_one(client, local_video):
    await client.put("/api/settings/app", json={"stt_model": "base", "stt_device": "cpu"})
    with patch("services.transcriber.transcribe", stt()):
        r = await client.post(f"/api/result/{LOCAL_ID}/reextract", json={"language": "auto", "model": "small"})
        await run_reextract_items(LOCAL_ID)             # NS-11 stage 6: a queue item, the worker does it
    assert r.status_code == 200 and r.json() == {"status": "reextracting"}
    row = await fmt_row(LOCAL_ID)
    assert "NEW TRANSCRIPT" in row["formatted_text"] and row["subtitle_source"] == "transcript" and row["language"] == "en"
    assert row["transcription_model"] == "small" and row["transcription_device"] == "cpu"       # the model of the request wins
    assert (row["cleaned_text"], row["summary_text"], row["mindmap_text"]) == (None, None, None)  # derived data cleared
    assert row["id"] == local_video["fmt_id"] and await fmt_count(LOCAL_ID) == 1                  # in place, no second row


async def test_retranscribe_uses_the_setting_when_the_request_names_no_model(client, local_video):
    await client.put("/api/settings/app", json={"stt_model": "base", "stt_device": "cpu"})
    with patch("services.transcriber.transcribe", stt()):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        await run_reextract_items(LOCAL_ID)
    assert (await fmt_row(LOCAL_ID))["transcription_model"] == "base"


async def test_a_failed_retranscription_keeps_everything_and_the_item_says_why(client, local_video):
    # NS-11 stage 6 (decision 5): this used to be only a log line (BASELINE: known bug)
    with patch("services.transcriber.transcribe", stt(segments=[], ok=False, error="model files are missing")):
        r = await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        (item,) = await run_reextract_items(LOCAL_ID)
    assert r.status_code == 200
    assert item["status"] == "failed" and item["error_message"] == "model files are missing"
    row = await fmt_row(LOCAL_ID)
    assert (row["formatted_text"], row["cleaned_text"], row["summary_text"]) == ("OLD TRANSCRIPT", "OLD CLEAN", "OLD SUMMARY")
    assert not (await client.get(f"/api/result/{LOCAL_ID}")).json().get("reextract_in_progress")


async def test_a_silent_file_fails_the_item_and_replaces_nothing(client, local_video):
    # NS-11 stage 6: no speech found (success, no segments) used to replace the transcript with an empty one and clear the cleaned
    # text, the summary and the map (BASELINE: known bug); now it is a failure and the old data stays.
    with patch("services.transcriber.transcribe", stt(segments=[])):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        (item,) = await run_reextract_items(LOCAL_ID)
    assert item["status"] == "failed" and item["error_message"] == "No speech was found in the file"
    row = await fmt_row(LOCAL_ID)
    assert (row["formatted_text"], row["cleaned_text"], row["summary_text"], row["mindmap_text"]) == (
        "OLD TRANSCRIPT", "OLD CLEAN", "OLD SUMMARY", "OLD MAP")


async def test_the_page_sees_a_running_retranscription_and_its_segments(client, local_video):
    release, started = threading.Event(), threading.Event()

    def slow(path, language, model, device, cache_path, on_progress):
        on_progress(4, 10.0, 20.0)
        started.set()
        release.wait(5)
        return stt()(path, language, model, device, cache_path, on_progress)

    with patch("services.transcriber.transcribe", slow):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        post = asyncio.create_task(run_reextract_items(LOCAL_ID))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        got = (await client.get(f"/api/result/{LOCAL_ID}")).json()
        assert got["reextract_in_progress"] is True and got["retranscribe_progress"] == "segment 4 · 50%"
        second = await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        assert second.status_code == 409 and "already in progress" in second.json()["detail"]
        release.set()
        await post
    assert not (await client.get(f"/api/result/{LOCAL_ID}")).json().get("reextract_in_progress")


async def test_a_file_that_vanished_after_the_check_fails_the_item_with_a_clear_message(client, local_video):
    # NS-11 stage 6: the endpoint found the file (200), but by the time the worker runs it is gone. This used to be only a logged
    # warning, nobody was told (the review's "silent no-op", BASELINE: known bug); now the item fails and says why.
    real_glob = __import__("glob").glob

    calls = {"n": 0}

    def vanishing(pattern, *a, **k):
        calls["n"] += 1
        return real_glob(pattern, *a, **k) if calls["n"] == 1 else []      # 1st call = the endpoint's check, 2nd = the task's

    with patch("glob.glob", vanishing), patch("services.transcriber.transcribe", stt()):
        r = await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        (item,) = await run_reextract_items(LOCAL_ID)
    assert r.status_code == 200 and (await fmt_row(LOCAL_ID))["formatted_text"] == "OLD TRANSCRIPT"
    assert item["status"] == "failed" and "no longer on disk" in item["error_message"]


# --- the conflicts the endpoint refuses ------------------------------------------------------------------------

async def test_reextract_is_refused_while_cleanup_or_summary_is_processing(client, local_video):
    await set_fmt(LOCAL_ID, cleanup_status="processing")
    assert (await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})).status_code == 409
    await set_fmt(LOCAL_ID, cleanup_status="done", summary_status="processing")
    r = await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    assert r.status_code == 409 and "Summarization is in progress" in r.json()["detail"]


# --- re-extract a YouTube video -----------------------------------------------------------------------------------

async def test_reextract_of_a_youtube_video_replaces_the_text_in_place_and_clears_derived_data(client, youtube_video):
    await set_fmt(VIDEO_ID, cleaned_text="OLD CLEAN", cleanup_status="done", summary_text="OLD SUMMARY", summary_status="done")
    with patch("services.reextract.extract_subtitles", return_value=yt()):
        r = await client.post(f"/api/result/{VIDEO_ID}/reextract", json={"language": "auto"})
        await run_reextract_items(VIDEO_ID)
    assert r.status_code == 200
    row = await fmt_row(VIDEO_ID)
    assert "NEW YT TEXT" in row["formatted_text"] and row["cleaned_text"] is None and row["summary_text"] is None
    assert row["id"] == youtube_video["fmt_id"] and await fmt_count(VIDEO_ID) == 1


async def test_a_failed_youtube_reextract_keeps_everything_and_the_item_says_why(client, youtube_video):
    # NS-11 stage 6: the same silence as for a file used to be here (BASELINE: known bug).
    await set_fmt(VIDEO_ID, cleaned_text="OLD CLEAN", cleanup_status="done")
    before = (await fmt_row(VIDEO_ID))["formatted_text"]
    with patch("services.reextract.extract_subtitles", return_value=yt(ok=False, error="This video has no subtitles available.")):
        r = await client.post(f"/api/result/{VIDEO_ID}/reextract", json={})
        (item,) = await run_reextract_items(VIDEO_ID)
    assert r.status_code == 200
    assert item["status"] == "failed" and item["error_message"] == "This video has no subtitles available."
    row = await fmt_row(VIDEO_ID)
    assert (row["formatted_text"], row["cleaned_text"]) == (before, "OLD CLEAN")
