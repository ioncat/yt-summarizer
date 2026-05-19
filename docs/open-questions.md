# Open Questions

Design and architecture questions without a final answer yet. Different from bugs — these are decisions that can be deferred and revisited based on real-world usage. When a question is resolved, move the decision into the relevant epic / docs and delete the entry here.

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
