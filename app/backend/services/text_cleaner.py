from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

# Default prompts — source of truth for text_cleaner defaults.
# video_service.py imports these for STAGE_DEFAULTS.
# Model has NO default here: user must pick one via the web Settings page.
DEFAULT_SYSTEM_PROMPT = (
    "You are a professional text editor specializing in cleaning up "
    "auto-generated subtitle transcripts. "
    "Your task is to improve readability while preserving ALL original content and meaning. "
    "If the text contains lines starting with '## ', treat them as chapter headings — "
    "preserve them exactly as-is. Do not translate, rephrase, or remove them."
)

DEFAULT_USER_PROMPT_TEMPLATE = (
    "Clean up this auto-generated subtitle text. Apply these rules:\n"
    "1. Fix capitalization — sentences start with a capital letter.\n"
    "2. Add correct punctuation — periods, commas, question marks.\n"
    "3. Remove filler words and verbal tics: "
    "ну, вот, как бы, значит, эм, типа, короче, ой, ах, в общем-то, "
    "слушай / знаешь when used as filler.\n"
    "4. Fix broken sentence fragments by merging them naturally.\n"
    "5. Keep the SAME language as the input text.\n"
    "6. Do NOT summarize or remove meaningful content.\n"
    "7. Return ONLY the cleaned text — no explanations, no comments.\n\n"
    "Text:\n{text}"
)


async def _clean_paragraph(
    client: httpx.AsyncClient,
    text: str,
    system_prompt: str,
    user_prompt_template: str,
    model: str,
    ollama_url: str,
) -> str:
    """Send one paragraph to Ollama. Returns the original text on any failure."""
    if not text.strip():
        return text
    try:
        response = await client.post(
            f"{ollama_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt_template.format(text=text)},
                ],
                "stream": False,
                # num_ctx 4K: cleanup paragraphs are ~500 chars (~150 tokens)
                # — large default context (128K on some models) inflates per-slot
                # KV-cache memory ~25× and pushes weights to CPU on consumer GPUs.
                # See open-questions: parallel speedup test (19.05.2026).
                "options": {"temperature": 0.1, "num_ctx": 4096},
            },
        )
        response.raise_for_status()
        cleaned = response.json()["message"]["content"].strip()
        if not cleaned:
            return text
        # Normalize whitespace: collapse any internal newlines (single \n,
        # multiple \n) to a single space, then collapse runs of spaces.
        # Cleanup output is meant to be flowing prose within one paragraph;
        # paragraph boundaries come from the outer split('\n\n'), not from
        # newlines inside a paragraph.
        cleaned = re.sub(r"\s*\n+\s*", " ", cleaned)
        cleaned = re.sub(r"  +", " ", cleaned).strip()
        return cleaned if cleaned else text
    except Exception as exc:
        logger.warning("Ollama failed on paragraph: %s", exc)
        return text


async def clean_text(
    formatted_text: str,
    system_prompt: str | None = None,
    user_prompt_template: str | None = None,
    model: str | None = None,
    ollama_url: str | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    parallel_workers: int = 1,
) -> Optional[str]:
    """
    Clean each paragraph via Ollama.

    model and ollama_url must be provided (loaded from DB app_settings).
    parallel_workers controls concurrent paragraph processing (default 1 = sequential).
    Returns None if model/url not configured, Ollama unreachable, or cancelled.
    """
    if not model:
        logger.warning("clean_text: no model configured. Select one in Settings.")
        return None
    if not ollama_url:
        logger.warning("clean_text: no ollama_url configured. Set it in Settings.")
        return None

    effective_system = system_prompt or DEFAULT_SYSTEM_PROMPT
    effective_user = user_prompt_template or DEFAULT_USER_PROMPT_TEMPLATE

    paragraphs = [p for p in formatted_text.split("\n\n") if p.strip()]
    if not paragraphs:
        return None

    workers = max(1, min(16, parallel_workers))
    total = len(paragraphs)
    logger.info("clean_text: %d paragraphs, parallel_workers=%d", total, workers)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            await client.get(f"{ollama_url}/api/tags", timeout=3.0)

            sem = asyncio.Semaphore(workers)
            completed = 0

            async def _process(idx: int, p: str) -> tuple[int, str | None]:
                nonlocal completed
                async with sem:
                    if is_cancelled and is_cancelled():
                        return idx, None
                    # Chapter headings are immutable — pass through without touching LLM
                    if p.startswith("## "):
                        result = p
                    else:
                        result = await _clean_paragraph(
                            client, p, effective_system, effective_user, model, ollama_url
                        )
                    completed += 1
                    if on_progress:
                        on_progress(completed, total)
                    return idx, result

            tasks = [_process(i, p) for i, p in enumerate(paragraphs)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            if is_cancelled and is_cancelled():
                logger.info("Cleanup cancelled mid-run.")
                return None

            # Sort by index, drop None and exceptions (fallback handled per-paragraph in _clean_paragraph)
            indexed: list[tuple[int, str | None]] = []
            for r in results:
                if isinstance(r, BaseException):
                    logger.warning("clean_text: task raised %s — skipping", type(r).__name__)
                    continue
                indexed.append(r)
            indexed.sort(key=lambda x: x[0])
            cleaned = [text for _, text in indexed if text is not None]
            return "\n\n".join(cleaned)

    except httpx.ConnectError:
        logger.info("Ollama not available at %s — skipping cleanup", ollama_url)
        return None
    except Exception as exc:
        logger.warning("text_cleaner failed: %s", exc)
        return None
