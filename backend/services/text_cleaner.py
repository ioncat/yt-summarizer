from __future__ import annotations

import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a professional text editor specializing in cleaning up "
    "auto-generated subtitle transcripts. "
    "Your task is to improve readability while preserving ALL original content and meaning."
)


def _user_prompt(text: str) -> str:
    return (
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
        f"Text:\n{text}"
    )


async def _clean_paragraph(client: httpx.AsyncClient, text: str) -> str:
    """Send one paragraph to Ollama. Returns the original text on any failure."""
    if not text.strip():
        return text
    try:
        response = await client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _user_prompt(text)},
                ],
                "stream": False,
                "options": {"temperature": 0.1},
            },
        )
        response.raise_for_status()
        cleaned = response.json()["message"]["content"].strip()
        return cleaned if cleaned else text
    except Exception as exc:
        logger.warning("Ollama failed on paragraph: %s", exc)
        return text


async def clean_text(formatted_text: str) -> Optional[str]:
    """
    Clean each paragraph via Ollama (aya-expanse or configured model).

    Returns None if Ollama is unreachable — pipeline continues without cleanup.
    Paragraphs are processed one by one to stay within the model's context window.
    """
    paragraphs = [p for p in formatted_text.split("\n\n") if p.strip()]
    if not paragraphs:
        return None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            # Fast availability check before processing
            await client.get(f"{settings.ollama_url}/api/tags", timeout=3.0)

            cleaned = [await _clean_paragraph(client, p) for p in paragraphs]
            return "\n\n".join(cleaned)

    except httpx.ConnectError:
        logger.info("Ollama not available at %s — skipping cleanup", settings.ollama_url)
        return None
    except Exception as exc:
        logger.warning("text_cleaner failed: %s", exc)
        return None
