# Epic 17: Map-Reduce Summarization

## Summary

Extend the summarization pipeline to handle long texts that exceed the model's context window. The system automatically detects text length and switches between single-pass (current) and Map-Reduce mode. No user intervention required — the mode is chosen transparently and reported in the UI.

## Business Value

Videos longer than ~30 minutes produce transcripts that exceed the context window of local 8K models. Single-pass summarization silently fails or produces garbage output on these texts. Map-Reduce ensures the feature works reliably regardless of video length.

## Scope

### Included
- Auto-detection of summarization mode based on text length vs. context threshold
- Map-Reduce pipeline: split by paragraphs → overlapping chunks → MAP (chunk → brief summary) → REDUCE (all summaries → final)
- Overlap: last paragraph of previous chunk prepended to next chunk for continuity
- New DB fields: `summary_mode` (`single` | `map_reduce`), `summary_chunks_count`
- Separate MAP and REDUCE prompts configurable in Settings → Summarization
- UI: `· N chunks` shown in meta when `summary_mode = map_reduce`
- Cancel support for Map-Reduce (same mechanism as single-pass)

### Not Included
- Per-chunk summary storage or display (intermediate MAP results not shown in UI)
- User-configurable chunk size or overlap size
- Streaming output
- Context window auto-detection from Ollama model metadata (threshold is fixed)
- Refine / Chain-of-Density approaches (Epic 18+)

---

## User Stories

---

### US-1701: Summarize a Long Video

**Title**: System automatically uses Map-Reduce for long transcripts

**User Story**:
As a user
I want summarization to work on long videos
So that I get a useful summary regardless of video length

**Acceptance Criteria**:

*Happy path — long text (≥ 24K chars):*
- **Given** a video whose `cleaned_text` (or `formatted_text`) is ≥ 24 000 characters
- **When** I click "✦ Summarize"
- **Then** the system splits the text into overlapping paragraph-based chunks, runs MAP summarization on each, then runs REDUCE to produce the final summary
- **And** the Summary tab shows the resulting text
- **And** the meta line shows `Summarized in X:XX · model · N chunks`

*Happy path — short text (< 24K chars):*
- **Given** a video whose text is < 24 000 characters
- **When** I click "✦ Summarize"
- **Then** the system uses single-pass summarization (existing behavior)
- **And** the meta line shows `Summarized in X:XX · model` (no chunk count)

*Re-run:*
- **Given** a summary already exists
- **When** I click "↺ Re-run summary"
- **Then** the system re-evaluates text length and picks the appropriate mode again

**Edge Cases**:
- Text is exactly 24 000 characters → Map-Reduce mode (boundary belongs to long side)
- Text has only one paragraph → treated as a single chunk, Map-Reduce still runs but with 1 chunk
- A chunk's MAP request fails → overall summarization status becomes `failed`, partial results discarded
- REDUCE request fails after all MAP calls succeed → status becomes `failed`, partial results discarded
- Ollama goes offline mid-pipeline (between MAP calls) → next MAP call fails → pipeline fails, status `failed`
- `cleaned_text` is null → fallback to `formatted_text`, same mode-detection logic applies

**Out of Scope**:
- Letting the user manually choose the mode
- Showing per-chunk MAP summaries in the UI
- Retrying individual failed chunks

**Notes for Engineering**:
- Threshold constant `MAP_REDUCE_THRESHOLD = 24_000` in `text_summarizer.py`
- Split by paragraphs (separated by `\n\n`) — do not split mid-sentence
- Chunk assembly: accumulate paragraphs until adding the next would exceed `CHUNK_SIZE = 3000` chars; start a new chunk; prepend last paragraph of previous chunk as overlap
- MAP prompt: short instruction — extract key points from this section
- REDUCE prompt: combine section summaries into a final coherent summary
- Both MAP and REDUCE prompts configurable in `pipeline_settings` (new keys: `map_prompt`, `reduce_prompt`); seeded with defaults on first launch
- `is_cancelled` lambda checked before each MAP call (same pattern as cleanup cancel)
- `summary_mode` and `summary_chunks_count` written to DB on completion

**Dependencies**:
- Epic 15 (summarization pipeline, cancel pattern, DB columns)
- Epic 7 (pipeline_settings table for MAP/REDUCE prompts)
- Epic 13 (ollama_url from DB)

---

### US-1702: See Which Mode Was Used

**Title**: Meta line shows Map-Reduce chunk count

**User Story**:
As a user
I want to know how my summary was produced
So that I understand why it took longer and can calibrate expectations

**Acceptance Criteria**:

- **Given** a summary produced by Map-Reduce
- **When** I open the Summary tab
- **Then** the meta line reads `Summarized in X:XX · model · N chunks`

- **Given** a summary produced by single-pass
- **When** I open the Summary tab
- **Then** the meta line reads `Summarized in X:XX · model` (no chunk info)

**Edge Cases**:
- `summary_chunks_count` is null (e.g. old record before this epic) → chunk count not shown, no error

**Out of Scope**:
- Showing individual chunk summaries
- Progress bar per chunk during processing

**Notes for Engineering**:
- `summary_chunks_count` returned from `GET /api/result/{video_id}` alongside existing summary fields
- Frontend: append `· {chunks} chunks` to meta string if `summary_mode === 'map_reduce'`

**Dependencies**:
- US-1701

---

### US-1703: Cancel Map-Reduce Summarization

**Title**: Stop button cancels Map-Reduce mid-pipeline

**User Story**:
As a user
I want to stop a running Map-Reduce summarization
So that I can switch models or abort a slow job without waiting for all chunks to finish

**Acceptance Criteria**:

- **Given** Map-Reduce summarization is running (any stage)
- **When** I click "✕ Stop"
- **Then** the current MAP or REDUCE call is allowed to finish, but no further calls are made
- **And** `summary_status` resets to `null`
- **And** no partial summary text is stored
- **And** the "✦ Summarize" button reappears

**Edge Cases**:
- Cancel arrives between MAP and REDUCE → REDUCE is not started, status resets
- Cancel arrives during the final REDUCE call → REDUCE finishes but result is discarded, status resets
- User clicks Stop twice → second click is a no-op (idempotent)

**Out of Scope**:
- Saving partial results (e.g. summaries of already-processed chunks)

**Notes for Engineering**:
- Reuse `_SUMMARY_CANCEL_SET` in `api.py` — no new mechanism needed
- `is_cancelled()` checked before each MAP call and before the REDUCE call
- Same `DELETE /api/result/{video_id}/summary` endpoint, no changes

**Dependencies**:
- US-1701
- Epic 15 (cancel pattern)

---

### US-1704: Inline Model Selector Reflects Active Mode

**Title**: Model selector on Result page shows model for active summarization mode

**User Story**:
As a user
I want the inline model selector on the Result page to reflect the model for the current mode (Single Pass or Map-Reduce)
So that I know which model will actually be used when I run summarization

**Acceptance Criteria**:

- **Given** Map-Reduce mode is active (force_map_reduce = true)
- **When** I open the Summary tab on the Result page
- **Then** the inline model selector shows and saves the model for Map-Reduce mode

- **Given** Single Pass mode is active (force_map_reduce = false)
- **When** I open the Summary tab on the Result page
- **Then** the inline model selector shows and saves the model for Single Pass mode

**Edge Cases**:
- Mode changes in Settings while Result page is open → selector does not auto-update (acceptable; user reruns summarization)

**Out of Scope**:
- Real-time sync between Settings and Result page model selector

**Notes for Engineering**:
- Result page needs to know current `force_map_reduce` flag — either fetch from `/api/settings` or add to `/api/result/{video_id}` response
- Model for Map-Reduce = `pipeline_settings['summarization'].model` (shared for now; separate models per mode is out of scope)
- Currently both modes share the same model — this story becomes relevant only if/when separate models per mode are introduced

**Dependencies**:
- US-1701

---

## Status

**Status**: 🔵 Planned
**Priority**: 🟠 P1
