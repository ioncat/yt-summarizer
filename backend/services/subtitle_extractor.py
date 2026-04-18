import http.cookiejar
import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from enum import Enum

YTDLP_PATH = os.environ.get("YTDLP_PATH", "yt-dlp")


class SubtitleSourceType(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"


class ExtractionErrorType(str, Enum):
    INVALID_URL = "invalid_url"
    NO_SUBTITLES = "no_subtitles"
    LANGUAGE_NOT_AVAILABLE = "language_not_available"
    VIDEO_UNAVAILABLE = "video_unavailable"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class SubtitleEntry:
    timestamp: str
    text: str


@dataclass
class VideoMetadata:
    video_id: str
    title: str | None
    author: str | None
    duration: int | None
    channel_id: str | None
    channel_name: str | None
    upload_date: str | None
    view_count: int | None
    description: str | None
    thumbnail_url: str | None


@dataclass
class ExtractionResult:
    success: bool
    metadata: VideoMetadata | None = None
    subtitles: list[SubtitleEntry] | None = None
    language: str | None = None
    source_type: SubtitleSourceType | None = None
    available_languages: list[str] | None = None
    error_type: ExtractionErrorType | None = None
    error_message: str | None = None


SUPPORTED_LANGUAGES = ["ru", "en", "uk"]


def extract_video_id(url: str) -> str | None:
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _make_opener(cookies_path: str | None) -> urllib.request.OpenerDirector:
    jar = http.cookiejar.MozillaCookieJar()
    if cookies_path and os.path.exists(cookies_path):
        jar.load(cookies_path, ignore_discard=True, ignore_expires=True)
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _run_ytdlp(args: list[str], cookies_path: str | None, timeout: int = 30) -> tuple[str, str, int]:
    cmd = [
        YTDLP_PATH,
        "--no-warnings",
        "--js-runtimes", "node",
    ]
    if cookies_path and os.path.exists(cookies_path):
        cmd += ["--cookies", cookies_path]
    cmd += args

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return result.stdout, result.stderr, result.returncode


def _parse_vtt_to_entries(vtt_content: str) -> list[SubtitleEntry]:
    entries = []
    seen_texts: set[str] = set()
    lines = vtt_content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            timestamp = line.split("-->")[0].strip()
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                text_line = re.sub(r"<[^>]+>", "", lines[i]).strip()
                if text_line:
                    text_lines.append(text_line)
                i += 1
            text = " ".join(text_lines).strip()
            if text and text not in seen_texts:
                seen_texts.add(text)
                ts = timestamp[:8] if len(timestamp) >= 8 else timestamp
                entries.append(SubtitleEntry(timestamp=ts, text=text))
        else:
            i += 1
    return entries


def _build_metadata(info: dict) -> VideoMetadata:
    upload_date = info.get("upload_date")
    if upload_date and len(upload_date) == 8:
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return VideoMetadata(
        video_id=info.get("id", ""),
        title=info.get("title"),
        author=info.get("uploader"),
        duration=info.get("duration"),
        channel_id=info.get("channel_id"),
        channel_name=info.get("channel"),
        upload_date=upload_date,
        view_count=info.get("view_count"),
        description=info.get("description"),
        thumbnail_url=info.get("thumbnail"),
    )


def _get_available_languages(info: dict) -> list[str]:
    languages: set[str] = set()
    for key in ("subtitles", "automatic_captions"):
        languages.update(info.get(key, {}).keys())
    return sorted(languages)


def _find_subtitle_track(
    info: dict, language: str
) -> tuple[list | None, SubtitleSourceType | None]:
    manual = info.get("subtitles", {})
    auto = info.get("automatic_captions", {})
    if language in manual:
        return manual[language], SubtitleSourceType.MANUAL
    if language in auto:
        return auto[language], SubtitleSourceType.AUTO
    return None, None


def _classify_error(stderr: str) -> ExtractionResult:
    s = stderr.lower()
    if "private" in s:
        return ExtractionResult(success=False, error_type=ExtractionErrorType.VIDEO_UNAVAILABLE, error_message="This video is private.")
    if "has been removed" in s or "no longer available" in s:
        return ExtractionResult(success=False, error_type=ExtractionErrorType.VIDEO_UNAVAILABLE, error_message="This video is no longer available.")
    if "sign in" in s or "confirm" in s:
        return ExtractionResult(success=False, error_type=ExtractionErrorType.VIDEO_UNAVAILABLE, error_message="YouTube requires sign-in. Please update cookies.")
    if "429" in s or "too many requests" in s:
        return ExtractionResult(success=False, error_type=ExtractionErrorType.NETWORK_ERROR, error_message="YouTube rate limit reached. Please try again later.")
    if "network" in s or "connection" in s:
        return ExtractionResult(success=False, error_type=ExtractionErrorType.NETWORK_ERROR, error_message="Network error. Please check your connection.")
    return ExtractionResult(success=False, error_type=ExtractionErrorType.VIDEO_UNAVAILABLE, error_message="This video is not accessible.")


def extract_subtitles(
    url: str, language: str = "en", cookies_path: str | None = None
) -> ExtractionResult:
    if not extract_video_id(url):
        return ExtractionResult(
            success=False,
            error_type=ExtractionErrorType.INVALID_URL,
            error_message="Invalid YouTube URL.",
        )

    try:
        # Step 1: get metadata via yt-dlp (no download)
        stdout, stderr, code = _run_ytdlp(
            ["--skip-download", "--print-json", url],
            cookies_path, timeout=30,
        )

        if not stdout.strip():
            return _classify_error(stderr)

        info = json.loads(stdout.strip())
        metadata = _build_metadata(info)
        available_languages = _get_available_languages(info)
        subtitle_formats, source_type = _find_subtitle_track(info, language)

        if not subtitle_formats:
            if not available_languages:
                return ExtractionResult(
                    success=False, metadata=metadata, available_languages=[],
                    error_type=ExtractionErrorType.NO_SUBTITLES,
                    error_message="This video has no subtitles available.",
                )
            return ExtractionResult(
                success=False, metadata=metadata, available_languages=available_languages,
                error_type=ExtractionErrorType.LANGUAGE_NOT_AVAILABLE,
                error_message=(
                    f"Subtitles not available in '{language}'. "
                    f"Available: {', '.join(available_languages[:10])}"
                ),
            )

        # Step 2: download VTT via urllib with cookies (no second yt-dlp call)
        vtt_url = next(
            (f["url"] for f in subtitle_formats if f.get("ext") == "vtt"),
            subtitle_formats[0].get("url") if subtitle_formats else None,
        )

        if not vtt_url:
            return ExtractionResult(
                success=False, metadata=metadata,
                error_type=ExtractionErrorType.UNKNOWN,
                error_message="Could not retrieve subtitle file URL.",
            )

        opener = _make_opener(cookies_path)
        req = urllib.request.Request(
            vtt_url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with opener.open(req, timeout=30) as response:
            vtt_content = response.read().decode("utf-8")

        entries = _parse_vtt_to_entries(vtt_content)

        return ExtractionResult(
            success=True,
            metadata=metadata,
            subtitles=entries,
            language=language,
            source_type=source_type,
            available_languages=available_languages,
        )

    except subprocess.TimeoutExpired:
        return ExtractionResult(
            success=False,
            error_type=ExtractionErrorType.TIMEOUT,
            error_message="Extraction timed out. Please try again.",
        )
    except Exception as e:
        return ExtractionResult(
            success=False,
            error_type=ExtractionErrorType.UNKNOWN,
            error_message=f"Unexpected error: {type(e).__name__}",
        )


def subtitles_to_json(entries: list[SubtitleEntry]) -> str:
    return json.dumps(
        [{"timestamp": e.timestamp, "text": e.text} for e in entries],
        ensure_ascii=False,
    )
