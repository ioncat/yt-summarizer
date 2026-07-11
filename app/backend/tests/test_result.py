import pytest


@pytest.mark.asyncio
async def test_get_result(client, seeded_video):
    r = await client.get(f"/api/result/{seeded_video['video_id']}")
    assert r.status_code == 200
    data = r.json()
    assert data["video_id"] == seeded_video["video_id"]
    assert "formatted_text" in data
    assert data["formatted_text"] is not None


@pytest.mark.asyncio
async def test_get_result_not_found(client):
    r = await client.get("/api/result/nonexistent_id")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_result_shape(client, seeded_video):
    r = await client.get(f"/api/result/{seeded_video['video_id']}")
    data = r.json()
    # Required fields
    for field in ("video_id", "title", "formatted_text", "cleanup_status", "summary_status"):
        assert field in data, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_delete_result(client, seeded_video):
    r = await client.delete(f"/api/result/{seeded_video['video_id']}")
    assert r.status_code == 200

    r2 = await client.get(f"/api/result/{seeded_video['video_id']}")
    assert r2.status_code == 404
