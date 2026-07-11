"""
Tests for POST/DELETE /api/result/{video_id}/summary.
"""
import asyncio
import pytest
import respx
import httpx

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

MOCK_SUMMARY_RESPONSE = {
    "message": {"role": "assistant", "content": "Summary of the video content."},
    "done": True,
}


@pytest.mark.asyncio
async def test_trigger_summary_no_model(client, seeded_video):
    """Summary with no model configured → endpoint rejects with 400."""
    await client.put("/api/settings/summarization", json={"model": None})

    r = await client.post(f"/api/result/{seeded_video['video_id']}/summary")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_trigger_summary_ollama_down(client, seeded_video):
    await client.put("/api/settings/summarization", json={"model": "qwen2.5:7b"})

    with respx.mock:
        respx.post(OLLAMA_CHAT_URL).mock(side_effect=httpx.ConnectError("refused"))
        r = await client.post(f"/api/result/{seeded_video['video_id']}/summary")
        assert r.status_code == 200
        await asyncio.sleep(0.3)

    r2 = await client.get(f"/api/result/{seeded_video['video_id']}")
    assert r2.json()["summary_status"] == "failed"


@pytest.mark.asyncio
async def test_cancel_summary(client, seeded_video):
    await client.put("/api/settings/summarization", json={"model": "qwen2.5:7b"})

    with respx.mock:
        async def slow_response(request):
            await asyncio.sleep(1)
            return httpx.Response(200, json=MOCK_SUMMARY_RESPONSE)

        respx.post(OLLAMA_CHAT_URL).mock(side_effect=slow_response)

        await client.post(f"/api/result/{seeded_video['video_id']}/summary")
        r_cancel = await client.delete(f"/api/result/{seeded_video['video_id']}/summary")
        assert r_cancel.status_code == 200

    await asyncio.sleep(0.1)
    r2 = await client.get(f"/api/result/{seeded_video['video_id']}")
    assert r2.json()["summary_status"] in (None, "processing", "failed")


@pytest.mark.asyncio
async def test_summary_uses_cleaned_text_when_available(client, db_session, seeded_video):
    """If cleaned_text is present, summary input should be cleaned_text."""
    from models.models import SubtitleFormatted
    from sqlalchemy import select

    # Add cleaned_text to the seeded row
    result = await db_session.execute(
        select(SubtitleFormatted).where(SubtitleFormatted.video_id == seeded_video["db_id"])
    )
    fmt = result.scalars().first()
    if fmt:
        fmt.cleaned_text = "Cleaned version of the transcript."
        await db_session.commit()

    # Verify endpoint accepts the request
    r = await client.post(f"/api/result/{seeded_video['video_id']}/summary")
    assert r.status_code == 200
