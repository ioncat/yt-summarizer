"""Shared text helpers across formatter / cleaner / summarizer."""
from __future__ import annotations

import re

# Sentence terminator followed by whitespace + capital letter (RU/EN).
# Used to detect end-of-heading when an LLM glues "## Title body..." together.
_SENT_BREAK_RE = re.compile(r"[.!?…]\s+(?=[A-ZА-ЯЁ])")

# Heading length cap when no clean break is found. Keeps a runaway "heading"
# from swallowing an entire paragraph.
_HEADING_MAX = 120


def normalize_chapter_headings(text: str) -> str:
    """
    Ensure '## Heading' blocks are surrounded by blank lines and that the
    heading itself is separated from its body by a blank line.

    LLM outputs often glue everything together as one line:
        "...end of body. ## Next Title body body body."
    The frontend renderText() splits on '\\n\\n', so without normalization
    the whole document renders as a single <p>.

    This function:
      1. Splits the text on every '## ' marker (regardless of surrounding
         whitespace).
      2. For each section, separates heading from body using the first of:
            - explicit newline,
            - sentence terminator + space + capital letter (within first
              ~250 chars),
            - forced word-boundary cut at _HEADING_MAX.
      3. Re-emits 'pre\\n\\n## Heading\\n\\nbody\\n\\n## Heading2\\n\\nbody'.

    Safe to call on text without any '## ' — returns input unchanged.
    """
    if not text or "##" not in text:
        return text

    # Split on '## ' with any surrounding whitespace consumed.
    parts = re.split(r"\s*##\s+", text)
    blocks: list[str] = []

    pre = parts[0].strip()
    if pre:
        blocks.append(pre)

    for section in parts[1:]:
        section = section.strip()
        if not section:
            continue

        nl = section.find("\n")
        sent_m = _SENT_BREAK_RE.search(section[:250])

        cut: int | None = None
        if nl >= 0:
            cut = nl
        if sent_m:
            sent_cut = sent_m.end() - 1  # keep terminator with heading, drop space
            cut = sent_cut if cut is None else min(cut, sent_cut)

        if cut is None and len(section) > _HEADING_MAX:
            ws = section.rfind(" ", 0, _HEADING_MAX)
            if ws > 0:
                cut = ws

        if cut is None:
            heading = section
            body = ""
        else:
            heading = section[:cut].strip()
            body = section[cut:].strip()

        if not heading:
            # Degenerate '## ' with nothing usable — skip.
            if body:
                blocks.append(body)
            continue

        block = f"## {heading}"
        if body:
            block += f"\n\n{body}"
        blocks.append(block)

    return "\n\n".join(blocks)
