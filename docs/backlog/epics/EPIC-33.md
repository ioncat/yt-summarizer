# Epic 33: Benchmark Enhancement

**Status:** 🔵 Planned  
**Phase:** 2 — Summarization Quality  
**Depends on:** Epic 26 (Benchmark) ✅

---

## Strategic Context

Different content types (short clips, long courses, structured lectures) require different processing modes and respond differently to different models. A model that excels at dense Full Extract chapters may underperform on single-pass short summaries. Benchmark is the key tool for model selection per use case — making its UX and data quality critical for informed decisions.

---

## Goal

Capture real LLM performance metrics from Ollama during benchmark runs and display them per model column. All numbers must come from authoritative sources — no estimation.

---

## User Stories

### US-3301: Capture token counts and speed from Ollama

**Given** a benchmark run is triggered for any mode (single-pass / map-reduce / full_extract)  
**When** the Ollama streaming response ends (done=true message)  
**Then** `prompt_eval_count`, `eval_count`, `eval_duration` are captured from the done-object and stored in `benchmark_runs`

**Notes for Engineering:**
- Ollama done-message fields: `prompt_eval_count` (input tokens), `eval_count` (output tokens), `eval_duration` (nanoseconds of generation time)
- `tokens_per_second = eval_count / (eval_duration / 1e9)`
- For multi-call modes (map-reduce, full_extract): accumulate across all LLM calls — sum `prompt_eval_count`, `eval_count`; compute overall tok/s from total `eval_count` / total wall-clock generation time
- `text_summarizer.py` currently returns `str | None`. Must return a structured result: use `SummaryResult` dataclass `(text: str | None, prompt_tokens: int, completion_tokens: int, tokens_per_second: float, chunks_count: int)`
- All callers in `api.py` and `benchmark_service.py` must be updated for new return type
- `text_cleaner.py` is out of scope (benchmark has cleanup stage too but we'll add metrics there separately if needed)

**Out of Scope:** GPU utilization (not available from Ollama API), prompt_eval_duration (internal detail)

**Edge Cases:**
- Ollama omits token fields on error → store None, don't crash
- eval_duration = 0 → tokens_per_second = None (avoid division by zero)
- Model not loaded yet (high load_duration) → tok/s still computed from eval_duration only, load time excluded

---

### US-3302: New DB columns on BenchmarkRun

**Given** Epic 33 is being implemented  
**When** `_migrate_db()` runs  
**Then** four new nullable columns exist on `benchmark_runs`: `prompt_tokens INTEGER`, `completion_tokens INTEGER`, `tokens_per_second REAL`, `chunks_count INTEGER`

**Notes for Engineering:**
- Add to `BenchmarkRun` ORM model in `models.py`
- Add `ALTER TABLE` migration in `_migrate_db()` (check `PRAGMA table_info` first, same pattern as other migrations)
- `compression_ratio` is NOT stored — computed on the fly from existing `input_chars` / `output_chars`
- **DB backup before any schema change** (see CLAUDE.md backup rule)

**Out of Scope:** migrating existing benchmark_runs rows (will have NULLs — acceptable)

---

### US-3303: Display metrics in BenchmarkPage

**Given** a benchmark run has completed with metrics captured  
**When** the user views the Benchmark page  
**Then** each model column shows: `tok/s`, `Prompt tokens`, `Completion tokens`, `Chunks` (or `Chapters`), `Compression %`

**Notes for Engineering:**
- `compression_ratio = Math.round((1 - output_chars / input_chars) * 100)` — compute in frontend from existing fields
- Show `—` when value is null (old runs without metrics)
- `chunks_count` label: "Chunks" for map_reduce, "Chapters" for full_extract, hidden for single
- `tok/s` format: one decimal place (e.g. `12.4 tok/s`)
- Tokens: show as `↓ 1 240 / ↑ 387` (prompt / completion) or separate labeled rows

**Edge Cases:**
- Old benchmark runs (NULL metrics) → show `—` not 0
- Failed runs → all metrics null

---

## Implementation Plan (ordered by dependency)

1. 🔴 **`text_summarizer.py`** — add `SummaryResult` dataclass; capture done-object in all streaming paths; accumulate for multi-call modes
2. 🔴 **`models.py` + `database.py`** — add 4 columns + migration
3. 🟠 **`api.py`** — update callers of `summarize_text()` / `extract_notes()` to unpack `SummaryResult`; pass metrics to `finish_summary()`
4. 🟠 **`benchmark_service.py`** — pass metrics through `_run_one_model`; write to DB
5. 🟡 **`BenchmarkPage.tsx`** — render metrics row per column

---

---

## US-3304: Remove model selection limit

**Given** user opens Benchmark page  
**When** selecting models to compare  
**Then** no hard limit on model count; selected models render as horizontally scrollable columns

**Notes for Engineering:**
- Remove `prev.length < 4` guard in `BenchmarkPage.tsx` (line 102)
- Benchmark grid container: add `overflow-x: auto` + `min-width` per column (e.g. `320px`) so narrow columns don't appear
- Update label from "select up to 4" → "select models to compare"
- HTML export already uses `repeat(N, 1fr)` — no change needed there

**Out of Scope:** pagination, virtual scroll (unnecessary at realistic model counts)

---

## Wishlist (not in current scope — record only)

These ideas were captured during planning. Do not implement until explicitly prioritized.

| Idea | Description |
|------|-------------|
| **Column drag-and-drop reordering** | User drags model columns into preferred order. Persist order as `sort_order` integer column on `benchmark_runs`. Enables visual ranking. Basis for future exports that respect user's ordering. |
| **Model rating** | Mark a preferred model per benchmark run — star, heart, or similar. Stored in DB. Useful when comparing 5+ models: quickly flag the winner without re-reading all columns. |
| **User comments per run** | Inline notes field per model column — user jots observations while analyzing (e.g. "too verbose", "best for chapters"). Stored in `benchmark_runs.user_notes TEXT`. |
| **Use-case tagging** | Tag each benchmark with content type (short clip / lecture / course / etc.) to build a model→use-case lookup table over time. |

**Rationale:** Different content types suit different models. A model good at Full Extract chapters may be poor at single-pass short summaries. Benchmark + rating + comments builds institutional knowledge about which model to pick per scenario.

---

## Open Question (decide before start)

Return type change for `summarize_text()` / `extract_notes()`:
- **Option A:** `tuple[str | None, dict]` — minimal change, unpack at call sites
- **Option B:** `SummaryResult` dataclass — cleaner, self-documenting, preferred

Decision: **Option B** (dataclass)
