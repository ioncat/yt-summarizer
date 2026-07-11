"""
Tests for GET /api/history.
"""
import pytest
from models.models import Video, SubtitleFormatted


async def _seed_n_videos(db_session, n: int, prefix: str = "hist"):
    """Seed n videos directly into the test DB."""
    videos = []
    for i in range(n):
        vid_id = f"{prefix}_{i:04d}XX"[:11]
        v = Video(
            url=f"https://www.youtube.com/watch?v={vid_id}",
            video_id=vid_id,
            title=f"History Video {i}",
            author="Test Author",
        )
        db_session.add(v)
        await db_session.flush()
        fmt = SubtitleFormatted(
            video_id=v.id,
            language="ru",
            formatted_text=f"Content of video {i}",
            processing_status="success",
        )
        db_session.add(fmt)
        videos.append(v)
    await db_session.commit()
    return videos


@pytest.mark.asyncio
async def test_history_empty_returns_items_list(client):
    r = await client.get("/api/history")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data or isinstance(data, list)


@pytest.mark.asyncio
async def test_history_pagination(client, db_session):
    videos = await _seed_n_videos(db_session, 25, prefix="pgtest")

    r1 = await client.get("/api/history?page=1")
    assert r1.status_code == 200
    data = r1.json()
    items = data["items"] if "items" in data else data
    assert len(items) <= 20  # page size

    r2 = await client.get("/api/history?page=2")
    assert r2.status_code == 200

    # Cleanup
    for v in videos:
        fmts = await db_session.execute(
            __import__("sqlalchemy").select(SubtitleFormatted).where(SubtitleFormatted.video_id == v.id)
        )
        for fmt in fmts.scalars().all():
            await db_session.delete(fmt)
        await db_session.delete(v)
    await db_session.commit()


@pytest.mark.asyncio
async def test_history_search(client, db_session):
    from sqlalchemy import select

    v = Video(
        url="https://www.youtube.com/watch?v=srchTest001",
        video_id="srchTest001",
        title="Python Tutorial Advanced",
        author="Coding Channel",
    )
    db_session.add(v)
    await db_session.flush()
    fmt = SubtitleFormatted(video_id=v.id, language="ru", formatted_text="content", processing_status="success")
    db_session.add(fmt)
    await db_session.commit()

    r = await client.get("/api/history?search=Python+Tutorial")
    assert r.status_code == 200
    data = r.json()
    items = data["items"] if "items" in data else data
    titles = [i.get("title", "") for i in items]
    assert any("Python" in t for t in titles)

    # Cleanup
    await db_session.delete(fmt)
    await db_session.delete(v)
    await db_session.commit()


@pytest.mark.asyncio
async def test_history_favorites_filter(client, db_session):
    from sqlalchemy import select

    v = Video(
        url="https://www.youtube.com/watch?v=favTest0001",
        video_id="favTest0001",
        title="Favorite Video",
        author="Author",
        is_favorite=True,
    )
    db_session.add(v)
    await db_session.flush()
    fmt = SubtitleFormatted(video_id=v.id, language="ru", formatted_text="content", processing_status="success")
    db_session.add(fmt)
    await db_session.commit()

    r = await client.get("/api/history?favorites_only=true")
    assert r.status_code == 200
    data = r.json()
    items = data["items"] if "items" in data else data
    assert all(i.get("is_favorite") for i in items)

    # Cleanup
    await db_session.delete(fmt)
    await db_session.delete(v)
    await db_session.commit()
