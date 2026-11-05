"""Sizing of the Ollama context window for every /api/chat call.

Without `num_ctx` Ollama uses its default (4096 tokens). A thinking model (gemma4, qwen3, ...)
spends the tokens that are left after the prompt on `message.thinking`, stops with
`done_reason: length` and returns an empty `message.content`. So every chat call sizes
`num_ctx` from its own input with `build_options()`.

Rule: needed = prompt tokens + reserve (thinking + answer) + 25% of the prompt tokens;
`num_ctx` is the next size of 4096 / 8192 / 16384 / 32768 / 65536 that fits, never above the
cap. Fixed sizes keep Ollama from reloading the model for every slightly different length.
Tokens are estimated at 3 characters each (safe for Cyrillic, over-counts English a little).

The cap (app setting `llm_max_num_ctx`, default 32768) travels in a context variable set by the
code that runs a stage (`llm_scope`), so the LLM functions keep their signatures.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar

logger = logging.getLogger("ollama_options")

DEFAULT_MAX_NUM_CTX = 32768
MIN_NUM_CTX = 4096
CHARS_PER_TOKEN = 3
DEFAULT_RESERVE_TOKENS = 4096
_BUCKETS = (4096, 8192, 16384, 32768, 65536)

_max_num_ctx: ContextVar[int] = ContextVar("llm_max_num_ctx", default=DEFAULT_MAX_NUM_CTX)


def parse_max_num_ctx(value: str | int | None) -> int:
    """Setting value -> cap. Anything unusable falls back to the default."""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_MAX_NUM_CTX
    return n if n >= MIN_NUM_CTX else DEFAULT_MAX_NUM_CTX


@contextmanager
def llm_scope(max_num_ctx: str | int | None = None):
    """Set the num_ctx cap for every LLM call made inside the block (also in child tasks)."""
    token = _max_num_ctx.set(parse_max_num_ctx(max_num_ctx))
    try:
        yield
    finally:
        _max_num_ctx.reset(token)


def apply_max_num_ctx(value: str | int | None) -> None:
    """Set the cap for the rest of the current task (a stage runner reads the setting once)."""
    _max_num_ctx.set(parse_max_num_ctx(value))


def estimate_tokens(*texts: str) -> int:
    return sum(len(t or "") for t in texts) // CHARS_PER_TOKEN + 1


def compute_num_ctx(*texts: str, reserve_tokens: int = DEFAULT_RESERVE_TOKENS, max_ctx: int | None = None) -> int:
    cap = max_ctx if max_ctx is not None else _max_num_ctx.get()
    prompt_tokens = estimate_tokens(*texts)
    needed = prompt_tokens + reserve_tokens + prompt_tokens // 4
    for size in _BUCKETS:
        if size >= needed:
            return min(max(size, MIN_NUM_CTX), cap)
    return cap


def build_options(*texts: str, reserve_tokens: int = DEFAULT_RESERVE_TOKENS, max_ctx: int | None = None,
                  **options) -> dict:
    """Ollama `options` dict: the given options plus a `num_ctx` sized to the prompt `texts`."""
    num_ctx = compute_num_ctx(*texts, reserve_tokens=reserve_tokens, max_ctx=max_ctx)
    cap = max_ctx if max_ctx is not None else _max_num_ctx.get()
    if estimate_tokens(*texts) + reserve_tokens > cap:
        logger.warning("prompt of ~%d tokens does not leave room for the answer in num_ctx cap %d",
                       estimate_tokens(*texts), cap)
    return {**options, "num_ctx": num_ctx}
