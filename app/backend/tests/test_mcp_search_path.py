"""The MCP tools against the real backend app (no HTTP mocks): app/mcp_server.py -> /api/history*.

The unit tests in app/tests mock the backend; this one proves the two halves agree, e.g. on Cyrillic case.
"""
import os
import sys

import httpx
import pytest
from httpx import ASGITransport

from tests.test_history_text_search import make_video  # noqa: F401  (fixture)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import mcp_server  # noqa: E402


@pytest.fixture
def mcp_on_backend(monkeypatch):
    from main import app
    monkeypatch.setattr(mcp_server, "_client", lambda: httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=30.0))


async def test_search_history_finds_a_capitalised_cyrillic_title_with_a_lowercase_query(mcp_on_backend, make_video):
    await make_video("mcpPath0001", title="Борщ по-украински", author="Кулинарный Канал",
                     formatted_text="Сначала нарежьте свёклу. Затем варите борщ.")
    out = await mcp_server.search_history(query="борщ")
    assert "Борщ по-украински — Кулинарный Канал" in out and "mcpPath0001" in out
    assert "mcpPath0001" in await mcp_server.search_history(query="КАНАЛ")


async def test_search_history_in_text_finds_the_same_video_by_a_word_in_its_transcript(mcp_on_backend, make_video):
    await make_video("mcpPath0002", title="Другое", formatted_text="Сначала нарежьте свёклу. Затем варите БОРЩ.")
    out = await mcp_server.search_history(query="борщ", in_text=True)
    assert "mcpPath0002" in out and "transcript ×1, first at char 38" in out
    assert "БОРЩ" in out  # the snippet keeps the original case
