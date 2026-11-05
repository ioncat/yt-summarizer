"""HTTP clients for Ollama (and one PyPI call) without the 240 ms SSL set-up on the event loop (NS-28 item 3).

`httpx.AsyncClient(...)` builds its SSL context (loads the CA bundle) every time it is created, about 240 ms of CPU
done synchronously inside the event loop: every /api/health call (the page polls it every 15 s), every stage run, every
model list froze all requests for that long (700-900 ms with the CPU busy). The context is the same every time, so it
is built once per process and handed to each client; creating a client is then a fraction of a millisecond.
"""
from __future__ import annotations

import ssl
import threading

import httpx

_context: ssl.SSLContext | None = None
_lock = threading.Lock()


def ssl_context() -> ssl.SSLContext:
    """The process-wide SSL context (built on first use; startup warms it in a thread)."""
    global _context
    if _context is None:
        with _lock:
            if _context is None:
                _context = httpx.create_ssl_context()
    return _context


def http_client(**kwargs) -> httpx.AsyncClient:
    """Drop-in for httpx.AsyncClient(**kwargs) that reuses the shared SSL context."""
    kwargs.setdefault("verify", ssl_context())
    return httpx.AsyncClient(**kwargs)
