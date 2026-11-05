"""NS-11 baseline: the backend endpoints app/mcp_server.py can reach.

Pins that the MCP server has no path of its own: it only calls the same HTTP API,
and for processing it uses the BackgroundTasks endpoints (/api/process, .../cleanup,
.../summary), never /api/queue/*. NS-11 stage 1+ must keep this list reachable.
"""
import os
import re

SRC = open(os.path.join(os.path.dirname(__file__), "..", "mcp_server.py"), encoding="utf8").read()


def _endpoints() -> set[str]:
    found = set(re.findall(r'f?"(/api/[^"?]*)"', SRC))
    return {re.sub(r"\{[^}]+\}", "{id}", p) for p in found}


def test_mcp_server_calls_only_these_endpoints():
    assert _endpoints() == {
        "/api/process",
        "/api/status/{id}",
        "/api/result/{id}",
        "/api/result/{id}/cleanup",
        "/api/result/{id}/summary",
        "/api/history",
        "/api/history/text-search",
        "/api/health",
    }


def test_mcp_server_never_uses_the_queue():
    assert "/api/queue" not in SRC
