# Epic 29: Parallel MAP Processing

**Phase**: 2 — Summarization Quality  
**Status**: 🔵 Planned  
**Priority**: 🟠 P1

## Goal

The current pipeline processes paragraphs and chunks **sequentially** — one LLM call at a time. For a 5-hour video with 58 chapter-sized paragraphs, this means 58 sequential calls × ~30–120s each = 30–120 minutes total.

If the user runs Ollama with `OLLAMA_NUM_PARALLEL=4` (or more), the bottleneck is artificial — we could process 4 paragraphs simultaneously and cut total time by ~4×.

This epic introduces parallel processing for all MAP-like stages: cleanup paragraphs, summarization MAP chunks, and Full Extract chapter sections. Output order is preserved via index. Parallelism is configurable.

---

## Affected stages

1. `text_cleaner.py clean_text()` — paragraph-by-paragraph cleanup
2. `text_summarizer.py _map_reduce()` — MAP step (REDUCE stays single-call)
3. `text_summarizer.py extract_notes()` — chapter section processing (no REDUCE)

The REDUCE step in map-reduce stays sequential (single call, can't parallelize).

---

## Concurrency Strategy

```python
sem = asyncio.Semaphore(parallel_workers)

async def _process_indexed(idx, item):
    async with sem:
        if is_cancelled():
            return idx, None
        result = await call_llm(item)
        return idx, result

tasks = [_process_indexed(i, item) for i, item in enumerate(items)]
results = await asyncio.gather(*tasks, return_exceptions=True)
# Sort by index, build output in correct order
ordered = [r for _, r in sorted(results, key=lambda x: x[0])]
```

Key properties:
- **Order preserved** via index sort after `gather()`
- **Concurrency limit** via `Semaphore` — protects memory and Ollama from overload
- **Cancel-aware** — each parallel task checks `is_cancelled()` before LLM call
- **Per-task failures isolated** — `return_exceptions=True` keeps successful results

---

## Configuration

New `app_settings` key: `parallel_workers` (string, integer 1–16, default `"1"`).

- `"1"` = current sequential behavior (default, safe)
- `"4"` = matches typical `OLLAMA_NUM_PARALLEL=4`
- Value above Ollama's actual capacity → no extra speed, just queued requests

Settings UI: Settings → General, near Ollama URL. Help text: "Should match OLLAMA_NUM_PARALLEL on your Ollama server."

---

## User Stories

---

### US-2901: Parallel cleanup paragraphs

**As a** user processing a long video with AI cleanup  
**I want** paragraphs to be cleaned in parallel up to a configurable limit  
**So that** cleanup of long videos finishes proportionally faster on a parallel-capable Ollama instance

#### Acceptance Criteria

**Given** `parallel_workers = 4` is set in Settings  
**When** AI cleanup runs on a video with N paragraphs  
**Then** up to 4 paragraphs are sent to Ollama simultaneously  
**And** the final `cleaned_text` preserves the original paragraph order  
**And** the order is identical to what sequential processing would produce

**Given** `parallel_workers = 1` (default)  
**When** cleanup runs  
**Then** behavior is identical to current sequential implementation

**Given** cleanup is cancelled mid-run  
**When** parallel tasks are in flight  
**Then** in-flight tasks complete their current LLM call but no new tasks start  
**And** the cleanup returns None (same as sequential cancel behavior)

#### Edge Cases

- One paragraph fails (timeout, error) → fallback to raw text (existing behavior), other paragraphs unaffected
- `## ` heading paragraphs still bypass LLM (Epic 25 invariant) — they fill their slot without acquiring semaphore
- Progress callback fires as each task completes (not in input order) — display can show "N / total completed" without per-position info

#### Out of Scope

- Dynamic concurrency adjustment based on Ollama response times
- Per-stage `parallel_workers` settings
- Streaming output before all tasks complete

#### Notes for Engineering

`text_cleaner.py clean_text()`: replace the existing `for i, p in enumerate(paragraphs)` loop with an `asyncio.gather()` pattern, gated by `asyncio.Semaphore(parallel_workers)`.

```python
sem = asyncio.Semaphore(parallel_workers)

async def _clean_indexed(idx, p):
    async with sem:
        if is_cancelled and is_cancelled():
            return idx, None
        if p.startswith("## "):
            return idx, p
        result = await _clean_paragraph(client, p, ...)
        if on_progress:
            on_progress(_completed_count(), total)
        return idx, result

tasks = [_clean_indexed(i, p) for i, p in enumerate(paragraphs)]
results = await asyncio.gather(*tasks)
ordered = [r for _, r in sorted(results, key=lambda x: x[0])]
```

Progress counter needs an atomic counter (or just count completed via list length).

---

### US-2902: Parallel MAP in map-reduce summarization

**As a** user running map-reduce summarization on a long video  
**I want** MAP chunks to be processed in parallel up to a configurable limit  
**So that** the MAP phase scales with my Ollama parallelism

#### Acceptance Criteria

**Given** `parallel_workers = 4` and a text producing 20 chunks  
**When** map-reduce runs  
**Then** up to 4 MAP chunks are processed simultaneously  
**And** chunk summaries are concatenated in original chunk order before REDUCE  
**And** REDUCE still runs as a single call (not parallelized)

**Given** `parallel_workers = 1`  
**When** map-reduce runs  
**Then** behavior is identical to current sequential MAP implementation

#### Edge Cases

- One MAP chunk fails → abort with None (current behavior preserved)
- Cancel mid-MAP → no new chunks start, in-flight finish
- Very high `parallel_workers` (e.g. 16) but only 3 chunks → only 3 parallel tasks run

#### Out of Scope

- Parallelizing REDUCE (it's a single call)
- Adaptive chunk-size based on parallelism

#### Notes for Engineering

`text_summarizer.py _map_reduce()`: same pattern as US-2901 applied to the MAP loop. REDUCE stays sequential after MAP completes.

---

### US-2903: Parallel section processing in Full Extract

**As a** user running Full Extract on a chapter-structured video  
**I want** chapters to be extracted in parallel up to a configurable limit  
**So that** the no-reduce extract scales with my Ollama parallelism

#### Acceptance Criteria

**Given** `parallel_workers = 4` and a video with 58 chapters  
**When** Full Extract runs  
**Then** up to 4 chapter sections are processed simultaneously  
**And** final output preserves chapter order (`## Chapter 1`, then `## Chapter 2`, ...)

**Given** cancellation mid-run  
**When** parallel sections are in flight  
**Then** in-flight sections complete, no new ones start, output is None

#### Edge Cases

- Section fails → fallback to raw content (existing behavior), other sections unaffected
- Heading-only section (no body text) → still acquires semaphore slot briefly, returns heading

#### Out of Scope

- Different `parallel_workers` per stage
- Reordering sections by output length

#### Notes for Engineering

`text_summarizer.py extract_notes()`: replace the existing sequential `for` loop over sections with the same indexed-gather pattern. Each section keeps its index, results sorted by index after `gather()`.

---

### US-2904: Configure parallel workers via Settings

**As a** user with a parallel-capable Ollama setup  
**I want** to configure the parallelism level in the web UI  
**So that** I can match Ollama's `OLLAMA_NUM_PARALLEL` without editing code

#### Acceptance Criteria

**Given** Settings → General page  
**When** user views the page  
**Then** "Parallel workers" field is visible with current value (default 1)  
**And** help text explains: "Match OLLAMA_NUM_PARALLEL on your Ollama server"

**Given** user enters a value 1–16 and saves  
**When** the next cleanup/summary/extract runs  
**Then** the new parallelism is applied immediately

**Given** user enters an invalid value (0, negative, non-numeric, >16)  
**When** they try to save  
**Then** an inline validation error is shown, save is blocked

#### Edge Cases

- Empty value → treat as 1
- User sets 16 but Ollama supports only 4 → no error, just no extra speed
- Setting changes mid-cleanup → applies to next run, not the current one

#### Out of Scope

- Auto-detecting Ollama's actual parallelism
- Per-model concurrency settings

#### Notes for Engineering

Add `parallel_workers` to `_seed_app_settings()` defaults (`"1"`).

Add field to Settings → General page. Read at start of each cleanup/summary/extract run from `app_settings` table (via `get_app_setting`). Cast string to int, clamp to [1, 16].

---

## Implementation Order

1. `app_settings` seed for `parallel_workers` (default `"1"`) — no schema change, key-value table
2. Refactor `text_cleaner.py clean_text()` to indexed-gather pattern (US-2901)
3. Refactor `text_summarizer.py _map_reduce()` MAP loop (US-2902)
4. Refactor `text_summarizer.py extract_notes()` (US-2903)
5. Settings UI field + validation (US-2904)
6. Pass `parallel_workers` through `api.py` to all three call sites

## Out of Scope (Epic level)

- Parallelizing REDUCE step (single call)
- Distributed processing across multiple Ollama instances
- Streaming partial results to UI as parallel tasks complete (only completed counter)
- Auto-tuning parallelism based on observed throughput
