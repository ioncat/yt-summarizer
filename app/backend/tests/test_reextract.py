"""
Tests for POST /api/result/{video_id}/reextract.

Covers:
- 404 for unknown video
- 200 + status=reextracting for a normal YouTube video
- 422 when a local:// video's upload file is absent from disk
"""
import asyncio
import pytest
import pytest_asyncio
from unittest.mock import patch


@pytest_asyncio.fixture
async def seeded_local_video(db_session):
    """Insert a video whose URL is local:// with NO matching file on disk."""
    from models.models import Video, SubtitleFormatted

    video_id = "file-testlocalvid"
    video = Video(
        url="local://nonexistent_audio.mp3",
        video_id=video_id,
        title="Local Test File",
        author=None,
        duration=60,
    )
    db_session.add(video)
    await db_session.flush()

    fmt = SubtitleFormatted(
        video_id=video.id,
        language="ru",
        formatted_text="Test transcript text.",
        text_length=20,
        processing_status="success",
        subtitle_source="transcript",
    )
    db_session.add(fmt)
    await db_session.commit()

    yield {"video_id": video_id, "db_id": video.id, "fmt_id": fmt.id}

    await db_session.delete(fmt)
    await db_session.delete(video)
    await db_session.commit()


@pytest.mark.asyncio
async def test_reextract_not_found(client):
    """Nonexistent video_id → 404."""
    r = await client.post("/api/result/nonexistent_reextract_xyz/reextract", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reextract_youtube_video(client, seeded_video):
    """YouTube video reextract → 200 with status=reextracting.
    extract_subtitles is patched so no real yt-dlp subprocess is spawned;
    the background task returns early on a non-success result."""
    from services.subtitle_extractor import ExtractionResult, ExtractionErrorType

    mock_extraction = ExtractionResult(
        success=False,
        error_type=ExtractionErrorType.NO_SUBTITLES,
        error_message="mocked — no yt-dlp in tests",
    )

    with patch("routers.api.extract_subtitles", return_value=mock_extraction):
        r = await client.post(
            f"/api/result/{seeded_video['video_id']}/reextract",
            json={"language": "auto"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "reextracting"
        # Let the background task run and exit cleanly inside the patch scope
        await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_reextract_local_file_not_found(client, seeded_local_video):
    """local:// URL with no matching file in uploads dir → 422 synchronously."""
    r = await client.post(
        f"/api/result/{seeded_local_video['video_id']}/reextract",
        json={"language": "auto"},
    )
    assert r.status_code == 422
    assert "not found" in r.json()["detail"].lower()
