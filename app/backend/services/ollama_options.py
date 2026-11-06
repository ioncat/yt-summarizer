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
MIN_ANSWER_TOKENS = 1024     # the least room for the answer that an input must leave inside the limit; below it the call is refused
_BUCKETS = (4096, 8192, 16384, 32768, 65536)
MAX_REASON_CHARS = 500  # as str(exc)[:500] in the stage runners
MAX_NUM_CTX = max(_BUCKETS)  # upper bound of any cap, 65536

_max_num_ctx: ContextVar[int] = ContextVar("llm_max_num_ctx", default=DEFAULT_MAX_NUM_CTX)
_failure_reason: ContextVar[list | None] = ContextVar("llm_failure_reason", default=None)


def clamp_num_ctx(n: int) -> int:
    return max(MIN_NUM_CTX, min(MAX_NUM_CTX, n))


def parse_max_num_ctx(value: str | int | None) -> int:
    """Setting value -> cap, clamped to 4096..65536. A value that is not a number gives the default."""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_MAX_NUM_CTX
    return clamp_num_ctx(n)


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


def begin_llm_run(max_num_ctx: str | int | None = None) -> None:
    """Start of a stage run: set the cap and open a fresh box for the reason of a failed call."""
    apply_max_num_ctx(max_num_ctx)
    _failure_reason.set([])


def record_failure_reason(message: str) -> None:
    """Called by an LLM call that got no usable answer; the first reason of a run is kept (cut to MAX_REASON_CHARS: the
    text may come from an Ollama answer or a setting, and ends up in the database and on the page)."""
    box = _failure_reason.get()
    if box is not None and not box:
        box.append(message[:MAX_REASON_CHARS])


def record_llm_exception(exc: Exception, model: str | None) -> None:
    """An LLM call raised: record a reason the user can act on, where the exception says what is wrong.

    Ollama answers HTTP 404 on /api/chat when the model is not installed: "Model 'x' not found in Ollama" (instead of the
    generic "may be unreachable, or the model returned nothing"). Other exceptions record nothing here."""
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) == 404:
        record_failure_reason(f"Model '{model}' not found in Ollama")


def llm_failure_reason() -> str | None:
    box = _failure_reason.get()
    return box[0] if box else None


def empty_answer_message(has_thinking: bool) -> str:
    if has_thinking:
        return ("model returned no answer (thinking used the whole context) — "
                "use a model without thinking (or raise llm_max_num_ctx if the input is very long)")
    return "model returned nothing"


def estimate_tokens(*texts: str) -> int:
    return sum(len(t or "") for t in texts) // CHARS_PER_TOKEN + 1


def compute_num_ctx(*texts: str, reserve_tokens: int = DEFAULT_RESERVE_TOKENS, max_ctx: int | None = None) -> int:
    cap = clamp_num_ctx(max_ctx) if max_ctx is not None else _max_num_ctx.get()
    prompt_tokens = estimate_tokens(*texts)
    needed = prompt_tokens + reserve_tokens + prompt_tokens // 4
    for size in _BUCKETS:
        if size >= needed:
            return min(max(size, MIN_NUM_CTX), cap)
    return cap


class ContextTooSmall(Exception):
    """The input does not fit the context limit with room left for the answer. Ollama would cut the input off without a word and
    the model would answer from half a text, so the call is not made (NS-26); the reason is recorded for the stage."""


def current_max_num_ctx() -> int:
    """The context limit in force for the current stage run (the setting, clamped)."""
    return _max_num_ctx.get()


def too_long_message(tokens: int, cap: int, room: int = MIN_ANSWER_TOKENS) -> str:
    return (f"The input (~{tokens} tokens) is too long for the context limit ({cap}), which must also leave room for the answer "
            f"(~{room} tokens): the answer would be cut off. Raise the context limit in Settings → General, or use a shorter text.")


def build_options(*texts: str, reserve_tokens: int = DEFAULT_RESERVE_TOKENS, max_ctx: int | None = None,
                  **options) -> dict:
    """Ollama `options` dict: the given options plus a `num_ctx` sized to the prompt `texts`.

    The context asked from Ollama is sized for the full `reserve_tokens` where the limit allows it (thinking models need room), but
    the call is refused only when the input does not leave even MIN_ANSWER_TOKENS (or `reserve_tokens`, if smaller) inside the
    limit. Raises ContextTooSmall (after recording its reason) in that case."""
    cap = clamp_num_ctx(max_ctx) if max_ctx is not None else _max_num_ctx.get()
    tokens = estimate_tokens(*texts)
    room = min(reserve_tokens, MIN_ANSWER_TOKENS)
    if tokens + room > cap:
        message = too_long_message(tokens, cap, room)
        logger.warning("%s", message)
        record_failure_reason(message)
        raise ContextTooSmall(message)
    return {**options, "num_ctx": compute_num_ctx(*texts, reserve_tokens=reserve_tokens, max_ctx=max_ctx)}
