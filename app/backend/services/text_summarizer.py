from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant that creates concise, accurate summaries. "
    "Preserve the key information and maintain the same language as the input."
)

DEFAULT_USER_PROMPT_TEMPLATE = (
    "Summarize the following text in 5–7 concise bullet points. "
    "Focus on the main ideas and key takeaways. "
    "Keep the SAME language as the input text. "
    "Return ONLY the bullet points — no intro, no comments.\n\n"
    "Text:\n{text}"
)


async def summarize_text(
    text: str,
    system_prompt: str | None = None,
    user_prompt_template: str | None = None,
    model: str | None = None,
    ollama_url: str | None = None,
    is_cancelled: "Callable[[], bool] | None" = None,
) -> Optional[str]:
    """
    Summarize text via a single Ollama request.

    model and ollama_url must be provided (loaded from DB).
    Returns None if model/url not configured, Ollama unreachable, or cancelled.
    """
    if not model:
        logger.warning("summarize_text: no model configured. Select one in Settings.")
        return None
    if not ollama_url:
        logger.warning("summarize_text: no ollama_url configured. Set it in Settings.")
        return None
    if not text or not text.strip():
        return None

    effective_system = system_prompt or DEFAULT_SYSTEM_PROMPT
    effective_user = user_prompt_template or DEFAULT_USER_PROMPT_TEMPLATE

    if is_cancelled and is_cancelled():
        return None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            await client.get(f"{ollama_url}/api/tags", timeout=3.0)

            response = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": effective_system},
                        {"role": "user", "content": effective_user.format(text=text)},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.2},
                },
            )
            response.raise_for_status()
            result = response.json()["message"]["content"].strip()
            return result if result else None

    except httpx.ConnectError:
        logger.info("Ollama not available at %s — skipping summarization", ollama_url)
        return None
    except Exception as exc:
        logger.warning("text_summarizer failed: %s", exc)
        return None
