# Open Questions

Design questions and known issues without a final answer yet. Decisions that can be deferred and revisited based on real-world usage. When resolved, move the decision into the relevant epic / docs and delete the entry here.

---

## Specific Ollama model hangs on every chunk — `qwen3.5:4b` (19.05.2026)

### The problem

Map-Reduce summarization on a 134K-char video with `qwen3.5:4b` failed every single MAP chunk (51 of 51) with `httpx.ReadTimeout` at exactly 180s each. Total time wasted: ~2.5 hours. Final summary status: `failed`.

Log pattern (every ~3 minutes):
```
[WARNING] services.text_summarizer: _call_ollama failed: [ReadTimeout]
[INFO]    services.text_summarizer: map_reduce: MAP N/51 (~3000 chars)
```

Eventually: `MAP chunk 1 failed — aborting`.

### What rules out the easy explanations

- **Not a model-name typo:** model dropdown is populated from Ollama's `/api/tags` — the name `qwen3.5:4b` was confirmed present via `ollama list`. Couldn't be wrong.
- **Not thinking mode in general:** other reasoning models (`gemma4:e4b`, larger Qwen variants) ran fine on the same hardware. So just "thinking model = slow" is wrong.
- **Not low timeout:** 180s should be plenty for a 4B model on a 3K-char chunk.

### Plausible real causes (untested)

- This particular Ollama build of `qwen3.5:4b` has a broken/incompatible chat template in its Modelfile
- Context window for this specific model variant too small — chunk + system prompt exceeds it, Ollama hangs instead of returning an error
- Bug in this exact q4 quant of this model

### What to do when it recurs

1. Test the model directly with `curl http://localhost:11434/api/chat -d '{"model":"...","messages":[{"role":"user","content":"hi"}],"stream":true}'` and time the first token
2. Try smaller and larger chunks — narrows down to context-size issue
3. Check Ollama's server log for the model load
4. Switch to a different model — confirmed-working ones include `cas/aya-expanse-8b`, `gemma3:4b`, `qwen2.5-coder:14b`, `gemma4:e4b`

### Defensive idea (not implemented)

Before launching a long summarization, do one quick health probe (1–2K chars, 30s timeout). If that fails, abort the run with a clear error instead of letting all N chunks time out for 2+ hours. ~30 min to implement; saves a lot of wasted compute.

---

## Cleanup timeout on large chapter paragraphs (17.05.2026)

### The problem

Chapter-aware formatting on a 5-hour video produces ~58 large chapter-sized paragraphs. Each paragraph sent to Ollama in `text_cleaner.py` with a 120s timeout (`httpx.ReadTimeout`). With slow/large models, every paragraph times out → cleanup silently falls back to original text. Result: `cleaned_text` ends up as a copy of `formatted_text`, no actual cleanup happened.

### Side effects

- UI and History may appear slow/empty during heavy Ollama load (backend event-loop starved)
- No clear signal to user that cleanup is failing — log shows `Ollama failed on paragraph: ` (empty exception message)

### Options

1. **Bump timeout** from 120s to 300s+ — naive fix, doesn't help if model is genuinely too slow
2. **Split large paragraphs** before sending to LLM — keeps timeout reasonable, more LLM calls
3. **Use faster model** for cleanup — user choice, requires education
4. **Parallel MAP** (Epic 29) — already implemented; helps if `OLLAMA_NUM_PARALLEL` set, doesn't fix per-paragraph timeout

### Recommendation

Combine **2 + 3**: split large paragraphs (>3000 chars) into sub-chunks within `text_cleaner.py`, plus surface a UI hint when cleanup completes with cleaned_text == formatted_text (likely silent fail).

---

## Transient "Could not load result" on cleanup/summary finish (18.05.2026)

### The problem

Frontend `loadResult()` polls `GET /api/result/{video_id}` every few seconds. At the moment a background task transitions `processing → done` (backend writes `finish_*` row), a coincident poll request can fail → first catch handler shows "Could not load result" full-screen error. Next poll succeeds, but user already saw the error.

### Recommendation

In `loadResult` catch, count consecutive failures, only show error after 2–3 in a row. Single transient miss = ignore, retry on next tick. ~10 min fix.

---

## Summary output format inconsistency across modes (19.05.2026)

### The problem

Each processing mode emits a different output shape. Format is determined by per-mode prompts in `text_summarizer.py`. There is no central "format contract" — each mode evolved its own style.

| Mode | Prompt asks for | Actual output |
|---|---|---|
| Single-pass | "5–7 concise bullet points" | bullets `- ...` |
| Map-Reduce MAP | "Detailed paragraph, no bullets" | dense prose paragraph |
| Map-Reduce REDUCE | "Thematic sections with short headings + paragraphs" | sectioned doc |
| Full Extract | "Extract and structure all key content, preserve facts" | mixed: `## ` chapters preserved, body is prose or bullets at model's discretion |

**Where the prompts live:**

- `text_summarizer.py` — `DEFAULT_*_PROMPT` constants
- DB `pipeline_settings` table — user overrides per stage (`summarization`, `summarization_extract`, `summarization_combine`)
- Full Extract prompts only live in code — no Settings UI tab for them yet, always uses defaults

**Frontend renderer (`utils/renderText.tsx`):**

- Recognizes `## ` headings → `<h3 class="chapter-heading">`
- Everything else → `<p class="text-paragraph">`
- **Does not recognize bullets** (`- `, `* `) — they render as plain text

### Why this might be a problem

- Unpredictable visual language between modes
- Copy-paste of bullets to other tools loses list semantics
- Map-Reduce paragraphs feel different from Full Extract chapters

### Why this might NOT be a problem

Each mode serves a different purpose:

- **Single-pass** = quick overview → bullets justified
- **Map-Reduce** = condensed narrative → paragraphs justified
- **Full Extract** = detailed reference → chapters + mixed content justified

The "inconsistency" mirrors content goals: short scan vs narrative vs reference. Similar to how a news brief, a magazine article, and a textbook chapter all look different — and that's correct.

### Options if we decide to unify

**Option A — Markdown-lite contract (recommended over react-markdown)**

Single output shape for all modes:

- `## Heading` (already supported)
- Plain paragraphs
- Bullets: lines starting with `- ` or `* `
- Nothing else — no tables, nested lists, bold, italic

Steps:

1. Update all prompts to enforce this shape (per-mode differences only in **content goal**: compress vs preserve, not in **format**)
2. Extend `renderText()` to detect bullet lines and render as `<ul><li>`
3. Cost: ~1–2h of code

**Option B — react-markdown** ❌

Already attempted as Epic 8, dropped because LLM output was inconsistent enough to break rendering. Not recommended.

**Option C — Status quo** ✅ (current default)

Leave it. Each mode = different product. Reassess after 2–3 weeks of real-world use. If bullets from map-reduce annoy in practice, or copy-paste workflows suffer, then revisit.

### Recommendation

**Defer.** Current state works because each mode targets a different use case. Premature format unification is wasted effort. Revisit only if real usage surfaces friction.

### Related

- Epic 8: react-markdown rendering — ❌ Dropped
- Epic 19: Prompt Management v2 — 🔵 Planned (language-aware prompts; could be the place to bundle format contract too)
- Epic 25: Chapter heading preservation — ✅ Done (`## ` invariant established)
