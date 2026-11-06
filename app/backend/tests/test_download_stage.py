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


def fake_ytdlp(returncode=0, stderr=b"", make_file=True, on_run=None, raises=None):
    calls: list[list[str]] = []

    def run(args, capture_output=False, timeout=None):
        calls.append(list(args))
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
    await client.put("/api/settings/app", json={"download_default_format": "mp3", "download_default_quality": "low"})
    run, calls = fake_ytdlp()
    item = await add_item(["download"])
    with patch.object(downloader.subprocess, "run", run):
        await run_worker([item])
    assert (await get_item(item))["status"] == "done"
    assert (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp3").read_bytes() == b"x" * 10         # Settings: mp3 / low
    (args,) = calls
    assert args[-2:] == ["--", URL] and "-x" in args and args[args.index("--audio-quality") + 1] == "128K"
    run_row = await stage_of(client)
    assert run_row["status"] == "done" and run_row["meta"] == {"file": f"{VIDEO_ID}.mp3", "size": 10, "format": "mp3", "quality": "low"}
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

async def test_the_saved_file_is_served_by_video_id_with_its_name_and_type(client):
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp3").write_bytes(b"audio-bytes")
    r = await client.get(f"/api/downloads/{VIDEO_ID}")
    assert r.status_code == 200 and r.content == b"audio-bytes"
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert f'filename="{VIDEO_ID}.mp3"' in r.headers["content-disposition"]
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp3").unlink()
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp4").write_bytes(b"video-bytes")
    assert (await client.get(f"/api/downloads/{VIDEO_ID}")).headers["content-type"].startswith("video/mp4")


@pytest.mark.parametrize("asked", ["nothingHere1", "..", "...", "a.b", "%2e%2e", "x" * 80, "id;rm", "C:"])
async def test_no_file_and_no_odd_ids_give_404_and_never_a_path(client, asked):
    (Path(ct.TEST_DOWNLOADS) / "secret.txt").write_bytes(b"not for the web")
    r = await client.get(f"/api/downloads/{asked}")
    assert r.status_code in (404, 422) and b"not for the web" not in r.content


async def test_a_half_written_file_is_not_served(client):
    (Path(ct.TEST_DOWNLOADS) / f"{VIDEO_ID}.mp4.part").write_bytes(b"half")
    assert (await client.get(f"/api/downloads/{VIDEO_ID}")).status_code == 404
