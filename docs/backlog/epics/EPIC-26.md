# Epic 26: Benchmark — Side-by-Side Model Comparison

**Phase**: 2 — Summarization Quality  
**Status**: 🔵 Planned  
**Priority**: 🟡 P2

## Goal

Allow the user to run 2–4 models on the same input text using the **same processing pipeline** (same mode logic as production), and compare results side by side. The purpose is to evaluate model quality for cleanup and summarization, not just output — but to understand how each model handles the exact same processing scenario.

---

## Key Principle: Same Mode, Different Models

The benchmark does not bypass the pipeline — it runs through it.

```
input_text + has_chapters + text_length
         ↓
    [mode selector]   ← same logic as _run_summary / _run_cleanup
         ↓
  single | map_reduce | full_extract | hierarchical
         ↓
  run mode × N models in parallel
         ↓
  benchmark_runs: one row per model, mode + duration recorded
```

Mode is auto-selected from input characteristics. User can force a specific mode via override (useful for testing edge cases).

---

## DB Schema

New table `benchmark_runs`:

```sql
CREATE TABLE benchmark_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL,
    stage       TEXT NOT NULL,       -- 'cleanup' | 'summary'
    mode        TEXT NOT NULL,       -- 'single' | 'map_reduce' | 'full_extract'
    model       TEXT NOT NULL,
    input_chars INTEGER NOT NULL,
    output_text TEXT,
    output_chars INTEGER,
    duration_seconds INTEGER,
    created_at  TEXT NOT NULL
)
```

Migration via `_migrate_db()` — new table, not a column addition, so `CREATE TABLE IF NOT EXISTS`.

---

## User Stories

---

### US-2601: Run benchmark on a video

**As a** user evaluating model quality  
**I want** to select 2–4 models and run them on the same video text  
**So that** I can compare output quality under identical conditions

#### Acceptance Criteria

**Given** a video with formatted or cleaned text  
**When** user opens `/benchmark/:videoId`, selects N models, and clicks "Run"  
**Then** backend runs all N models in parallel on the same input text  
**And** mode is auto-selected based on text length and `has_chapters` (same logic as production)  
**And** each model's result is saved as a separate row in `benchmark_runs`  
**And** results appear in the UI as they complete (streaming or polling)

**Given** user wants to test a specific mode regardless of auto-selection  
**When** user selects a mode override before running  
**Then** all models run in that forced mode

#### Edge Cases

- One model fails / times out → its column shows error, others complete normally
- User runs benchmark twice on same video → new rows added, old rows preserved (history)
- No models selected → "Run" button disabled
- Only one model selected → allowed (useful for re-running with different mode override)

#### Out of Scope

- Cleanup benchmark (stage = 'cleanup') — Phase 2; this story covers stage = 'summary' only
- Scheduling or background benchmark runs
- Comparing different input texts (always same video)

#### Notes for Engineering

New endpoint `POST /api/benchmark/run`:
```json
{
  "video_id": "abc123",
  "stage": "summary",
  "models": ["qwen2.5:7b", "gemma3:4b"],
  "mode_override": null   // or "map_reduce" | "full_extract" | "single"
}
```

Backend resolves mode via the same auto-select logic as `_run_summary`. Runs models with `asyncio.gather()`. Each result stored in `benchmark_runs`. Returns list of run IDs.

Use same `extract_notes()` / `summarize_text()` functions from `text_summarizer.py` — no duplication.

---

### US-2602: View results side by side

**As a** user comparing model outputs  
**I want** to see N model results in parallel columns with synchronized scrolling  
**So that** I can compare quality at the same position in the document

#### Acceptance Criteria

**Given** benchmark has completed for N models  
**When** user views `/benchmark/:videoId`  
**Then** page shows N columns in CSS Grid `repeat(N, 1fr)` layout  
**And** each column header shows: model name, mode badge, duration, output char count  
**And** `## ` headings in output rendered as `<h3>` (same as ResultPage)  
**And** scrolling one column scrolls all others to the same position

**Given** N = 1  
**When** user views the page  
**Then** single column fills available width (no layout break)

**Given** N = 4  
**When** user views on a narrow screen  
**Then** layout switches to 2×2 or single-column scroll (responsive breakpoint)

#### Edge Cases

- Model output is null (failed) → column shows "❌ Failed" placeholder
- Outputs have very different lengths → columns scroll independently after user breaks sync (click to unsync)
- User has no benchmark runs for this video yet → prompt to run benchmark first

#### Out of Scope

- Diff highlighting between outputs
- Inline editing of outputs
- Sorting columns by metric

#### Notes for Engineering

`renderText()` from `ResultPage.tsx` — extract to shared utility in `utils/renderText.tsx` and reuse in both pages.

Synchronized scroll: attach `scroll` event listener to each column container; on scroll, set `scrollTop` on all other containers. Use a `syncing` ref flag to prevent recursive scroll updates.

---

### US-2603: Export benchmark as HTML

**As a** user who wants to share or archive benchmark results  
**I want** to export the current benchmark view as a self-contained HTML file  
**So that** I can open it offline or send it to others

#### Acceptance Criteria

**Given** benchmark results are displayed  
**When** user clicks "Export HTML"  
**Then** browser downloads a `.html` file containing all N columns with inline styles  
**And** the file renders correctly when opened in a browser without a server  
**And** filename includes video title and date: `benchmark_<title>_<YYYY-MM-DD>.html`

#### Edge Cases

- Title contains special characters → sanitized in filename (replace `/\:*?"<>|` with `_`)
- Very long output (293K chars) → export still works (client-side generation, no size limit)

#### Out of Scope

- PDF export
- Server-side export generation
- Sharing via link

#### Notes for Engineering

Pure client-side: build HTML string from current results, use `URL.createObjectURL(new Blob([html], {type: 'text/html'}))` + temporary `<a>` click. Include inline CSS (copy relevant rules from `index.css`). No backend needed.

---

### US-2604: Mode badge and metrics per column

**As a** user reading benchmark results  
**I want** to see which processing mode each model ran in and key metrics  
**So that** I can interpret results correctly (single-pass vs map-reduce vs full-extract)

#### Acceptance Criteria

**Given** a completed benchmark run  
**When** user views a column  
**Then** column header shows:
  - Model name
  - Mode badge: `Single` | `Map-Reduce · N chunks` | `Full Extract · N chapters`
  - Duration: `X:XX`
  - Compression: `N% compressed` (or `+N% expanded` if output > input)

**Given** two columns used different modes (e.g. one forced map-reduce, one full-extract)  
**When** user views both  
**Then** each column shows its own mode badge independently

#### Edge Cases

- Duration null (run failed mid-way) → show "—"
- Output longer than input → show "+N% expanded" in amber

#### Out of Scope

- Per-chunk metrics breakdown
- Token count (not available from Ollama /api/chat)

#### Notes for Engineering

All data available from `benchmark_runs` row: `mode`, `duration_seconds`, `input_chars`, `output_chars`. Compute compression client-side: `Math.round((1 - output_chars / input_chars) * 100)`.

---

### US-2605: Mirror primary runs into benchmark_runs (Original entry)

**As a** user who already summarized or cleaned a video from the Result page  
**I want** that primary run to appear automatically on the Benchmark page as the first column  
**So that** I can compare subsequent models against my baseline without re-running the original

#### Acceptance Criteria

**Given** a user runs summarization (or cleanup) from the Result page  
**When** the run completes successfully  
**Then** a row is inserted into `benchmark_runs` with `triggered_by='main'`, full output, model, duration, and input_chars

**Given** the Benchmark page is opened for that video  
**When** runs are rendered  
**Then** the mirrored row appears alongside any `triggered_by='benchmark'` rows  
**And** the column shows a **📌 Original** badge to distinguish it

**Given** user re-runs summarization with a different model from the Result page  
**When** the new run completes  
**Then** a new `benchmark_runs` row is inserted (history preserved, not overwritten)

#### Edge Cases

- Failed run (`status='failed'`) still inserted into `benchmark_runs` for visibility
- Run without a configured model → no benchmark_runs insert (no value)
- Re-run same model from Benchmark page → newest run wins in dedup-by-model display

#### Out of Scope

- Per-version diff view between original and benchmark runs
- Manual deletion of individual benchmark rows from UI

#### Notes for Engineering

`finish_summary()` and `finish_cleanup()` in `video_service.py` perform the INSERT after updating `subtitles_formatted`. Fields populated from existing data: model from primary row, input_chars from source text length, output from the function argument, duration computed from `started_at` to now.

---

### US-2606: Benchmark cleanup stage in addition to summary

**As a** user choosing between models for AI cleanup (heavy operation)  
**I want** to benchmark several models on the same cleanup task  
**So that** I can pick the best speed/quality tradeoff before running cleanup on long videos

#### Acceptance Criteria

**Given** the Benchmark page is open  
**When** user selects "Cleanup" stage  
**Then** model selector + Run button work for cleanup as for summary  
**And** Mode dropdown is hidden (cleanup has no modes)  
**And** Run uses `text_cleaner.clean_text()` instead of summarize/extract

**Given** cleanup-stage runs exist for a video  
**When** user toggles stage Summary ↔ Cleanup  
**Then** display switches between the two stage filters; summary and cleanup runs are NOT shown together

**Given** the user runs cleanup from the Result page  
**When** the cleanup completes  
**Then** a `benchmark_runs` row with `stage='cleanup'`, `mode='cleanup'`, `triggered_by='main'` is also inserted (mirrors US-2605 logic)

#### Edge Cases

- Cleanup operates on `formatted_text` (raw subtitles), not on `cleaned_text` — important when same model already cleaned the text
- Large videos: cleanup-benchmark can take hours per model; UX warning would help (out of scope here)
- Mode column for cleanup runs stored as literal `'cleanup'` to keep the schema uniform

#### Out of Scope

- "Sample mode" — cleanup only first N paragraphs for quick comparison (future feature)
- Cleanup quality scoring / diff against original — future epic
- Side-by-side cleanup + summary in the same view

#### Notes for Engineering

`start_benchmark(..., stage)` accepts `'summary'` (default) or `'cleanup'`. For cleanup:
- `mode = 'cleanup'`
- `source_text = fmt['formatted_text']` (raw)
- `_run_one_model` dispatches to `clean_text()` instead of `summarize_text()`/`extract_notes()`

`POST /api/benchmark/run` request body adds `stage: 'summary' | 'cleanup'` with 'summary' as default.

Frontend: stage selector dropdown on BenchmarkPage; `displayRuns` filters by `runs.filter(r => r.stage === stage)`; Mode selector conditionally rendered only for summary stage.

---

## Implementation Order

1. DB migration — `benchmark_runs` table in `_migrate_db()` ✅
2. Backend service — `benchmark_service.py`: `run_benchmark()`, `get_benchmark_runs()` ✅
3. API endpoints — `POST /api/benchmark/run`, `GET /api/benchmark/{video_id}` ✅
4. Extract `renderText()` to shared util ✅
5. Frontend — `/benchmark/:videoId` page: model selector, run button, N-column grid, synchronized scroll ✅
6. Column headers — mode badge, duration, compression ✅
7. HTML export ✅
8. **US-2605**: mirror primary runs into `benchmark_runs` via `finish_summary` / `finish_cleanup`. Add `triggered_by` column + migration. 📌 Original badge in UI. ✅
9. **US-2606**: cleanup stage support. `start_benchmark(stage)`, `_run_one_model` cleanup branch, stage selector UI, displayRuns filter. ✅

## Out of Scope (Epic level)

- Prompt comparison (same model, different prompts) — separate epic
- Automatic benchmark on every new video
- Storing benchmark history across videos in a dashboard
- Cleanup sample mode (partial cleanup for quick benchmark)
- Quality scoring / output diffing
