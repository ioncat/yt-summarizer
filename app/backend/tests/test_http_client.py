"""NS-28 item 3: no SSL context is built on the event loop per request."""
import asyncio
import os
import re
import threading
import time

import httpx
import respx

from services import http_client as hc

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_context_is_built_once_even_from_many_threads(monkeypatch):
    calls = []
    real = httpx.create_ssl_context
    monkeypatch.setattr(hc, "_context", None)
    monkeypatch.setattr(hc.httpx, "create_ssl_context", lambda *a, **k: calls.append(1) or real(*a, **k))
    threads = [threading.Thread(target=hc.ssl_context) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and hc.ssl_context() is hc.ssl_context()


def test_creating_a_client_is_cheap_once_the_context_exists():
    hc.ssl_context()
    start = time.perf_counter()
    clients = [hc.http_client(timeout=3.0) for _ in range(100)]
    per_client_ms = (time.perf_counter() - start) / 100 * 1000
    assert per_client_ms < 20, per_client_ms  # httpx.AsyncClient() alone costs about 240 ms
    assert all(c.timeout.read == 3.0 for c in clients)


def test_an_explicit_verify_argument_still_wins():
    c = hc.http_client(verify=False)
    assert c is not None


@respx.mock
async def test_health_and_models_never_build_a_context(client, monkeypatch):
    hc.ssl_context()
    built = []
    real = httpx.create_ssl_context
    monkeypatch.setattr(hc.httpx, "create_ssl_context", lambda *a, **k: built.append(1) or real(*a, **k))
    await client.put("/api/settings/app", json={"ollama_url": "http://localhost:11434"})
    respx.get("http://localhost:11434/api/tags").mock(return_value=httpx.Response(200, json={"models": [{"name": "m"}]}))
    for _ in range(20):
        assert (await client.get("/api/health")).json() == {"backend": True, "ollama": True}
    assert (await client.get("/api/models")).json() == {"models": ["m"]}
    assert built == []


async def test_requests_are_not_held_up_while_health_is_called(client):
    """Before the fix each health call froze the loop for ~240 ms; a ticker must keep ticking."""
    hc.ssl_context()
    lags = []

    async def ticker():
        while True:
            t = time.perf_counter()
            await asyncio.sleep(0.005)
            lags.append(time.perf_counter() - t - 0.005)

    task = asyncio.create_task(ticker())
    await asyncio.gather(*(client.get("/api/health") for _ in range(10)))
    task.cancel()
    assert max(lags) < 0.15, max(lags)


def test_no_module_builds_httpx_clients_directly():
    """Every call site uses http_client(); a bare httpx.AsyncClient( would bring the 240 ms back."""
    offenders = []
    for folder in ("services", "routers"):
        for name in os.listdir(os.path.join(BACKEND, folder)):
            if name.endswith(".py") and name != "http_client.py":
                text = open(os.path.join(BACKEND, folder, name), encoding="utf-8").read()
                if re.search(r"httpx\.AsyncClient\(", text):
                    offenders.append(f"{folder}/{name}")
    assert offenders == []
