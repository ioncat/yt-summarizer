import html
import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum

from config import settings

logger = logging.getLogger(__name__)


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
    chapters: list[dict] | None = None  # [{start_time, end_time, title}, ...]


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
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/|youtube\.com/live/)([a-zA-Z0-9_-]{11})",
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


def _vtt_ts_to_seconds(ts: str) -> int:
    """Convert VTT timestamp 'HH:MM:SS.mmm' to integer seconds."""
    parts = ts.split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return int(h * 3600 + m * 60 + s)


def _parse_vtt_chapters(vtt_content: str) -> list[dict] | None:
    """Extract chapter markers from VTT NOTE blocks.

    YouTube auto-captions embed chapter boundaries as:

        NOTE
        00:00:00.000 --> 00:05:30.000 Chapter Title In Video Language

    These reflect the video's actual language (unlike info["chapters"] from
    yt-dlp JSON which may be in English for auto-generated chapters).
    Returns a list of chapter dicts, or None if no chapter NOTEs found.
    """
    chapters: list[dict] = []
    lines = vtt_content.splitlines()
    i = 0
    chapter_re = re.compile(
        r'^(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\s+(.+)$'
    )
    while i < len(lines):
        if lines[i].strip() == "NOTE" and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            m = chapter_re.match(next_line)
            if m:
                start_str, end_str, title = m.groups()
                title = title.strip()
                # Skip VTT metadata NOTEs (e.g. "align:start position:0%")
                if title and not title.startswith("align:") and not title.startswith("position:"):
                    chapters.append({
                        "start_time": _vtt_ts_to_seconds(start_str),
                        "end_time": _vtt_ts_to_seconds(end_str),
                        "title": title,
                    })
        i += 1
    return chapters if chapters else None


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
            # Decode HTML entities (e.g. &nbsp;, &amp;) that some YouTube
            # auto-captions inject. Then collapse any resulting whitespace
            # runs (multiple &nbsp; → multiple spaces) to a single space.
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
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


_DESC_TS_RE = re.compile(r'^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)', re.MULTILINE)
_MIN_DESC_CHAPTERS = 2  # single timestamp in description is likely not a chapter list

# Script ranges for language-mismatch detection.
# Key = script name, value = set of BCP-47 language codes that use that script.
_SCRIPT_LANGUAGES: dict[str, set[str]] = {
    "cyrillic": {"ru", "uk", "bg", "sr", "mk", "kk", "be"},
    "cjk":      {"zh", "ja", "ko"},
    "arabic":   {"ar", "fa", "ur"},
    "hebrew":   {"he"},
    "greek":    {"el"},
}
_SCRIPT_RE: dict[str, re.Pattern] = {
    "cyrillic": re.compile(r'[Ѐ-ӿ]'),
    "cjk":      re.compile(r'[一-鿿぀-ヿ가-힯]'),
    "arabic":   re.compile(r'[؀-ۿ]'),
    "hebrew":   re.compile(r'[֐-׿]'),
    "greek":    re.compile(r'[Ͱ-Ͽ]'),
}


def _detect_script(text: str) -> str:
    """Return dominant script name ('cyrillic', 'cjk', 'arabic', 'latin', etc.)."""
    for name, pattern in _SCRIPT_RE.items():
        if pattern.search(text):
            return name
    return "latin"


def _expected_script(language: str) -> str | None:
    """Return expected script name for a BCP-47 language code, or None if unknown."""
    lang_base = language.split("-")[0].lower()
    for script, langs in _SCRIPT_LANGUAGES.items():
        if lang_base in langs:
            return script
    return None  # Latin or unknown — no strict check


def _desc_ts_to_seconds(ts: str) -> int:
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return int(parts[0]) * 60 + int(parts[1])


def _parse_description_chapters(description: str, duration: int | None) -> list[dict] | None:
    """Parse chapter timecodes from video description.

    Authors write timestamps in their own language in the description — YouTube
    does NOT translate description text. This makes it the only reliable source
    for chapter titles in the video's original language.

    Returns None if fewer than _MIN_DESC_CHAPTERS timecodes found (not a chapter list).
    """
    if not description:
        return None
    matches = _DESC_TS_RE.findall(description)
    if len(matches) < _MIN_DESC_CHAPTERS:
        return None

    chapters = sorted(
        [{"start_time": _desc_ts_to_seconds(ts), "end_time": 0, "title": title.strip()}
         for ts, title in matches],
        key=lambda c: c["start_time"],
    )
    # Infer end_time from next chapter's start; last chapter ends at video duration
    for i in range(len(chapters) - 1):
        chapters[i]["end_time"] = chapters[i + 1]["start_time"]
    chapters[-1]["end_time"] = int(duration) if duration else chapters[-1]["start_time"] + 300

    return chapters


def _build_metadata(info: dict) -> VideoMetadata:
    upload_date = info.get("upload_date")
    if upload_date and len(upload_date) == 8:
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

    video_id = info.get("id", "unknown")
    raw_chapters = info.get("chapters")
    yt_chapters: list[dict] | None = None
    if raw_chapters:
        yt_chapters = [
            {
                "start_time": int(ch.get("start_time", 0)),
                "end_time": int(ch.get("end_time", 0)),
                "title": ch.get("title", ""),
            }
            for ch in raw_chapters
        ]

    # Prefer description timecodes — they are in the author's original language.
    # YouTube translates info["chapters"] to the API request language (usually English).
    desc_chapters = _parse_description_chapters(
        info.get("description") or "", info.get("duration")
    )

    if desc_chapters:
        chapters = desc_chapters
        if yt_chapters and abs(len(desc_chapters) - len(yt_chapters)) > 2:
            logger.warning(
                "[CHAPTER_SOURCE] video=%s: description chapters (%d) vs YouTube chapters (%d) "
                "count mismatch >2 — description parsing may be unreliable for this video.",
                video_id, len(desc_chapters), len(yt_chapters),
            )
    elif yt_chapters:
        chapters = yt_chapters
        logger.warning(
            "[CHAPTER_SOURCE] video=%s: no timecodes in description, falling back to "
            "YouTube API chapters (titles may be translated to English). "
            "If chapter headings appear in wrong language, description parsing failed.",
            video_id,
        )
    else:
        chapters = None

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
        chapters=chapters,
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


def _detect_language(info: dict) -> str:
    """Detect original video language from yt-dlp metadata.

    Priority:
    1. Key ending in '-orig' in automatic_captions → strip suffix (most reliable)
    2. First key in subtitles (manually uploaded captions)
    3. First key in automatic_captions
    4. Top-level 'language' field
    5. Fallback 'ru'
    """
    auto = info.get("automatic_captions", {})
    manual = info.get("subtitles", {})

    for key in auto:
        if key.endswith("-orig"):
            return key[:-5]

    if manual:
        return next(iter(manual))

    if auto:
        first = next(iter(auto))
        return first

    lang = info.get("language")
    if lang:
        return lang

    return "ru"


def _fetch_metadata(url: str, cookies_path: str | None, ytdlp_path: str) -> tuple[dict | None, str]:
    """Lightweight metadata-only yt-dlp call (no subtitle download)."""
    stdout, stderr, code = _run_ytdlp(
        ["--no-playlist", "--skip-download", "--print-json", url],
        cookies_path, ytdlp_path=ytdlp_path, timeout=30,
    )
    if not stdout.strip():
        return None, stderr
    try:
        return json.loads(stdout.strip()), stderr
    except json.JSONDecodeError:
        return None, stderr


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
    url: str, language: str = "auto", cookies_path: str | None = None, ytdlp_path: str = "yt-dlp"
) -> ExtractionResult:
    if not extract_video_id(url):
        return ExtractionResult(
            success=False,
            error_type=ExtractionErrorType.INVALID_URL,
            error_message="Invalid YouTube URL.",
        )

    # Auto-detect language: lightweight metadata call first, then full extraction
    if language == "auto":
        info, stderr = _fetch_metadata(url, cookies_path, ytdlp_path)
        if info is None:
            return _classify_error(stderr)
        language = _detect_language(info)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout, stderr, code = _run_ytdlp(
                [
                    "--no-playlist",
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

            # Override JSON chapters with VTT NOTE chapters when available.
            # VTT NOTE blocks embed chapter titles from the subtitle stream
            # which reflects the video's actual language, whereas info["chapters"]
            # from yt-dlp JSON can be English for YouTube auto-generated chapters.
            vtt_chapters = _parse_vtt_chapters(vtt_content)
            if vtt_chapters:
                metadata.chapters = vtt_chapters

            # Language-mismatch check: chapter title script vs subtitle language.
            # Fires when chapter headings are in a different script than the video
            # language — most commonly English titles on a non-Latin-script video.
            if metadata.chapters:
                title_text = " ".join(c["title"] for c in metadata.chapters)
                title_script = _detect_script(title_text)
                exp_script = _expected_script(language)
                if exp_script and title_script != exp_script:
                    logger.warning(
                        "[CHAPTER_SOURCE] video=%s: chapter titles are in %s script "
                        "but subtitle language is '%s' (expected %s script). "
                        "Headings will appear in wrong language throughout the pipeline "
                        "(formatted_text → cleaned_text → summary → mindmap).",
                        metadata.video_id, title_script, language, exp_script,
                    )

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
