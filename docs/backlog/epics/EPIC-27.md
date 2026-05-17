# Epic 27: Full Extract (No-Reduce Mode)

**Phase**: 2 — Summarization Quality  
**Status**: 🔵 Planned  
**Priority**: 🟠 P1

## Goal

For long, structured content (courses, lectures, documentaries) where **losing any detail is unacceptable**, the standard map-reduce pipeline is inappropriate — its REDUCE step aggressively compresses content.

Full Extract is a **lossless processing mode**: each chapter (or fixed-size chunk if no chapters) is sent to the LLM with a "structure and clarify, do not compress" instruction. Results are concatenated directly — **no REDUCE step**. The output is a clean, structured document that preserves all key facts, examples, and points from the original.

This mode is the primary choice for:
- Multi-hour courses with YouTube chapters
- Technical lectures where every detail matters
- Any content where the user wants a reference document, not a digest

---

## Processing Logic

```
With chapters (primary path):
  foreach chapter in video.chapters:
      chunk = subtitle text for that chapter
      result = LLM(chunk, prompt="extract_notes")   ← no compression
  output = "## Chapter Title\n\n" + result per chapter, concatenated

Without chapters (fallback):
  Same as map-reduce MAP step, but no REDUCE
  Fixed 3K char chunks → LLM(chunk, prompt="extract_notes") → concatenated
```

**Key difference from map-reduce:** no REDUCE step. Output length ≈ cleaned_text length, not compressed.

---

## Mode Selection

Processing mode is auto-selected based on content, but user can always override.

| Condition | Auto-selected mode |
|---|---|
| text < 24K | Single-pass |
| text ≥ 24K, no chapters | Map-Reduce |
| text ≥ 24K, has chapters | **Full Extract** (this epic) |
| text > 50K, no chapters | Hierarchical Map-Reduce (Epic 18) |

User override via mode selector in Summary tab (Epic 28).

---

## User Stories

---

### US-2701: Full Extract runs chapter-by-chapter without REDUCE

**As a** user processing a long structured video (course, lecture)  
**I want** the LLM to process each chapter independently and concatenate results without a REDUCE step  
**So that** no content is lost due to compression

#### Acceptance Criteria

**Given** video has chapters and text ≥ 24K chars  
**When** Full Extract mode runs  
**Then** each chapter's subtitle text is sent to LLM as a separate request with the extract prompt  
**And** results are concatenated in chapter order with `## Chapter Title` headings preserved  
**And** no REDUCE step is called

**Given** Full Extract completes  
**When** user views Summary tab  
**Then** output contains all original `## Chapter Title` headings  
**And** each section contains structured notes (not a compressed abstract)

#### Edge Cases

- Chapter with very long subtitle text (>8K chars) → split into sub-chunks, concatenate sub-results within that chapter section before moving to next
- Chapter with empty subtitle text → heading still emitted, content marked "(no content)"
- LLM partially fails on one chunk → that chunk emitted as-is (raw subtitle text), processing continues
- Video has chapters but `has_chapters = false` in DB (reprocessing edge case) → fall back to chunk-based no-reduce

#### Out of Scope

- Re-ranking or re-ordering chapter content
- Cross-chapter synthesis or linking related concepts
- Generating a table of contents (separate feature)

#### Notes for Engineering

New `summary_mode = "full_extract"` value in DB.

New prompt constants in `text_summarizer.py`:
```python
DEFAULT_EXTRACT_SYSTEM_PROMPT = """You are a content extraction assistant. \
Your task is to extract and structure all key information from the provided text. \
Preserve ALL facts, examples, definitions, steps, and important points. \
Do NOT summarize or compress — restructure for clarity only. \
Remove filler words, repetitions, and off-topic digressions. \
If the text starts with a '## ' heading, preserve it at the top of your output."""

DEFAULT_EXTRACT_USER_PROMPT = """Extract and structure the following content. \
Preserve all key information. Output clean, structured prose or bullet points.\n\n{text}"""
```

New function `extract_notes(text, chapters, ...)` in `text_summarizer.py`:
- If `chapters` provided: iterate chapters, slice subtitle text by chapter boundaries, call LLM per chapter
- If no chapters: split into 3K chunks (same as map-reduce), call LLM per chunk
- Concatenate with chapter headings, return full text

DB: `summary_mode` column already exists. Set to `"full_extract"` on trigger.

---

### US-2702: Auto-select Full Extract for chapter videos

**As a** user running summarization on a video with chapters  
**I want** Full Extract to be automatically selected as the default mode  
**So that** I get lossless output without having to configure anything

#### Acceptance Criteria

**Given** video has chapters (`has_chapters = true`) and `len(text) >= 24000`  
**When** summarization is triggered (button click or auto-pipeline)  
**Then** backend automatically uses Full Extract mode  
**And** Summary tab meta shows `"Full Extract · N chapters · model"` (not "Map-Reduce")

**Given** video has no chapters and `len(text) >= 24000`  
**When** summarization is triggered  
**Then** backend uses existing Map-Reduce mode (unchanged behavior)

#### Edge Cases

- Video has chapters but all chapters have empty text → fall back to map-reduce on full text
- `has_chapters = true` but `video.chapters` is null/empty in DB → treat as no-chapters

#### Out of Scope

- Manual mode override UI (Epic 28)
- Changing auto-select thresholds via Settings

#### Notes for Engineering

In `api.py` `_run_summarization()`:
```python
use_full_extract = (
    has_chapters
    and video.chapters
    and len(input_text) >= 24_000
)
if use_full_extract:
    result = await extract_notes(input_text, video.chapters, ...)
else:
    result = await summarize_text(input_text, ...)  # existing logic
```

Pass `video.chapters` from DB to the summarization call. Already available via `get_result()`.

---

### US-2703: Full Extract progress visible in UI

**As a** user watching Full Extract run  
**I want** to see per-chapter progress (not just a spinner)  
**So that** I know the job is running and how far along it is

#### Acceptance Criteria

**Given** Full Extract is running  
**When** user views Summary tab  
**Then** progress shows `"Extracting chapter N / M..."` updated in real time  
**And** cancel button is available (same as existing cancel for summarization)

**Given** Full Extract completes  
**When** user views Summary tab meta  
**Then** meta shows `"Full Extract · N chapters · X:XX · model"`

#### Edge Cases

- Single-chapter video → progress shows "Extracting chapter 1 / 1..."
- Progress update fails (polling gap) → last known chapter count shown, not empty

#### Out of Scope

- Per-chapter cancel (cancel stops at next chapter boundary, not mid-chapter)
- Estimated time remaining

#### Notes for Engineering

Reuse existing `summary_status = "processing"` + polling mechanism. Add `summary_chunks_count` (already in DB — repurpose for chapter count in full_extract mode). Frontend polls `GET /api/result/{video_id}` — add `summary_progress` field: `{"current": N, "total": M, "mode": "full_extract"}` to the response while processing.

Alternatively: emit progress via the existing chunks_count field updated incrementally (simpler, no schema change).

---

## Implementation Order

1. `text_summarizer.py` — `extract_notes()` function + prompt constants (US-2701)
2. `api.py` — auto-select logic in `_run_summarization()` (US-2702)
3. Frontend meta label — "Full Extract · N chapters · X:XX" (US-2702)
4. Progress display — chapter counter during processing (US-2703)

## Out of Scope (Epic level)

- Manual mode override UI — Epic 28
- Hierarchical REDUCE for large chapter-less texts — Epic 18
- Cross-chapter semantic linking
- Export to DOCX/PDF
