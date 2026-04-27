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


def format_subtitles(
    entries: list[SubtitleEntry], paragraph_gap: int = PARAGRAPH_GAP_SECONDS
) -> dict:
    if not entries:
        return {"formatted_text": "", "char_count": 0, "paragraph_count": 0}

    texts = [e.text for e in entries]
    seconds = [_timestamp_to_seconds(e.timestamp) for e in entries]

    # Remove rolling-window overlaps between consecutive entries
    segments: list[tuple[int, str]] = []
    for i, text in enumerate(texts):
        unique = text if i == 0 else text[_find_overlap(texts[i - 1], text):].strip()
        if unique:
            segments.append((seconds[i], unique))

    if not segments:
        return {"formatted_text": "", "char_count": 0, "paragraph_count": 0}

    # Group into paragraphs by time gaps between entries
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

    formatted_text = "\n\n".join(paragraphs)
    return {
        "formatted_text": formatted_text,
        "char_count": len(formatted_text),
        "paragraph_count": len(paragraphs),
    }
