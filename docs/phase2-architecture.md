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

## Key Principle

> One-shot decision: watch or skip. No accumulation, no search, no return.

The user needs a summary short enough to read in 30 seconds and accurate enough
to make a reliable watch/skip decision. That's the only success criterion.

History in DB is incidental (avoid reprocessing same video), not a feature.
RAG and cross-video search are out of scope — the task is inherently single-use.
