"""
Generate a compact Markdown hierarchy suitable for mindmap visualization.
Single LLM call. Input: summary_text (or cleaned_text as fallback).
Output: shallow Markdown tree (max 3 levels, ~20-40 nodes).
"""
import httpx

DEFAULT_SYSTEM_PROMPT = """You are a mindmap structure generator.
Transform the provided text into a compact Markdown hierarchy for mindmap visualization.

Rules:
- Output ONLY Markdown, no explanations, no code fences
- Structure: # (single root topic), ## (main branches, 4-7 items), - bullet points (2-4 per branch)
- Maximum 3 levels deep
- Each node: short phrase only (3-7 words), NO full sentences, NO punctuation at end
- Preserve the original language of the text
- Do not include details, examples, or elaborations — only key concepts"""

DEFAULT_USER_TEMPLATE = "Generate a mindmap hierarchy for this text:\n\n{text}"

TIMEOUT = 120


async def generate_mindmap(
    text: str,
    ollama_url: str,
    model: str,
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

    sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    user_tmpl = user_prompt_template or DEFAULT_USER_TEMPLATE
    user_msg = user_tmpl.replace("{text}", text)

    payload = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0.3},
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Quick health check
            try:
                await client.get(f"{ollama_url}/api/tags", timeout=5)
            except Exception:
                return None

            if is_cancelled():
                return None

            resp = await client.post(f"{ollama_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "").strip()
            return content if content else None
    except Exception:
        return None
