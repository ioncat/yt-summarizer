import pytest
import respx
import httpx


@pytest.mark.asyncio
async def test_health_backend_up(client):
    with respx.mock:
        respx.get("http://localhost:11434/api/tags").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        r = await client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["backend"] is True
    assert data["ollama"] is True


@pytest.mark.asyncio
async def test_health_ollama_down(client):
    with respx.mock:
        respx.get("http://localhost:11434/api/tags").mock(
            side_effect=httpx.ConnectError("refused")
        )
        r = await client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["backend"] is True
    assert data["ollama"] is False
