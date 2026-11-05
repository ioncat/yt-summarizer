"""Search inside the stored texts of all videos (NS-29): transcript, cleaned text, summary, mind map.

Read-only. The match is case-insensitive and done in Python, because SQLite's LIKE/ILIKE does not
fold the case of Cyrillic. The position of a hit is a character offset into that text, so a caller
can read around it with get_result(parts=[...], offset=...).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import SubtitleFormatted, Video

MIN_QUERY_LEN = 3
SNIPPET_RADIUS = 80
# part name (as in get_result) -> column of subtitles_formatted
PART_COLUMNS = {
    "summary": "summary_text",
    "cleaned": "cleaned_text",
    "transcript": "formatted_text",
    "mindmap": "mindmap_text",
}


def _fold(text: str) -> str:
    """Lower-case that keeps every character at its index (so positions stay valid)."""
    low = text.lower()
    if len(low) == len(text):
        return low
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text)


def find_hits(text: str, query: str) -> tuple[int, int | None]:
    """(number of matches, position of the first one or None)."""
    folded, needle = _fold(text), _fold(query)
    first = folded.find(needle)
    if first < 0:
        return 0, None
    count, pos = 0, first
    while pos >= 0:
        count += 1
        pos = folded.find(needle, pos + len(needle))
    return count, first


def make_snippet(text: str, position: int, length: int) -> str:
    start = max(0, position - SNIPPET_RADIUS)
    end = min(len(text), position + length + SNIPPET_RADIUS)
    body = " ".join(text[start:end].split())
    return ("…" if start > 0 else "") + body + ("…" if end < len(text) else "")


async def search_texts(db: AsyncSession, query: str, limit: int = 20) -> dict:
    """Videos (newest first) whose texts contain `query`, at most `limit` of them.

    For every video: how many matches each part has, and the first match of each part.
    """
    videos = (await db.execute(
        select(Video.id, Video.video_id, Video.title, Video.author)
        .where(~Video.url.startswith("__pending__"))
        .order_by(Video.created_at.desc())
    )).all()

    found: list[dict] = []
    searched = 0
    for v in videos:
        searched += 1
        fmt = (await db.execute(
            select(*(getattr(SubtitleFormatted, col) for col in PART_COLUMNS.values()))
            .where(SubtitleFormatted.video_id == v.id)
            .order_by(SubtitleFormatted.created_at.desc())
            .limit(1)
        )).first()
        if not fmt:
            continue
        counts: dict[str, int] = {}
        matches: list[dict] = []
        for part, text in zip(PART_COLUMNS, fmt):
            if not text:
                continue
            count, first = find_hits(text, query)
            if count:
                counts[part] = count
                matches.append({"part": part, "position": first,
                                "snippet": make_snippet(text, first, len(query))})
        if counts:
            found.append({"video_id": v.video_id, "title": v.title, "author": v.author,
                          "counts": counts, "matches": matches})
            if len(found) >= limit:
                break
    return {"query": query, "videos": found, "searched": searched, "total_videos": len(videos)}
