"""Downloading a video or its audio with yt-dlp (the browser download buttons and the queue's download stage)."""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path


def mp4_format_spec(quality: str) -> str:
    if quality == "best":
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    h = quality.rstrip("p")
    return (
        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={h}]+bestaudio/best[height<={h}]"
    )


# --- the queue's download stage (NS-17 items 12 / 13) -----------------------------------------------------------------------
# The file is written on the server, in data/downloads, named after the video id (a YouTube id: letters, digits, "-" and "_"; the
# title-based names are NS-23). Nothing about the file's place or name, and no program, comes from a request.

MAX_FILESIZE = "4G"          # yt-dlp skips a bigger file instead of filling the disk
TIMEOUT_SECONDS = 900        # the same limit as the browser download
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_AUDIO_QUALITY = {"best": "320K", "high": "192K", "low": "128K"}
_PARTIAL_SUFFIXES = (".part", ".ytdl", ".temp")


class DownloadFailed(RuntimeError):
    """The download did not produce a file; the message says why (it is shown on the queue row and the result page)."""


def downloads_dir() -> str:
    """Where downloaded files are saved (data/downloads next to the backend folder; gitignored)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/downloads"))


def safe_base_name(video_id: str) -> str:
    """The file name base: the video id, and only if it is made of safe characters (no path, no dots, no spaces)."""
    if not video_id or not _SAFE_ID.match(video_id):
        raise DownloadFailed("Cannot download: the video id is not a plain YouTube id")
    return video_id


def build_args(ytdlp_cmd: list[str], url: str, video_id: str, out_dir: str, fmt: str, quality: str,
               cookies_path: str | None) -> list[str]:
    """The yt-dlp command as an argument list (never a shell string), `--` before the URL. `url` must already be the canonical
    https YouTube link (validate_youtube_url)."""
    base = safe_base_name(video_id)
    template = str(Path(out_dir) / f"{base}.%(ext)s").replace("%(ext)s", "\0").replace("%", "%%").replace("\0", "%(ext)s")
    if fmt == "mp3":
        args = ytdlp_cmd + ["--no-playlist", "--max-filesize", MAX_FILESIZE, "-x", "--audio-format", "mp3",
                            "--audio-quality", _AUDIO_QUALITY.get(quality, "192K"), "-o", template]
    else:
        args = ytdlp_cmd + ["--no-playlist", "--max-filesize", MAX_FILESIZE, "-f", mp4_format_spec(quality),
                            "--merge-output-format", "mp4", "-o", template]
    if cookies_path and Path(cookies_path).exists():
        args += ["--cookies", cookies_path]
    return args + ["--", url]


def find_download(video_id: str, folder: str | None = None) -> Path | None:
    """The finished file of this video in the downloads folder (not a half-written one), or None."""
    try:
        base = safe_base_name(video_id)
    except DownloadFailed:
        return None
    root = Path(folder or downloads_dir())
    if not root.is_dir():
        return None
    found = [p for p in root.iterdir() if p.is_file() and p.name.startswith(base + ".") and not p.name.endswith(_PARTIAL_SUFFIXES)]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def _run_blocking(args: list[str], video_id: str, out_dir: str) -> Path:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(args, capture_output=True, timeout=TIMEOUT_SECONDS - 10)
    except subprocess.TimeoutExpired as exc:
        raise DownloadFailed("Download timed out") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace")[-500:].strip() if proc.stderr else "unknown error"
        raise DownloadFailed(f"yt-dlp failed: {err}")
    out = find_download(video_id, out_dir)
    if out is None:
        raise DownloadFailed(f"No file was produced (a video over {MAX_FILESIZE} is skipped)")
    return out


async def download_file(url: str, video_id: str, fmt: str, quality: str, ytdlp_cmd: list[str], cookies_path: str | None,
                        out_dir: str | None = None) -> Path:
    """Download `url` (canonical https YouTube link) into the downloads folder as <video_id>.<ext>; returns the file."""
    folder = out_dir or downloads_dir()
    args = build_args(ytdlp_cmd, url, video_id, folder, fmt, quality, cookies_path)
    try:
        return await asyncio.wait_for(asyncio.to_thread(_run_blocking, args, video_id, folder), timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise DownloadFailed("Download timed out") from exc
