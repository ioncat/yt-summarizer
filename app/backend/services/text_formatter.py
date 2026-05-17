from __future__ import annotations

from services.subtitle_extractor import SubtitleEntry

PARAGRAPH_GAP_SECONDS = 4


def _timestamp_to_seconds(ts: str) -> int:
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        pass
    return 0


def _find_overlap(s1: str, s2: str) -> int:
    """Length of longest suffix of s1 that equals a prefix of s2."""
    limit = min(len(s1), len(s2))
    for n in range(limit, 0, -1):
        if s1.endswith(s2[:n]):
            return n
    return 0


def _dedup_segments(entries: list[SubtitleEntry]) -> list[tuple[int, str]]:
    """Remove rolling-window overlaps. Returns list of (seconds, text) pairs."""
    texts = [e.text for e in entries]
    seconds = [_timestamp_to_seconds(e.timestamp) for e in entries]
    segments: list[tuple[int, str]] = []
    for i, text in enumerate(texts):
        unique = text if i == 0 else text[_find_overlap(texts[i - 1], text):].strip()
        if unique:
            segments.append((seconds[i], unique))
    return segments


def _format_with_chapters(
    segments: list[tuple[int, str]],
    chapters: list[dict],
) -> tuple[str, int]:
    """Group segments into creator-defined chapters. Returns (text, paragraph_count)."""
    # Sort chapters by start_time (defensive)
    sorted_chapters = sorted(chapters, key=lambda c: c["start_time"])

    # Assign each segment to a chapter bucket
    buckets: list[list[str]] = [[] for _ in sorted_chapters]
    orphans: list[str] = []  # segments before first chapter or between chapters

    for sec, text in segments:
        assigned = False
        for i, ch in enumerate(sorted_chapters):
            if ch["start_time"] <= sec < ch["end_time"]:
                buckets[i].append(text)
                assigned = True
                break
        if not assigned:
            # Segment falls outside all chapters (gaps or after last chapter end)
            # Assign to nearest preceding chapter
            best = -1
            for i, ch in enumerate(sorted_chapters):
                if ch["start_time"] <= sec:
                    best = i
            if best >= 0:
                buckets[best].append(text)
            else:
                orphans.append(text)

    parts: list[str] = []

    # Orphans before first chapter (rare)
    if orphans:
        parts.append(" ".join(orphans))

    for i, ch in enumerate(sorted_chapters):
        chapter_text = " ".join(buckets[i]).strip()
        if not chapter_text:
            continue
        parts.append(f"## {ch['title']}\n\n{chapter_text}")

    return "\n\n".join(parts), len(parts)


def _format_with_gaps(
    segments: list[tuple[int, str]],
    paragraph_gap: int,
) -> tuple[str, int]:
    """Group segments into paragraphs by time gaps. Returns (text, paragraph_count)."""
    paragraphs: list[str] = []
    current: list[str] = [segments[0][1]]

    for i in range(1, len(segments)):
        gap = segments[i][0] - segments[i - 1][0]
        if gap >= paragraph_gap:
            paragraphs.append(" ".join(current))
            current = [segments[i][1]]
        else:
            current.append(segments[i][1])

    paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs), len(paragraphs)


def format_subtitles(
    entries: list[SubtitleEntry],
    chapters: list[dict] | None = None,
    paragraph_gap: int = PARAGRAPH_GAP_SECONDS,
) -> dict:
    if not entries:
        return {"formatted_text": "", "char_count": 0, "paragraph_count": 0, "has_chapters": False}

    segments = _dedup_segments(entries)

    if not segments:
        return {"formatted_text": "", "char_count": 0, "paragraph_count": 0, "has_chapters": False}

    if chapters:
        formatted_text, paragraph_count = _format_with_chapters(segments, chapters)
        has_chapters = True
    else:
        formatted_text, paragraph_count = _format_with_gaps(segments, paragraph_gap)
        has_chapters = False

    return {
        "formatted_text": formatted_text,
        "char_count": len(formatted_text),
        "paragraph_count": paragraph_count,
        "has_chapters": has_chapters,
    }
