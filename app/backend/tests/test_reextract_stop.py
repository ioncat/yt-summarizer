"""NS-11 stage 6: Stop on a re-extract / re-transcribe (decision 1: nothing is replaced, the saved text and what was made from it stay)."""
import asyncio
import threading
import time
from unittest.mock import patch

import pytest

from services.stage_control import TRANSCRIBE_CANCEL
from services.transcriber import TranscriptionResult
from tests.baseline_helpers import VIDEO_ID, fmt_row, reset_queue, run_reextract_items
from tests.test_baseline_reextract import LOCAL_ID, local_video, stt, yt, youtube_video  # noqa: F401
from tests.test_reextract_queue import items_of, runs_of


@pytest.fixture(autouse=True)
async def _clean(client):
    TRANSCRIBE_CANCEL.clear()
    await reset_queue()
    yield
    TRANSCRIBE_CANCEL.clear()
    await reset_queue()


def endless(started: threading.Event):
    """Segment after segment until the progress callback raises (the Stop), like the real engines."""
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
        return TranscriptionResult(segments=[{"start": 0.0, "end": 1.0, "text": "TOO LATE"}], detected_language="en", success=True, device_used="cpu")
    return fake


async def _keeps_everything():
    row = await fmt_row(LOCAL_ID)
    assert (row["formatted_text"], row["cleaned_text"], row["summary_text"], row["mindmap_text"]) == (
        "OLD TRANSCRIPT", "OLD CLEAN", "OLD SUMMARY", "OLD MAP")


async def test_stop_on_a_running_retranscription_replaces_nothing(client, local_video):
    started = threading.Event()
    with patch("services.transcriber.transcribe", endless(started)):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        worker = asyncio.create_task(run_reextract_items(LOCAL_ID))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        r = await client.delete(f"/api/result/{LOCAL_ID}/reextract")
        assert r.status_code == 200 and r.json() == {"status": "stopping"}
        (item,) = await worker
    assert item["status"] == "skipped" and item["error_message"] == "Re-extract stopped"
    await _keeps_everything()
    (run,) = await runs_of(LOCAL_ID, "transcribe")
    assert (run["status"], run["error_code"]) == ("cancelled", "cancelled")
    assert LOCAL_ID not in TRANSCRIBE_CANCEL
    assert not (await client.get(f"/api/result/{LOCAL_ID}")).json().get("reextract_in_progress")      # the page is free again


async def test_stop_on_a_queued_reextract_takes_it_out_of_the_queue_and_cancels_its_run(client, local_video):
    await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
    r = await client.delete(f"/api/result/{LOCAL_ID}/reextract")
    assert r.status_code == 200 and r.json() == {"status": "stopped"}
    assert await items_of(client, LOCAL_ID) == []
    (run,) = await runs_of(LOCAL_ID, "transcribe")
    assert run["status"] == "cancelled"
    assert not (await client.get(f"/api/result/{LOCAL_ID}")).json().get("reextract_in_progress")
    await _keeps_everything()


async def test_stop_with_nothing_to_stop_is_404(client, local_video):
    assert (await client.delete(f"/api/result/{LOCAL_ID}/reextract")).status_code == 404
    assert (await client.delete("/api/result/no-such-video/reextract")).status_code == 404


async def test_a_stop_that_arrives_as_the_transcription_ends_still_wins(client, local_video):
    def finishes_after_the_stop(path, language, model, device, cache_path, on_progress):
        TRANSCRIBE_CANCEL.add(LOCAL_ID)                    # Stop pressed just before the end: no more segments, no callback
        return TranscriptionResult(segments=[{"start": 0.0, "end": 1.0, "text": "TOO LATE"}], detected_language="en", success=True, device_used="cpu")

    with patch("services.transcriber.transcribe", finishes_after_the_stop):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        (item,) = await run_reextract_items(LOCAL_ID)
    assert item["status"] == "skipped"
    await _keeps_everything()


async def test_a_stop_before_the_work_begins_means_nothing_is_called(client, local_video):
    called = []
    with patch("services.transcriber.transcribe", lambda *a, **k: called.append(1)):
        await client.post(f"/api/result/{LOCAL_ID}/reextract", json={})
        TRANSCRIBE_CANCEL.add(LOCAL_ID)
        (item,) = await run_reextract_items(LOCAL_ID)
    assert called == [] and item["status"] == "skipped"
    await _keeps_everything()


async def test_stop_while_yt_dlp_runs_throws_its_result_away(client, youtube_video):
    before = (await fmt_row(VIDEO_ID))["formatted_text"]
    started = threading.Event()

    def slow_extract(*a, **k):
        started.set()
        time.sleep(0.3)
        return yt()

    with patch("services.reextract.extract_subtitles", slow_extract):
        await client.post(f"/api/result/{VIDEO_ID}/reextract", json={})
        worker = asyncio.create_task(run_reextract_items(VIDEO_ID))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        assert (await client.delete(f"/api/result/{VIDEO_ID}/reextract")).json() == {"status": "stopping"}
        (item,) = await worker
    assert item["status"] == "skipped"
    assert (await fmt_row(VIDEO_ID))["formatted_text"] == before
    assert (await runs_of(VIDEO_ID, "extract"))[-1]["status"] == "cancelled"
