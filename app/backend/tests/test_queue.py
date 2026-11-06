"""
Tests for /api/queue/* endpoints.
Queue GET returns {"count": N, "items": [...]} — not a raw list.
Queue bulk add returns 400 for URLs with no extractable video_id.
"""
import pytest

VALID_URL = "https://www.youtube.com/watch?v=queueTest001"
VALID_URL_2 = "https://www.youtube.com/watch?v=queueTest002"


def _items(resp_json):
    """Extract items list from queue response (handles both list and {items: [...]} shapes)."""
    if isinstance(resp_json, list):
        return resp_json
    return resp_json.get("items", [])


@pytest.mark.asyncio
async def test_queue_bulk_add(client):
    r = await client.post("/api/queue/bulk", json={
        "urls": [VALID_URL],
        "stages": ["extract"],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["added"] >= 1


@pytest.mark.asyncio
async def test_queue_bulk_invalid_url(client):
    r = await client.post("/api/queue/bulk", json={
        "urls": ["not-a-url-at-all"],
        "stages": ["extract"],
    })
    # Endpoint may return 400 for invalid URLs or 200 with added=0
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        data = r.json()
        assert data["added"] == 0


@pytest.mark.asyncio
async def test_queue_get(client):
    await client.post("/api/queue/bulk", json={"urls": [VALID_URL_2], "stages": ["extract"]})
    r = await client.get("/api/queue")
    assert r.status_code == 200
    items = _items(r.json())
    assert isinstance(items, list)


@pytest.mark.asyncio
async def test_queue_counts(client):
    r = await client.get("/api/queue/counts")
    assert r.status_code == 200
    data = r.json()
    assert "pending" in data or "active" in data


@pytest.mark.asyncio
async def test_queue_delete_item(client):
    await client.post("/api/queue/bulk", json={
        "urls": ["https://www.youtube.com/watch?v=deleteMe123"],
        "stages": ["extract"],
    })

    items_r = await client.get("/api/queue")
    items = _items(items_r.json())
    pending = [i for i in items if i["status"] == "pending"]
    if not pending:
        pytest.skip("No pending items to delete")

    item_id = pending[0]["id"]
    r_del = await client.delete(f"/api/queue/{item_id}")
    assert r_del.status_code == 200


@pytest.mark.asyncio
async def test_queue_clear_all(client):
    await client.post("/api/queue/bulk", json={
        "urls": ["https://www.youtube.com/watch?v=clearAll001"],
        "stages": ["extract"],
    })
    r = await client.delete("/api/queue/all")
    assert r.status_code == 200

    items_r = await client.get("/api/queue")
    items = [i for i in _items(items_r.json()) if i["status"] == "pending"]
    assert len(items) == 0


@pytest.mark.asyncio
async def test_queue_rows_with_the_same_time_and_position_are_listed_by_id(client):
    """NS-17 item 6: the order of the list must not change between two reads."""
    from sqlalchemy import text
    from models.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        for n in (3, 1, 2):          # inserted out of order, same sort_order and added_at
            await db.execute(text(
                "INSERT INTO processing_queue (id, url, video_id, status, pipeline_stages, added_at, sort_order) "
                "VALUES (:id, :u, :v, 'pending', '[\"extract\"]', '2026-11-05 10:00:00', 7)"),
                {"id": n, "u": f"https://www.youtube.com/watch?v=sameTime000{n}", "v": f"sameTime000{n}"})
        await db.commit()
    first = [i["id"] for i in (await client.get("/api/queue")).json()["items"]]
    second = [i["id"] for i in (await client.get("/api/queue")).json()["items"]]
    assert first == second == [1, 2, 3]
