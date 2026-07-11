import pytest
import respx
import httpx


@pytest.mark.asyncio
async def test_get_settings_returns_shape(client):
    r = await client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "app" in data
    assert "cleanup" in data
    assert "summarization" in data
    assert "ollama_url" in data["app"]


@pytest.mark.asyncio
async def test_put_app_settings(client):
    r = await client.put("/api/settings/app", json={"ollama_url": "http://custom:11434"})
    assert r.status_code == 200

    r2 = await client.get("/api/settings")
    assert r2.json()["app"]["ollama_url"] == "http://custom:11434"

    # Restore default so other tests aren't affected
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})


@pytest.mark.asyncio
async def test_put_stage_settings_cleanup(client):
    payload = {
        "model": "qwen2.5:7b",
        "system_prompt": "You are a helpful editor.",
        "user_prompt_template": "Clean this: {text}",
    }
    r = await client.put("/api/settings/cleanup", json=payload)
    assert r.status_code == 200

    r2 = await client.get("/api/settings")
    assert r2.json()["cleanup"]["model"] == "qwen2.5:7b"


@pytest.mark.asyncio
async def test_delete_stage_settings_resets_to_defaults(client):
    await client.put("/api/settings/cleanup", json={"model": "custom-model"})
    r = await client.delete("/api/settings/cleanup")
    assert r.status_code == 200

    r2 = await client.get("/api/settings")
    # After reset, model should be None (no default model)
    assert r2.json()["cleanup"]["model"] is None


@pytest.mark.asyncio
async def test_get_models_ollama_down(client):
    with respx.mock:
        respx.get("http://localhost:11434/api/tags").mock(
            side_effect=httpx.ConnectError("refused")
        )
        r = await client.get("/api/models")
    # Endpoint returns 503 when Ollama is unreachable
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert r.json() == []
