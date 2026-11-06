"""NS-17 items 12 / 13: `download` is a stage of the queue item. yt-dlp is replaced by a fake that writes (or does not write) the file."""
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio

from services import downloader
from services.stage_control import ITEM_CANCEL
from services.stage_codes import ERROR_CODES, classify_error
from tests import conftest as ct
from tests.baseline_helpers import VIDEO_ID, add_item, fmt_row, get_item, reset_queue, run_worker

URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest_asyncio.fixture(autouse=True)
async def _setup(client):
    ITEM_CANCEL.clear()
    await reset_queue()
    for f in Path(ct.TEST_DOWNLOADS).iterdir():
        f.unlink()
    yield
    ITEM_CANCEL.clear()
    for f in Path(ct.TEST_DOWNLOADS).iterdir():
        f.unlink()


def fake_ytdlp(returncode=0, stderr=b"", make_file=True, on_run=None, raises=None, fragments=()):
    calls: list[list[str]] = []

    def run(args, capture_output=False, timeout=None):
        calls.append(list(args))
        for name in fragments:                                   # what yt-dlp leaves behind when it dies half way
            (Path(ct.TEST_DOWNLOADS) / name.format(id=VIDEO_ID)).write_bytes(b"frag")
        if on_run:
            on_run()
        if raises:
            raise raises
        if returncode == 0 and make_file:
            template = args[args.index("-o") + 1]
            ext = "mp3" if "-x" in args else "mp4"
            Path(template.replace("%(ext)s", ext)).write_bytes(b"x" * 10)
        return SimpleNamespace(returncode=returncode, stdout=b"", stderr=stderr)

    return run, calls


async def stage_of(client, video_id=VIDEO_ID):
    return (await client.get(f"/api/result/{video_id}")).json()["stages"].get("download")


# --- the arguments ----------------------------------------------------------------------------------------------------------

def test_the_command_is_an_argument_list_with_the_url_last_after_double_dash(tmp_path):
    args = downloader.build_args(["yt-dlp"], URL, VIDEO_ID, str(tmp_path), "mp4", "best", None)
    assert isinstance(args, list) and all(isinstance(a, str) for a in args)
    assert args[-2:] == ["--", URL]
    assert "--no-playlist" in args and args[args.index("--max-filesize") + 1] == downloader.MAX_FILESIZE
    assert args[args.index("-o") + 1] == str(tmp_path / f"{VIDEO_ID}.%(ext)s")        # named after the id, in the folder given


def test_audio_and_quality_settings_become_the_right_flags(tmp_path):
    mp3 = downloader.build_args(["yt-dlp"], URL, VIDEO_ID, str(tmp_path), "mp3", "low", None)
    assert "-x" in mp3 and mp3[mp3.index("--audio-quality") + 1] == "128K" and "-f" not in mp3
    p720 = downloader.build_args(["yt-dlp"], URL, VIDEO_ID, str(tmp_path), "mp4", "720p", None)
    assert "height<=720" in p720[p720.index("-f") + 1] and "--merge-output-format" in p720


def test_cookies_only_when_the_file_exists(tmp_path):
    cookies = tmp_path / "cookies.txt"
    assert "--cookies" not in downloader.build_args(["yt-dlp"], URL, VIDEO_ID, str(tmp_path), "mp4", "best", str(cookies))
    cookies.write_text("x")
    args = downloader.build_args(["yt-dlp"], URL, VIDEO_ID, str(tmp_path), "mp4", "best", str(cookies))
    assert args[args.index("--cookies") + 1] == str(cookies) and args[-2] == "--"


@pytest.mark.parametrize("bad", ["../evil", "a/b", "a b", "x.mp4", "", "a" * 65, "C:\\x", "id;rm -rf", "%(title)s"])
def test_a_file_name_that_is_not_a_plain_id_is_refused(bad, tmp_path):
    with pytest.raises(downloader.DownloadFailed):
        downloader.build_args(["yt-dlp"], URL, bad, str(tmp_path), "mp4", "best", None)


def test_a_percent_in_the_folder_name_cannot_become_a_yt_dlp_template_field(tmp_path):
    folder = tmp_path / "100%(title)s"
    args = downloader.build_args(["yt-dlp"], URL, VIDEO_ID, str(folder), "mp4", "best", None)
    template = args[args.index("-o") + 1]
    assert template.count("%(ext)s") == 1 and "%%(title)s" in template


def test_find_download_ignores_half_written_files(tmp_path):
    (tmp_path / f"{VIDEO_ID}.mp4.part").write_bytes(b"1")
    (tmp_path / f"{VIDEO_ID}.f137.mp4.ytdl").write_bytes(b"1")
    assert downloader.find_download(VIDEO_ID, str(tmp_path)) is None
    (tmp_path / f"{VIDEO_ID}.mp4").write_bytes(b"1")
    assert downloader.find_download(VIDEO_ID, str(tmp_path)).name == f"{VIDEO_ID}.mp4"
    assert downloader.find_download("../x", str(tmp_path)) is None


def test_the_downloads_folder_is_ignored_by_git_and_never_the_live_one_in_tests():
    root = Path(__file__).resolve().parents[3]
    lines = [l.strip() for l in (root / ".gitignore").read_text(encoding="utf8").splitlines()]
    assert "app/data/downloads/" in lines
    try:
        out = subprocess.run(["git", "check-ignore", "-q", "app/data/downloads/x.mp4"], cwd=root, capture_output=True)
        assert out.returncode == 0
    except FileNotFoundError:
        pass                                                                          # no git on the path: the .gitignore line is enough
    assert os.path.normcase(os.path.abspath(downloader.downloads_dir())) == os.path.normcase(os.path.abspath(ct.TEST_DOWNLOADS))
    assert os.path.normcase(os.path.abspath(ct.TEST_DOWNLOADS)) != os.path.normcase(ct.LIVE_DOWNLOADS)


# --- the stage in the queue worker -----------------------------------------------------------------------------------------

async def test_a_download_item_saves_the_file_and_records_the_run(client, seeded_video):
    await client.put("/api/settings/app", json={"download_default_format": "mp3", "download_default_quality": "720p"})
    run, calls = fake_ytdlp()
    item = await add_item(["download"])
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert (await get_item(item))["status"] == "done"
    assert (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp3").read_bytes() == b"x" * 10         # Settings: mp3 / 720p
    (args,) = calls
    assert args[-2:] == ["--", URL] and "-x" in args and args[args.index("--audio-quality") + 1] == "192K"
    run_row = await stage_of(client)
    assert run_row["status"] == "done" and run_row["meta"] == {"file": f"{VIDEO_ID}.mp3", "size": 10, "format": "mp3", "quality": "720p"}
    assert run_row["queue_item_id"] == item


async def test_the_default_is_mp4_best_and_the_download_runs_after_the_text_stages(client, seeded_video):
    order: list[str] = []

    async def cleanup(*a, **k):
        order.append("cleanup")
        return "Cleaned."

    run, calls = fake_ytdlp(on_run=lambda: order.append("download"))
    await client.put("/api/settings/cleanup", json={"model": "m"})
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    item = await add_item(["cleanup", "download"])
    with patch("services.text_cleaner.clean_text", cleanup), patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert order == ["cleanup", "download"]
    assert "bestvideo[ext=mp4]" in calls[0][calls[0].index("-f") + 1]
    assert (await get_item(item))["status"] == "done"


async def test_a_failed_download_ends_the_item_partial_with_the_reason_and_does_not_crash_it(client, seeded_video):
    run, _ = fake_ytdlp(returncode=1, stderr=b"ERROR: Video unavailable")
    item = await add_item(["download"])
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    row = await get_item(item)
    assert row["status"] == "partial" and "Download failed: yt-dlp failed: ERROR: Video unavailable" in row["error_message"]
    stage = await stage_of(client)
    assert stage["status"] == "failed" and "Video unavailable" in stage["error_text"]
    assert not os.listdir(ct.TEST_DOWNLOADS)


async def test_a_timeout_and_a_missing_file_have_their_own_messages(client, seeded_video):
    item = await add_item(["download"])
    with patch.object(downloader.subprocess, "run", fake_ytdlp(raises=subprocess.TimeoutExpired("yt-dlp", 890))[0]):
        await run_worker([item])
    assert "Download timed out" in (await get_item(item))["error_message"]
    await reset_queue()
    item = await add_item(["download"])
    with patch.object(downloader.subprocess, "run", fake_ytdlp(make_file=False)[0]):
        await run_worker([item])
    assert "No file was produced" in (await get_item(item))["error_message"]


async def test_a_stop_during_the_download_ends_the_item_skipped_and_the_run_cancelled(client, seeded_video):
    item = await add_item(["download"])
    run, _ = fake_ytdlp(on_run=lambda: ITEM_CANCEL.add(item))              # the Stop arrives while yt-dlp is running
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert (await get_item(item))["status"] == "skipped"
    assert (await stage_of(client))["status"] == "cancelled"


async def test_a_local_file_cannot_be_downloaded_and_says_so(client, seeded_video):
    from services import queue_service as q
    await q._run_download_stage(7, VIDEO_ID, "local://talk.mp3")
    stage = await stage_of(client)
    assert stage["status"] == "failed" and "not available for local files" in stage["error_text"]


async def test_a_link_that_is_not_an_https_youtube_link_is_refused_before_yt_dlp_runs(client, seeded_video):
    from services import queue_service as q
    run, calls = fake_ytdlp()
    with patch.object(downloader.subprocess, "run", run):
        await q._run_download_stage(7, VIDEO_ID, "http://example.com/watch?v=" + VIDEO_ID)
    assert calls == []
    assert "not a YouTube https link" in (await stage_of(client))["error_text"]


async def test_the_old_browser_download_endpoint_is_untouched_by_the_stage(client, seeded_video):
    assert re.search(r"/result/\{video_id\}/download", str([r.path for r in __import__("main").app.routes]))


# --- getting the saved file back --------------------------------------------------------------------------------------------

async def done_run(file, video_id=VIDEO_ID):
    """A finished download run naming `file`, as the worker writes it."""
    from models.database import AsyncSessionLocal
    from services import stage_runs
    async with AsyncSessionLocal() as db:
        await stage_runs.begin(db, video_id, "download")
        await stage_runs.finish(db, video_id, "download", meta={"file": file, "size": 1, "format": "mp4", "quality": "best"})
        await db.commit()


async def test_the_saved_file_is_served_by_video_id_with_its_name_and_type(client):
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp3").write_bytes(b"audio-bytes")
    await done_run(f"{VIDEO_ID}.mp3")
    r = await client.get(f"/api/downloads/{VIDEO_ID}")
    assert r.status_code == 200 and r.content == b"audio-bytes"
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert f'filename="{VIDEO_ID}.mp3"' in r.headers["content-disposition"]
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp3").unlink()
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp4").write_bytes(b"video-bytes")
    await done_run(f"{VIDEO_ID}.mp4")                                                 # the newest done run decides
    assert (await client.get(f"/api/downloads/{VIDEO_ID}")).headers["content-type"].startswith("video/mp4")


@pytest.mark.parametrize("asked", ["nothingHere1", "..", "...", "a.b", "%2e%2e", "x" * 80, "id;rm", "C:"])
async def test_no_file_and_no_odd_ids_give_404_and_never_a_path(client, asked):
    (Path(ct.TEST_DOWNLOADS) / "secret.txt").write_bytes(b"not for the web")
    r = await client.get(f"/api/downloads/{asked}")
    assert r.status_code in (404, 422) and b"not for the web" not in r.content


async def test_a_file_in_the_folder_that_no_done_run_names_is_not_served(client):
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp4").write_bytes(b"stray")                # no run at all
    assert (await client.get(f"/api/downloads/{VIDEO_ID}")).status_code == 404
    await done_run(f"{VIDEO_ID}.mp3")                                                   # a run names a file that is not there
    assert (await client.get(f"/api/downloads/{VIDEO_ID}")).status_code == 404


@pytest.mark.parametrize("name", ["{id}.f137.mp4", "{id}.mp4.part", "{id}.ytdl", "{id}.f251.webm", "{id}.temp.mp4", "../secret.txt", "{id}.exe"])
async def test_fragments_and_odd_names_are_not_served_even_if_a_run_names_them(client, name):
    real = name.format(id=VIDEO_ID)
    if "/" not in real:
        (Path(ct.TEST_DOWNLOADS) / real).write_bytes(b"fragment")
    (Path(ct.TEST_DOWNLOADS).parent / "secret.txt").write_bytes(b"not for the web")
    await done_run(real)
    r = await client.get(f"/api/downloads/{VIDEO_ID}")
    assert r.status_code == 404 and b"fragment" not in r.content and b"not for the web" not in r.content
    (Path(ct.TEST_DOWNLOADS).parent / "secret.txt").unlink()


async def test_a_half_written_file_is_not_served(client):
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp4.part").write_bytes(b"half")
    await done_run(f"{VIDEO_ID}.mp4")
    assert (await client.get(f"/api/downloads/{VIDEO_ID}")).status_code == 404


# --- leftovers (review: Low-Medium) --------------------------------------------------------------------------------------------

def folder_names():
    return sorted(os.listdir(ct.TEST_DOWNLOADS))


async def test_a_stop_deletes_the_file_this_run_produced(client, seeded_video):
    item = await add_item(["download"])
    run, _ = fake_ytdlp(on_run=lambda: ITEM_CANCEL.add(item), fragments=["{id}.f137.mp4"])
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert (await get_item(item))["status"] == "skipped"
    assert folder_names() == []                                           # neither the finished file nor the fragment


async def test_a_stop_keeps_a_good_file_from_an_earlier_run(client, seeded_video):
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp3").write_bytes(b"earlier good file")
    await done_run(f"{VIDEO_ID}.mp3")
    item = await add_item(["download"])
    run, _ = fake_ytdlp(on_run=lambda: ITEM_CANCEL.add(item))             # mp4 by default: a different name from the earlier mp3
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert folder_names() == [f"{VIDEO_ID}.mp3"]
    assert (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp3").read_bytes() == b"earlier good file"


async def test_a_timeout_removes_the_fragments(client, seeded_video):
    item = await add_item(["download"])
    run, _ = fake_ytdlp(raises=subprocess.TimeoutExpired("yt-dlp", 890), fragments=["{id}.mp4.part", "{id}.f137.mp4", "{id}.ytdl"])
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert "Download timed out" in (await get_item(item))["error_message"]
    assert folder_names() == []


async def test_a_crash_removes_the_fragments_and_keeps_the_earlier_good_file(client, seeded_video):
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp3").write_bytes(b"earlier good file")
    await done_run(f"{VIDEO_ID}.mp3")
    item = await add_item(["download"])
    run, _ = fake_ytdlp(returncode=1, stderr=b"ERROR: boom", fragments=["{id}.f251.webm", "{id}.f137.mp4.part"])
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert (await get_item(item))["status"] == "partial"
    assert folder_names() == [f"{VIDEO_ID}.mp3"]


async def test_an_unexpected_error_also_cleans_up(client, seeded_video):
    item = await add_item(["download"])
    run, _ = fake_ytdlp(raises=RuntimeError("disk exploded"), fragments=["{id}.mp4.part"])
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert (await get_item(item))["status"] == "partial" and folder_names() == []


async def test_stale_fragments_of_an_earlier_crash_are_removed_at_the_start_and_only_the_named_file_stays(client, seeded_video):
    for stale in (f"{VIDEO_ID}.f137.mp4", f"{VIDEO_ID}.mp4.part", f"{VIDEO_ID}.ytdl"):
        (Path(ct.TEST_DOWNLOADS) / stale).write_bytes(b"old")
    (Path(ct.TEST_DOWNLOADS) / "otherVideo01.mp4").write_bytes(b"someone else's file")      # other videos are never touched
    item = await add_item(["download"])
    run, _ = fake_ytdlp(fragments=["{id}.f251.webm"])                                          # and a leftover of this very run
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert (await get_item(item))["status"] == "done"
    assert folder_names() == sorted(["otherVideo01.mp4", f"{VIDEO_ID}.mp4"])


# --- item 13: no subtitles, but the download was asked for --------------------------------------------------------------------

NEW = "noSubs00001"
NEW_URL = f"https://www.youtube.com/watch?v={NEW}"


def no_subtitles(*a, **k):
    return SimpleNamespace(success=False, error_message="This video has no subtitles available.", available_languages=None,
                           error_type="x", subtitles=[], metadata=None, language=None)


async def test_no_subtitles_still_downloads_and_the_item_ends_partial_with_both_facts(client):
    run, calls = fake_ytdlp()
    item = await add_item(["extract", "cleanup", "download"], url=NEW_URL, video_id=NEW)
    cleanups: list[int] = []

    async def cleanup(*a, **k):
        cleanups.append(1)
        return "x"

    with patch("services.subtitle_extractor.extract_subtitles", no_subtitles), patch("services.text_cleaner.clean_text", cleanup), \
            patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    row = await get_item(item)
    assert row["status"] == "partial"
    assert "Subtitles failed: This video has no subtitles available." in row["error_message"]
    assert f"the video was downloaded ({NEW}.mp4" in row["error_message"]
    assert (Path(ct.TEST_DOWNLOADS) / f"{NEW}.mp4").exists() and len(calls) == 1 and calls[0][-1] == NEW_URL
    assert cleanups == []                                                  # the text stages did not run: there is no text
    from tests.baseline_helpers import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        runs = dict((await db.execute(text("SELECT stage, status FROM processing_stages WHERE video_id = :v"), {"v": NEW})).fetchall())
    assert runs == {"extract": "failed", "download": "done"}
    await client.delete(f"/api/queue/{row['id']}")


async def test_no_subtitles_and_a_failing_download_report_both_failures(client):
    item = await add_item(["extract", "download"], url=NEW_URL, video_id=NEW)
    with patch("services.subtitle_extractor.extract_subtitles", no_subtitles), \
            patch.object(downloader.subprocess, "run", fake_ytdlp(returncode=1, stderr=b"ERROR: private video")[0]):
        await run_worker([item])
    row = await get_item(item)
    assert row["status"] == "partial"
    assert "Subtitles failed: This video has no subtitles available." in row["error_message"]
    assert "Download failed: yt-dlp failed: ERROR: private video" in row["error_message"]
    assert "was downloaded" not in row["error_message"]


async def test_without_the_download_stage_no_subtitles_still_fails_the_item_as_before(client):
    run, calls = fake_ytdlp()
    item = await add_item(["extract", "cleanup"], url=NEW_URL, video_id=NEW)
    with patch("services.subtitle_extractor.extract_subtitles", no_subtitles), patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    row = await get_item(item)
    assert row["status"] == "failed" and "no subtitles" in row["error_message"].lower()
    assert calls == []


async def test_a_stop_during_the_extract_still_stops_everything_and_downloads_nothing(client):
    run, calls = fake_ytdlp()
    item = await add_item(["extract", "download"], url=NEW_URL, video_id=NEW)

    def stopped_extract(*a, **k):
        ITEM_CANCEL.add(item)
        return no_subtitles()

    with patch("services.subtitle_extractor.extract_subtitles", stopped_extract), patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert (await get_item(item))["status"] == "skipped" and calls == []


# --- reason codes and the texts shown (review: Low) --------------------------------------------------------------------------------

JS_WARNING = ("WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is enabled by default; to use another "
              "runtime add  --js-runtimes RUNTIME[:PATH] to your command/config. YouTube extraction without a JS runtime has been "
              "deprecated, and some formats may be missing. See  https://github.com/yt-dlp/yt-dlp/wiki/EJS  for details on installing one")


def test_the_yt_dlp_javascript_warning_is_not_part_of_the_shown_error():
    stderr = f"{JS_WARNING}\nERROR: [youtube] dQw4w9WgXcQ: Video unavailable. This video has been removed by the uploader\n"
    shown = downloader.clean_ytdlp_error(stderr)
    assert shown == "ERROR: [youtube] dQw4w9WgXcQ: Video unavailable. This video has been removed by the uploader"
    assert "JavaScript" not in shown


def test_without_an_error_line_the_last_lines_that_are_not_warnings_are_shown():
    stderr = f"{JS_WARNING}\n[download] Destination: x.mp4\n[download]  12.0% of 3.00MiB\nSomething odd happened\n"
    shown = downloader.clean_ytdlp_error(stderr)
    assert "JavaScript" not in shown and shown.endswith("Something odd happened")
    assert downloader.clean_ytdlp_error(JS_WARNING) == "unknown error"                        # only a warning: nothing worth showing
    assert downloader.clean_ytdlp_error("") == "unknown error"
    assert len(downloader.clean_ytdlp_error("ERROR: " + "x" * 5000)) <= 500


async def test_the_warning_does_not_reach_the_queue_row_or_the_stage_table(client, seeded_video):
    item = await add_item(["download"])
    stderr = f"{JS_WARNING}\nERROR: unable to download video data: HTTP Error 404: Not Found\n".encode()
    with patch.object(downloader.subprocess, "run", fake_ytdlp(returncode=1, stderr=stderr)[0]):
        await run_worker([item])
    row = await get_item(item)
    assert "HTTP Error 404" in row["error_message"] and "JavaScript" not in row["error_message"]
    stage = await stage_of(client)
    assert "JavaScript" not in stage["error_text"]
    assert stage["error_code"] == "download_failed"                                          # not not_found


@pytest.mark.parametrize("text,code", [
    ("yt-dlp failed: ERROR: unable to download video data: HTTP Error 404: Not Found", "download_failed"),
    ("yt-dlp failed: ERROR: [youtube] dQw4w9WgXcQ: Video unavailable. This video is private", "download_failed"),
    ("yt-dlp failed: ERROR: unable to download video data: <urlopen error [Errno 111] Connection refused>", "download_failed"),
    ("yt-dlp failed: ERROR: [youtube] x: Sign in to confirm you're not a bot", "download_failed"),
    ("No file was produced (a video over 4G is skipped)", "download_failed"),
    ("Download timed out", "timeout"),
    ("Cancelled", "cancelled"),
    ("Download is not available for local files", "download_failed"),
])
def test_a_failed_download_gets_the_download_code_from_real_texts(text, code):
    assert classify_error(text, "download") == code


def test_the_same_texts_without_the_stage_keep_their_old_codes():
    """The stage argument is what stops them being read as an Ollama / model problem."""
    assert classify_error("yt-dlp failed: ERROR: HTTP Error 404: Not Found") == "not_found"
    assert classify_error("No file was produced (a video over 4G is skipped)") == "empty_answer"
    assert classify_error("yt-dlp failed: ERROR: <urlopen error Connection refused>") == "ollama_down"


def test_download_failed_is_a_known_code():
    assert "download_failed" in ERROR_CODES


async def test_a_run_that_fails_with_no_file_has_the_download_code(client, seeded_video):
    item = await add_item(["download"])
    with patch.object(downloader.subprocess, "run", fake_ytdlp(make_file=False)[0]):
        await run_worker([item])
    assert (await stage_of(client))["error_code"] == "download_failed"


# --- a download for a video that is already in History (review: Low, behaviour) ----------------------------------------------------

async def test_a_download_only_item_can_be_queued_by_id_and_runs(client, seeded_video):
    r = await client.post("/api/queue/bulk", json={"video_ids": [VIDEO_ID], "pipeline_stages": ["download"]})
    assert r.status_code == 200 and r.json()["added"] == 1 and r.json()["duplicates"] == []
    (item_row,) = (await client.get("/api/queue")).json()["items"]
    assert item_row["pipeline_stages"] == ["download"] and item_row["video_id"] == VIDEO_ID and item_row["url"] == URL
    run, calls = fake_ytdlp()
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item_row["id"]])
    assert (await get_item(item_row["id"]))["status"] == "done"
    assert (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp4").exists() and calls[0][-1] == URL
    assert (await stage_of(client))["status"] == "done"


async def test_a_second_download_request_is_a_duplicate_but_other_stages_still_go_in(client, seeded_video):
    await client.post("/api/queue/bulk", json={"video_ids": [VIDEO_ID], "pipeline_stages": ["download"]})
    again = (await client.post("/api/queue/bulk", json={"video_ids": [VIDEO_ID], "pipeline_stages": ["download"]})).json()
    assert again["added"] == 0 and again["duplicates"] == [VIDEO_ID]
    assert again["duplicate_details"][0]["reason"] == "in_queue" and again["duplicate_details"][0]["stages"] == ["download"]
    mixed = (await client.post("/api/queue/bulk", json={"video_ids": [VIDEO_ID], "pipeline_stages": ["summary", "download"]})).json()
    assert mixed["added"] == 1                                              # the summary goes in; the download is already covered


async def test_a_queued_summary_does_not_block_a_download(client, seeded_video):
    await client.post("/api/queue/bulk", json={"video_ids": [VIDEO_ID], "pipeline_stages": ["mindmap"]})
    r = (await client.post("/api/queue/bulk", json={"video_ids": [VIDEO_ID], "pipeline_stages": ["download"]})).json()
    assert r["added"] == 1 and r["duplicates"] == []                          # download has no place in the cleanup < summary < mind map order


async def test_the_other_stages_are_still_refused_for_a_result_in_history(client, seeded_video):
    for stages in (["extract"], ["transcribe"], ["download", "extract"], ["rm -rf"], []):
        r = await client.post("/api/queue/bulk", json={"video_ids": [VIDEO_ID], "pipeline_stages": stages})
        assert r.status_code == 400, stages
        assert "download" in r.json()["detail"]["message"] or stages == []
