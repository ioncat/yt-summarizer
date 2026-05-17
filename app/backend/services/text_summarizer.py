from __future__ import annotations

import logging
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Texts longer than this are summarized via Map-Reduce instead of single-pass.
# ~24 000 chars ≈ 6 000 tokens — safe headroom for 8K context models.
MAP_REDUCE_THRESHOLD = 24_000

# Target size of each MAP chunk (characters). Leaves room for prompt + output
# inside an 8K context window.
CHUNK_SIZE = 3_000

# ---------------------------------------------------------------------------
# Default prompts — single-pass
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant that creates concise, accurate summaries. "
    "Preserve the key information and maintain the same language as the input. "
    "If the text contains lines starting with '## ', treat them as chapter headings — "
    "preserve them exactly as-is in your output. Do not translate, rephrase, or remove them."
)

DEFAULT_USER_PROMPT_TEMPLATE = (
    "Summarize the following text in 5–7 concise bullet points. "
    "Focus on the main ideas and key takeaways. "
    "Keep the SAME language as the input text. "
    "Return ONLY the bullet points — no intro, no comments.\n\n"
    "Text:\n{text}"
)

# ---------------------------------------------------------------------------
# Default prompts — Map-Reduce MAP step
# ---------------------------------------------------------------------------

DEFAULT_MAP_SYSTEM_PROMPT = (
    "You are a helpful assistant that extracts key information from text sections. "
    "Preserve the key information and maintain the same language as the input. "
    "If the section starts with a line beginning with '## ', that is a chapter heading — "
    "begin your summary with that exact heading, then write the summary below it."
)

DEFAULT_MAP_USER_PROMPT = (
    "Write a detailed paragraph summarizing all key information from this section. "
    "Include all important facts, numbers, names, examples, and arguments. "
    "Do not skip any significant point. Do not compress aggressively. "
    "Keep the SAME language as the input text. "
    "If the section starts with a '## ' heading, preserve it at the top of your output. "
    "Return ONLY the result — no bullet points, no intro, no comments.\n\n"
    "Section:\n{text}"
)

# ---------------------------------------------------------------------------
# Default prompts — Map-Reduce REDUCE step
# ---------------------------------------------------------------------------

DEFAULT_REDUCE_SYSTEM_PROMPT = (
    "You are a helpful assistant that synthesizes section summaries into a coherent final summary. "
    "Maintain the same language as the input. "
    "If section summaries contain lines starting with '## ', those are chapter headings — "
    "preserve them exactly as-is in the final output."
)

DEFAULT_REDUCE_USER_PROMPT = (
    "Below are summaries of consecutive sections of a longer text. "
    "Organize them into a structured document divided into thematic sections. "
    "Each section must have a short heading followed by a paragraph that preserves all key ideas from that theme. "
    "Eliminate only exact repetition — preserve all important details, facts, numbers, and arguments. "
    "The final text should be substantially detailed, not a brief abstract. "
    "Keep the SAME language as the input text. "
    "Do NOT respond conversationally. Do NOT write \"Thank you\" or similar phrases. "
    "Do NOT add conclusions, opinions, or information not present in the source. "
    "Compress and reorganize only — do not interpret or invent. "
    "Return ONLY the summary. Start directly with the first section heading.\n\n"
    "Summaries:\n{text}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """
    Split text into overlapping chunks by paragraphs.

    Paragraphs are separated by double newlines (as produced by text_formatter).
    Each chunk accumulates paragraphs until adding the next would exceed chunk_size.
    The last paragraph of the previous chunk is prepended to the next chunk
    as overlap to preserve continuity across boundaries.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [text] if text.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    overlap_paragraph: str | None = None

    for para in paragraphs:
        para_len = len(para)

        # Start a new chunk when current would overflow
        if current_len + para_len > chunk_size and current:
            chunks.append("\n\n".join(current))
            overlap_paragraph = current[-1]  # last paragraph as overlap
            current = []
            current_len = 0
            if overlap_paragraph:
                current.append(overlap_paragraph)
                current_len += len(overlap_paragraph)

        current.append(para)
        current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


async def _call_ollama(
    client: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float = 180.0,
) -> str | None:
    """Single Ollama /api/chat call. Returns stripped content or None on error."""
    try:
        response = await client.post(
            f"{ollama_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.json()["message"]["content"].strip()
        return content if content else None
    except Exception as exc:
        logger.warning("_call_ollama failed: [%s] %s", type(exc).__name__, exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_LANGUAGE_NAMES: dict[str, str] = {
    "ru": "Russian", "en": "English", "uk": "Ukrainian",
    "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "pl": "Polish",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
}


def _language_instruction(language: str | None) -> str:
    """Return explicit language instruction, e.g. 'Respond in Russian.'"""
    if not language:
        return ""
    name = _LANGUAGE_NAMES.get(language.lower(), language)
    return f"Respond in {name}.\n"


async def summarize_text(
    text: str,
    system_prompt: str | None = None,
    user_prompt_template: str | None = None,
    model: str | None = None,
    ollama_url: str | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    force_map_reduce: bool = False,
    extract_prompt: str | None = None,
    combine_prompt: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    language: str | None = None,
) -> tuple[Optional[str], str, int]:
    """
    Summarize text via Ollama.

    Automatically selects single-pass or Map-Reduce based on text length.

    Returns:
        (summary_text, mode, chunks_count)
        mode: 'single' | 'map_reduce'
        chunks_count: 1 for single-pass, N for map-reduce
    """
    if not model:
        logger.warning("summarize_text: no model configured. Select one in Settings.")
        return None, "single", 0
    if not ollama_url:
        logger.warning("summarize_text: no ollama_url configured. Set it in Settings.")
        return None, "single", 0
    if not text or not text.strip():
        return None, "single", 0

    if is_cancelled and is_cancelled():
        return None, "single", 0

    try:
        async with httpx.AsyncClient() as client:
            # Availability check
            try:
                await client.get(f"{ollama_url}/api/tags", timeout=3.0)
            except httpx.ConnectError:
                logger.info("Ollama not available at %s — skipping summarization", ollama_url)
                return None, "single", 0

            lang_instruction = _language_instruction(language)
            if not force_map_reduce and len(text) < MAP_REDUCE_THRESHOLD:
                result = await _single_pass(
                    client, text, system_prompt, user_prompt_template, model, ollama_url,
                    lang_instruction=lang_instruction,
                )
                return result, "single", 1
            else:
                result, chunks_count = await _map_reduce(
                    client, text, system_prompt, model, ollama_url, is_cancelled,
                    extract_prompt=extract_prompt,
                    combine_prompt=combine_prompt,
                    on_progress=on_progress,
                    lang_instruction=lang_instruction,
                )
                return result, "map_reduce", chunks_count

    except Exception as exc:
        logger.warning("summarize_text failed: %s", exc)
        return None, "single", 0


async def _single_pass(
    client: httpx.AsyncClient,
    text: str,
    system_prompt: str | None,
    user_prompt_template: str | None,
    model: str,
    ollama_url: str,
    lang_instruction: str = "",
) -> str | None:
    effective_system = system_prompt or DEFAULT_SYSTEM_PROMPT
    effective_user = lang_instruction + (user_prompt_template or DEFAULT_USER_PROMPT_TEMPLATE).format(text=text)
    return await _call_ollama(client, ollama_url, model, effective_system, effective_user)


async def _map_reduce(
    client: httpx.AsyncClient,
    text: str,
    system_prompt: str | None,
    model: str,
    ollama_url: str,
    is_cancelled: Callable[[], bool] | None,
    extract_prompt: str | None = None,
    combine_prompt: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    lang_instruction: str = "",
) -> tuple[str | None, int]:
    """
    Map-Reduce summarization.
    Returns (final_summary, chunks_count).
    """
    chunks = _split_into_chunks(text)
    chunks_count = len(chunks)
    logger.info("map_reduce: %d chunks from %d chars", chunks_count, len(text))

    map_system = system_prompt or DEFAULT_MAP_SYSTEM_PROMPT
    effective_extract = extract_prompt or DEFAULT_MAP_USER_PROMPT
    effective_combine = combine_prompt or DEFAULT_REDUCE_USER_PROMPT

    # MAP — summarize each chunk
    chunk_summaries: list[str] = []
    for i, chunk in enumerate(chunks):
        if is_cancelled and is_cancelled():
            logger.info("map_reduce: cancelled at MAP chunk %d/%d", i + 1, chunks_count)
            return None, chunks_count

        logger.info("map_reduce: MAP %d/%d (%d chars)", i + 1, chunks_count, len(chunk))
        summary = await _call_ollama(
            client, ollama_url, model,
            map_system,
            lang_instruction + effective_extract.format(text=chunk),
        )
        if summary is None:
            logger.warning("map_reduce: MAP chunk %d failed — aborting", i + 1)
            return None, chunks_count
        chunk_summaries.append(summary)
        if on_progress:
            on_progress(i + 1, chunks_count)

    if is_cancelled and is_cancelled():
        return None, chunks_count

    # REDUCE — combine all chunk summaries into a final summary
    combined = "\n\n".join(chunk_summaries)
    logger.info("map_reduce: REDUCE (%d chars of chunk summaries)", len(combined))
    reduce_system = system_prompt or DEFAULT_REDUCE_SYSTEM_PROMPT
    # REDUCE gets much larger input than MAP chunks — needs a longer timeout
    reduce_timeout = max(180.0, len(combined) / 50.0)  # ~1 sec per 50 chars, min 180s
    logger.info("map_reduce: REDUCE timeout=%.0fs", reduce_timeout)
    final = await _call_ollama(
        client, ollama_url, model,
        reduce_system,
        lang_instruction + effective_combine.format(text=combined),
        timeout=reduce_timeout,
    )

    return final, chunks_count
