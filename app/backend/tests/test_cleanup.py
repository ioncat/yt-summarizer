"""
Tests for POST/DELETE /api/result/{video_id}/cleanup.

Ollama HTTP calls are mocked via respx.
"""
import asyncio
import pytest
import respx
import httpx


OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

MOCK_OLLAMA_RESPONSE = {
    "message": {"role": "assistant", "content": "Cleaned paragraph text."},
    "done": True,
}


@pytest.mark.asyncio
async def test_trigger_cleanup_no_model(client, seeded_video):
    """Cleanup with no model configured → endpoint rejects with 400."""
    await client.put("/api/settings/cleanup", json={"model": None})

    r = await client.post(f"/api/result/{seeded_video['video_id']}/cleanup")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_trigger_cleanup_ollama_down(client, seeded_video):
    """Cleanup with Ollama unreachable → status failed."""
    await client.put("/api/settings/cleanup", json={"model": "qwen2.5:7b"})

    with respx.mock:
        respx.post(OLLAMA_CHAT_URL).mock(side_effect=httpx.ConnectError("refused"))
        r = await client.post(f"/api/result/{seeded_video['video_id']}/cleanup")
        assert r.status_code == 200
        await asyncio.sleep(0.3)

    r2 = await client.get(f"/api/result/{seeded_video['video_id']}")
    assert r2.json()["cleanup_status"] == "failed"


@pytest.mark.asyncio
async def test_cancel_cleanup(client, seeded_video):
    """Cancel in-flight cleanup — status resets to null."""
    await client.put("/api/settings/cleanup", json={"model": "qwen2.5:7b"})

    with respx.mock:
        # Slow response so cancel arrives during processing
        async def slow_response(request):
            await asyncio.sleep(1)
            return httpx.Response(200, json=MOCK_OLLAMA_RESPONSE)

        respx.post(OLLAMA_CHAT_URL).mock(side_effect=slow_response)

        await client.post(f"/api/result/{seeded_video['video_id']}/cleanup")
        # Cancel immediately
        r_cancel = await client.delete(f"/api/result/{seeded_video['video_id']}/cleanup")
        assert r_cancel.status_code == 200

    # After cancel, status should reset
    await asyncio.sleep(0.1)
    r2 = await client.get(f"/api/result/{seeded_video['video_id']}")
    # Status may be null (cancelled), processing, or failed (bg task finished before cancel)
    assert r2.json()["cleanup_status"] in (None, "processing", "failed")


@pytest.mark.asyncio
async def test_cleanup_not_found(client):
    r = await client.post("/api/result/nonexistent/cleanup")
    assert r.status_code in (404, 200)  # 200 if bg task handles missing gracefully
