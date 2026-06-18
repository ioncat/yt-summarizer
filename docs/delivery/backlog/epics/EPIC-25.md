# Epic 25: Chapter Heading Preservation & Rendering

**Phase**: 2 — Summarization Quality  
**Status**: ✅ Done  
**Priority**: 🔴 P0

## Goal

`## Chapter Title` headings — authored by the video creator — are immutable semantic
units. They must pass through the entire processing pipeline unchanged (formatting →
cleanup → summarization) and render visually as headings in the UI.

The creator has already done the structural work: named each semantic block, defined
its scope, and anchored it to a timestamp. Preserving this structure is the single
most important quality constraint when chapters are present.

**Terminology**: when a video has chapters, subtitle groups are called **paragraphs**,
matching the chapter structure. This naming is intentional and must
be kept throughout code and UI.

---

## Pipeline Invariant

```
formatted_text:   ## Introduction\n\nraw subtitle text...
                       ↓  cleanup (LLM touches only text, not heading)
cleaned_text:     ## Introduction\n\ncleaned text...
                       ↓  summarize (heading preserved in output)
summary_text:     ## Introduction\n\nparagraph summary...
```

---

## User Stories

---

### US-2501: Cleanup preserves chapter headings

**As a** user running AI cleanup on a video with chapters  
**I want** the `## Chapter Title` headings to remain unchanged after cleanup  
**So that** the author's structure is preserved in the cleaned output

#### Acceptance Criteria

**Given** `formatted_text` contains `## Chapter Title\n\ntext...`  
**When** AI cleanup runs  
**Then** `cleaned_text` contains the same `## Chapter Title` heading unchanged

**Given** a paragraph in the text starts with `## `  
**When** the cleaner processes that paragraph  
**Then** it is written to output as-is without being sent to the LLM

#### Edge Cases

- Heading followed by empty text (empty chapter) → heading still passes through
- Multiple consecutive headings → all pass through unchanged
- Text that happens to start with `## ` but has no chapters → same rule applies (safe)

#### Notes for Engineering

`text_cleaner.py` splits `formatted_text` by `\n\n` into paragraphs.
Add a guard before sending each paragraph to Ollama:

```python
if paragraph.startswith("## "):
    yield paragraph  # pass through unchanged
    continue
```

---

### US-2502: Summarization preserves chapter headings

**As a** user running AI summarization on a video with chapters  
**I want** the `## Chapter Title` headings to appear in the summary output  
**So that** the summary is organized by the author's chapter structure

#### Acceptance Criteria

**Given** input text contains `## Chapter Title` headings  
**When** single-pass summarization runs  
**Then** `summary_text` preserves the `## Chapter Title` headings

**Given** map-reduce summarization runs  
**When** MAP step processes a chunk starting with `## Chapter Title`  
**Then** the chunk summary begins with the same `## Chapter Title`

**Given** REDUCE step combines chunk summaries  
**When** output is assembled  
**Then** `## Chapter Title` headings from chunk summaries are preserved

#### Edge Cases

- Model ignores the instruction and drops headings → acceptable degradation; no hard enforcement
- Model renames a heading → acceptable; we only instruct, not enforce
- REDUCE step re-orders chunks → headings move with their content

#### Notes for Engineering

Add explicit instruction to system prompts for cleanup and summarization stages:

```
If the text contains lines starting with "## ", treat them as chapter headings.
Preserve them exactly as-is in your output. Do not translate, rephrase, or remove them.
```

For map-reduce MAP prompt: instruct model to begin its chunk summary with the
`## heading` if the chunk starts with one.

Changes in `text_cleaner.py` DEFAULT_SYSTEM_PROMPT and
`text_summarizer.py` DEFAULT_MAP_SYSTEM_PROMPT / DEFAULT_REDUCE_SYSTEM_PROMPT.
Also update default prompts in DB via Settings reset (DELETE /api/settings/{stage}).

---

### US-2503: UI renders chapter headings visually

**As a** user reading extracted or processed text  
**I want** `## Chapter Title` lines to appear as visible subheadings  
**So that** the chapter structure is immediately scannable

#### Acceptance Criteria

**Given** displayed text contains lines starting with `## `  
**When** rendered in Subtitles, Cleaned, or Summary tab  
**Then** those lines appear as styled subheadings (larger, bold, separated)

**Given** the text has no `## ` lines  
**When** rendered  
**Then** output is identical to current plain text rendering (no regression)

#### Edge Cases

- `##` without space (e.g. `##title`) → not treated as heading, rendered as plain text
- Heading mid-paragraph (no preceding blank line) → still rendered as heading if line starts with `## `

#### Notes for Engineering

No react-markdown dependency needed. Minimal inline renderer:
split text by `\n`, detect lines starting with `"## "`, render as `<h3>` (or styled `<div>`),
remaining lines joined back as `<p>` blocks. Apply in the text display component used
across all three tabs.

---

## Implementation Order

1. `text_cleaner.py` — skip headings (US-2501) ← highest impact, no prompt tuning needed
2. Default prompts in `text_cleaner.py` + `text_summarizer.py` — heading preservation instruction (US-2502)
3. Frontend text renderer — `## ` → `<h3>` (US-2503)
4. Settings prompt reset — user can reset to new defaults via Settings UI

## Out of Scope

- Enforcing heading preservation with post-processing (regex check on LLM output)
- Collapsible chapters in UI
- Clickable chapter navigation / YouTube timestamp links
- Heading levels beyond `##` (h3, h4)
