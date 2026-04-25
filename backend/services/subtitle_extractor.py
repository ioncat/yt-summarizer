import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum

from config import settings


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


def _run_ytdlp(args: list[str], cookies_path: str | None, ytdlp_path: str, timeout: int = 30) -> tuple[str, str, int]:
    cmd = [
        ytdlp_path,
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
    raw: list[SubtitleEntry] = []
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
                raw.append(SubtitleEntry(timestamp=ts, text=text))
        else:
            i += 1

    # YouTube auto-captions use a rolling window: same timestamp can appear
    # multiple times with progressively more text. Keep only the longest.
    entries: list[SubtitleEntry] = []
    i = 0
    while i < len(raw):
        j = i + 1
        while j < len(raw) and raw[j].timestamp == raw[i].timestamp:
            j += 1
        best = max(raw[i:j], key=lambda e: len(e.text))
        entries.append(best)
        i = j
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
    url: str, language: str = "en", cookies_path: str | None = None, ytdlp_path: str = "yt-dlp"
) -> ExtractionResult:
    if not extract_video_id(url):
        return ExtractionResult(
            success=False,
            error_type=ExtractionErrorType.INVALID_URL,
            error_message="Invalid YouTube URL.",
        )

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout, stderr, code = _run_ytdlp(
                [
                    "--skip-download",
                    "--print-json",
                    "--write-subs",
                    "--write-auto-subs",
                    "--sub-lang", language,
                    "--sub-format", "vtt",
                    "-o", os.path.join(tmpdir, "sub"),
                    url,
                ],
                cookies_path, ytdlp_path=ytdlp_path, timeout=60,
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

            vtt_content = None
            for fname in os.listdir(tmpdir):
                if fname.endswith(".vtt"):
                    with open(os.path.join(tmpdir, fname), encoding="utf-8") as f:
                        vtt_content = f.read()
                    break

            if not vtt_content:
                s = stderr.lower()
                if "429" in s or "too many requests" in s:
                    return ExtractionResult(
                        success=False, metadata=metadata,
                        error_type=ExtractionErrorType.NETWORK_ERROR,
                        error_message="YouTube rate limit reached. Please try again later.",
                    )
                # Language listed in metadata but VTT not downloaded (e.g. auto-translated)
                real_langs = [l for l in available_languages if not l.endswith("-orig")]
                if language not in real_langs:
                    display = real_langs or available_languages
                    return ExtractionResult(
                        success=False, metadata=metadata,
                        available_languages=display,
                        error_type=ExtractionErrorType.LANGUAGE_NOT_AVAILABLE,
                        error_message=(
                            f"Subtitles not available in '{language}'. "
                            f"Available: {', '.join(display[:10])}"
                        ),
                    )
                return ExtractionResult(
                    success=False, metadata=metadata,
                    error_type=ExtractionErrorType.UNKNOWN,
                    error_message="Could not download subtitle file.",
                )

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
