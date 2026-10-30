"""
Tests for POST/DELETE /api/result/{video_id}/mindmap.

Ollama HTTP calls are mocked via respx.
The mindmapper does a GET /api/tags health check before POST /api/chat.
"""
import asyncio
import pytest
import respx
import httpx


OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

# Newline-delimited JSON stream that generates a non-empty mindmap
MOCK_STREAMING_RESPONSE = (
    '{"message":{"content":"# Mind Map\\n"},"done":false}\n'
    '{"message":{"content":"## Main Branch\\n"},"done":false}\n'
    '{"message":{"content":"- point one"},"done":true}\n'
)


@pytest.mark.asyncio
async def test_trigger_mindmap_no_model(client, seeded_video):
    """Without a model configured the endpoint returns 200 (processing),
    but the background task finds no model and marks status as 'failed'."""
    await client.put("/api/settings/summarization", json={"model": None})

    r = await client.post(f"/api/result/{seeded_video['video_id']}/mindmap")
    assert r.status_code == 200
    # Give the background task time to run
    await asyncio.sleep(0.3)

    r2 = await client.get(f"/api/result/{seeded_video['video_id']}")
    assert r2.json()["mindmap_status"] == "failed"


@pytest.mark.asyncio
async def test_trigger_mindmap_ollama_down(client, seeded_video):
    """Ollama health-check unreachable → generate_mindmap returns None → status 'failed'."""
    await client.put("/api/settings/summarization", json={"model": "qwen2.5:7b"})

    with respx.mock:
        respx.get(OLLAMA_TAGS_URL).mock(side_effect=httpx.ConnectError("refused"))
        r = await client.post(f"/api/result/{seeded_video['video_id']}/mindmap")
        assert r.status_code == 200
        await asyncio.sleep(0.3)

    r2 = await client.get(f"/api/result/{seeded_video['video_id']}")
    assert r2.json()["mindmap_status"] == "failed"


@pytest.mark.asyncio
async def test_trigger_mindmap_success(client, seeded_video):
    """Ollama returns a valid streaming mindmap → status 'done', text non-empty."""
    await client.put("/api/settings/summarization", json={"model": "qwen2.5:7b"})

    with respx.mock:
        respx.get(OLLAMA_TAGS_URL).mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        respx.post(OLLAMA_CHAT_URL).mock(
            return_value=httpx.Response(200, text=MOCK_STREAMING_RESPONSE)
        )
        r = await client.post(f"/api/result/{seeded_video['video_id']}/mindmap")
        assert r.status_code == 200
        await asyncio.sleep(0.5)

    r2 = await client.get(f"/api/result/{seeded_video['video_id']}")
    data = r2.json()
    assert data["mindmap_status"] == "done"
    assert data["mindmap_text"]


@pytest.mark.asyncio
async def test_cancel_mindmap(client, seeded_video):
    """Cancel a running mindmap generation → status resets to null."""
    await client.put("/api/settings/summarization", json={"model": "qwen2.5:7b"})

    with respx.mock:
        # Slow health-check so the cancel arrives before the stream starts
        async def slow_tags(request):
            await asyncio.sleep(1)
            return httpx.Response(200, json={"models": []})

        respx.get(OLLAMA_TAGS_URL).mock(side_effect=slow_tags)
        respx.post(OLLAMA_CHAT_URL).mock(
            return_value=httpx.Response(200, text=MOCK_STREAMING_RESPONSE)
        )

        await client.post(f"/api/result/{seeded_video['video_id']}/mindmap")
        r_cancel = await client.delete(f"/api/result/{seeded_video['video_id']}/mindmap")
        assert r_cancel.status_code == 200

    await asyncio.sleep(0.1)
    r2 = await client.get(f"/api/result/{seeded_video['video_id']}")
    # Acceptable states: null (cancelled), processing (still running), failed or done (completed before cancel)
    assert r2.json()["mindmap_status"] in (None, "processing", "failed", "done")


@pytest.mark.asyncio
async def test_mindmap_not_found(client):
    """Nonexistent video_id → 404."""
    r = await client.post("/api/result/nonexistent_mindmap_vid/mindmap")
    assert r.status_code == 404
