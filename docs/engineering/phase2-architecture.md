# Phase 2 Architecture: LLM Summarization

## The Core Problem

Both YT Summarizer and OnPage Summarizer share the same fundamental challenge:
**accurate meaning extraction from text**.

Reading is faster than watching video if you're focused, but the goal is to delegate
the reading itself to a machine — and have it return meaning, not just shorter text.

Single-pass LLM summarization fails at this because:
- The model decides what's important based on statistical patterns, not your context
- It compresses everything at once → loses local detail
- Errors spread across the entire output, not localized

---

## Chosen Approach: Map-Reduce Summarization

```
Phase 1 output (paragraphs)
│
├── paragraph 1 → LLM → summary_1
├── paragraph 2 → LLM → summary_2   ← MAP
├── paragraph 3 → LLM → summary_3
│   ...
│
└── [summary_1, summary_2, summary_3 ...] → LLM → final_summary   ← REDUCE
```

**Why it works:**
- Each paragraph = one idea → LLM focused, less information loss
- Paragraph summaries are detailed and localized
- Final summary combines meaning, not raw text
- Errors stay isolated to individual paragraphs

---

## Alternative Approaches

| Approach | How | Best for | Risk |
|----------|-----|----------|------|
| **Map-Reduce** | Each chunk → summary, then combine | Long videos, parallel processing | Loses cross-paragraph connections |
| **Refine** | summary[i] + chunk[i+1] → new summary | Narrative content, continuity | Slow (sequential), early errors propagate |
| **Chain of Density** | Iteratively add detail to sparse summary | High-quality single summary | Slower, more LLM calls |
| **Extractive** (TextRank) | Pick actual sentences from text | 100% faithful output | Reads mechanically |
| **RAG** | Vector embeddings + Q&A on demand | Cross-video search, interactive | Not a summary, requires user question |

---

## Recommended Architecture for Phase 2

### New DB table: `summaries`

```sql
CREATE TABLE summaries (
    id TEXT PRIMARY KEY,
    video_id TEXT REFERENCES videos(id),
    level TEXT,              -- 'paragraph' | 'document'
    paragraph_index INTEGER, -- NULL for document-level
    summary_text TEXT,
    model_used TEXT,
    created_at DATETIME
);
```

### Processing pipeline

```
subtitle_extractor → text_formatter → [Phase 1 done]
                                            ↓
                                    paragraph_summarizer (MAP)
                                            ↓
                                    document_summarizer (REDUCE)
                                            ↓
                                    summaries table
```

### Two output levels

- **Paragraph summaries** — detailed, one per paragraph. User can drill into any section.
- **Document summary** — concise, combines all paragraph summaries.

---

## Output Size

Target length is measured in **words, not time** — reading speed is individual.

Default: `summary_words = 500`. Configurable — user adjusts based on preference.
Range to experiment with: 300–1000 words. This is the human "context window" for
a watch/skip decision, and it's personal. Since this is a single-user tool, that's fine.

## Key Principle

> One-shot decision: watch or skip. No accumulation, no search, no return.

Success criterion: summary is short enough to read quickly AND accurate enough
to make a reliable watch/skip call. Word count is the lever to tune that balance.

History in DB is incidental (avoid reprocessing same video), not a feature.
RAG and cross-video search are out of scope — the task is inherently single-use.

---

## How the Model Context Is Assembled

Every call to Ollama sends two messages: `system` and `user`. Neither is sent as-is from
Settings — the final prompt is assembled in code from several sources.

### What you see in Settings vs. what the model receives

| Layer | Source | Visible in Settings? | Example |
|---|---|---|---|
| System prompt | Settings → stage | ✅ Yes | "You are a helpful assistant..." |
| Language instruction | Video metadata (`language` field) | ❌ No — injected by code | `"Respond in Russian.\n"` |
| User prompt template | Settings → stage | ✅ Yes | `"Write a detailed paragraph... Section:\n{text}"` |
| Input text | DB (`cleaned_text` or `formatted_text`) | ❌ No | actual subtitle content |

### Assembly order (user message sent to model)

```
[language instruction] + [user prompt template with {text} filled in]
```

Example for a Russian video, MAP step:
```
Respond in Russian.
Write a detailed paragraph summarizing all key information from this section.
Include all important facts, numbers, names, examples, and arguments.
Do not skip any significant point. Do not compress aggressively.
Keep the SAME language as the input text.
Return ONLY the paragraph — no bullet points, no intro, no comments.

Section:
[3000 chars of subtitle text]
```

### Where language instruction comes from

`language` is stored in the `videos` table — set at extraction time by yt-dlp
(e.g. `"ru"`, `"en"`, `"uk"`). At summarization time, `_run_summary` reads it from
`get_result()` and passes it to `summarize_text()`. The function `_language_instruction()`
converts the code to a full name (`"ru"` → `"Russian"`) and prepends it to every
Ollama call — MAP, REDUCE, and single-pass alike.

```python
# text_summarizer.py
_LANGUAGE_NAMES = {"ru": "Russian", "en": "English", "uk": "Ukrainian", ...}

def _language_instruction(language: str | None) -> str:
    if not language:
        return ""
    name = _LANGUAGE_NAMES.get(language.lower(), language)
    return f"Respond in {name}.\n"
```

If `language` is `null` in DB (e.g. old records before language detection was added),
the instruction is silently omitted — the model falls back to its own judgment.

### Why prepend, not embed

Placing `Respond in Russian.` at the very **start** of the user message — before the
task instructions — makes it the highest-priority directive in the prompt. Models tend
to follow instructions that appear early more reliably than those buried mid-prompt.

In practice, `"Keep the SAME language as the input text."` inside the prompt template
was consistently ignored by `qwen3:8b` and `cas/aya-expanse-8b:latest` when processing
Russian input — both defaulted to English output regardless. This is not necessarily
a function of model size; larger models may exhibit the same behaviour depending on
their instruction-following training. Prepending an explicit `Respond in Russian.`
solved this completely — the model treats it as a hard constraint rather than a soft
suggestion.

### Why this is not in the Settings prompt

The language instruction is **data-driven**, not prompt-driven. The same prompt template
works for any language — the correct language is injected automatically per video.
Putting it in the Settings prompt would require the user to update it manually every time
they process a video in a different language, which defeats the purpose.

### Future context injections (not yet implemented)

The same pattern can be extended to inject other per-video data:
- Video title → "The video is titled: {title}"
- Duration → context about expected density
- Domain/channel → hints about terminology

---

## Observed Scaling Behaviour (empirical, 30.04.2026)

Current implementation: `CHUNK_SIZE = 3 000`, `MAP_REDUCE_THRESHOLD = 24 000`.
Model tested: Qwen2.5-Coder-14B.

| Input size | Chunks | Output size | Compression | Quality |
|---|---|---|---|---|
| ~26 000 chars | ~9 | ~10 600 chars | ~40% | ✅ Good |
| ~75 000 chars | ~25 | ~1 500 chars | ~2% | ❌ Too compressed |

**Root cause of degradation at large scale:**
The REDUCE step receives all MAP outputs concatenated. With ~9 chunks this is
manageable; with ~25 chunks the combined input approaches or exceeds the model's
context window, causing aggressive over-compression.

**MAP step** performs consistently — produces a detailed paragraph per chunk regardless
of total text size. The bottleneck is exclusively in REDUCE.

**Potential fix for large texts: hierarchical (3-level) Map-Reduce**
```
chunks → MAP → partial summaries
         ↓
    group into batches of ~8 → intermediate REDUCE
         ↓
    combine batch results → final REDUCE
```
This keeps every REDUCE call within a safe input size regardless of total text length.
Not yet implemented — tracked as a future improvement.
