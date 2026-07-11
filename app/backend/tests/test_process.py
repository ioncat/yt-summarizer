"""
Tests for POST /api/process and GET /api/status/{task_id}.

extract_subtitles is patched to avoid real yt-dlp calls.
"""
import pytest
from unittest.mock import patch, MagicMock

from services.subtitle_extractor import (
    ExtractionResult,
    VideoMetadata,
    SubtitleEntry,
    SubtitleSourceType,
)

MOCK_EXTRACTION = ExtractionResult(
    success=True,
    metadata=VideoMetadata(
        video_id="xyzABC12345",
        title="Mock Video",
        author="Mock Channel",
        duration=300,
        channel_id="UC_mock",
        channel_name="Mock Channel",
        upload_date="20240101",
        view_count=1000,
        description="Test description",
        thumbnail_url=None,
        chapters=None,
    ),
    subtitles=[
        SubtitleEntry("00:00:01.000", "Первое предложение."),
        SubtitleEntry("00:00:05.000", "Второе предложение."),
    ],
    language="ru",
    source_type=SubtitleSourceType.AUTO,
)

TEST_URL = "https://www.youtube.com/watch?v=xyzABC12345"


@pytest.mark.asyncio
async def test_process_new_video(client):
    with patch("routers.api.extract_subtitles", return_value=MOCK_EXTRACTION):
        r = await client.post("/api/process", json={"url": TEST_URL, "language": "ru"})
    assert r.status_code == 200
    data = r.json()
    assert "task_id" in data
    assert data["video_id"] == "xyzABC12345"


@pytest.mark.asyncio
async def test_process_invalid_url(client):
    r = await client.post("/api/process", json={"url": "not-a-youtube-url", "language": "ru"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_process_duplicate_returns_409(client, seeded_video):
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    r = await client.post("/api/process", json={"url": url, "language": "ru"})
    assert r.status_code == 409
    data = r.json()
    # detail may be a dict or string depending on FastAPI version
    detail = data.get("detail", {})
    if isinstance(detail, dict):
        assert detail.get("video_id") == "dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_status_not_found(client):
    r = await client.get("/api/status/nonexistent-task-id")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_process_and_check_status(client):
    url = "https://www.youtube.com/watch?v=statusTest1"
    with patch("routers.api.extract_subtitles", return_value=MOCK_EXTRACTION):
        r = await client.post("/api/process", json={"url": url, "language": "ru"})
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    r2 = await client.get(f"/api/status/{task_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["task_id"] == task_id
    assert data["status"] in ("pending", "processing", "done", "completed", "failed")
