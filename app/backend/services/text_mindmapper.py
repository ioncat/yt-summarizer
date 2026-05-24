"""
Generate a compact Markdown hierarchy suitable for mindmap visualization.
Single LLM call. Input: summary_text (or cleaned_text as fallback).
Output: shallow Markdown tree (max 3 levels, ~20-40 nodes).
"""
import json
import logging

import httpx

logger = logging.getLogger("mindmapper")

DEFAULT_SYSTEM_PROMPT = """You are a mindmap structure generator.
Transform the provided text into a compact Markdown hierarchy for mindmap visualization.

Rules:
- Output ONLY Markdown, no explanations, no code fences
- Structure: # (single root topic), ## (main branches, 4-7 items), - bullet points (2-4 per branch)
- Maximum 3 levels deep
- Each node: short phrase only (3-7 words), NO full sentences, NO punctuation at end
- Mandatory: answer in {language}.
- Do not include details, examples, or elaborations — only key concepts"""

DEFAULT_USER_TEMPLATE = "Generate a mindmap hierarchy for this text:\n\n{text}"

TIMEOUT = 120


async def generate_mindmap(
    text: str,
    ollama_url: str,
    model: str,
    language: str = "Russian",
    system_prompt: str | None = None,
    user_prompt_template: str | None = None,
    is_cancelled: callable = lambda: False,
) -> str | None:
    """
    Call Ollama to generate a compact mindmap Markdown.
    Returns the markdown string, or None on failure/cancel.
    """
    if is_cancelled():
        return None

    sys_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).replace("{language}", language)
    user_tmpl = user_prompt_template or DEFAULT_USER_TEMPLATE
    # Strip ## chapter headings — they may be in a different language than the body
    # and cause the LLM to switch output language
    import re
    clean_text = re.sub(r'^## .+$', '', text, flags=re.MULTILINE).strip()
    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)
    user_msg = user_tmpl.replace("{text}", clean_text)

    payload = {
        "model": model,
        "stream": True,
        "options": {"temperature": 0.3},
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Quick health check
            logger.info("[mindmapper] health check %s/api/tags", ollama_url)
            try:
                await client.get(f"{ollama_url}/api/tags", timeout=5)
            except Exception as e:
                logger.warning("[mindmapper] health check failed: %s", e)
                return None

            if is_cancelled():
                logger.info("[mindmapper] cancelled before request")
                return None

            logger.info("[mindmapper] starting stream request, model=%s", payload["model"])
            chunks: list[str] = []
            token_count = 0
            async with client.stream("POST", f"{ollama_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                logger.info("[mindmapper] stream connected, reading tokens...")
                async for line in resp.aiter_lines():
                    if is_cancelled():
                        logger.info("[mindmapper] cancelled mid-stream after %d tokens", token_count)
                        return None
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    token = data.get("message", {}).get("content", "")
                    if token:
                        chunks.append(token)
                        token_count += 1
                    if data.get("done"):
                        logger.info("[mindmapper] stream done, %d tokens received", token_count)
                        break

            content = "".join(chunks).strip()
            logger.info("[mindmapper] result: %d chars", len(content))
            return content if content else None
    except Exception as e:
        logger.error("[mindmapper] exception: %s", e, exc_info=True)
        return None
