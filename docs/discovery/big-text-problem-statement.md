# Problem Statement — yt-summarizer

## Core Problem

**Convert a raw transcription of a long video (60K to 300K+ characters) into a readable document — with semantic and structural integrity, at the quality level of a newspaper article or study material.**

## Conditions Where the Problem Manifests

1. **Volume:** 60K–300K+ characters of raw VTT transcription
2. **Local hardware:** a single LLM on a consumer machine. No cloud APIs, no horizontal scaling
3. **LLM context:** limited (8K–32K tokens). The full text does not fit
4. **Time:** processing takes minutes to hours; the user is not willing to wait days
5. **Input quality:** YouTube auto-transcription — no punctuation, filler words ("uh", "like", "you know"), broken sentences, the same idea repeated in different words

## What We Need to Achieve

### Meaning

- Preserve **all key facts, examples, terms, numbers, and arguments**
- Invent nothing new (anti-hallucination)
- Do not compress where the author already structured the material (courses, lectures with chapters)
- Compress where the content is news, reviews, or conversational

### Form

Output must meet the standard of a readable document:

- **Paragraphs** of reasonable size, thematic
- **Headings** for sections / chapters
- **Direct speech, quotes** — where present (if the author quotes someone, format it as a quote)
- **Lists, enumerations** — where appropriate (steps, options, factors)
- **Punctuation and capitalization** — correct
- **No fillers or repetition**

### Structure — Two Scenarios

| Scenario | Input | Expected Output |
|---|---|---|
| **Author marked chapters** | YouTube chapters → `## Heading` | Structured reference by chapter. All facts preserved. Minimal compression. Document like a textbook. |
| **No author markup** | Continuous text | LLM identifies thematic sections itself. Compression is acceptable — the user is willing to lose detail for readability. |

### Adaptive Intent

The same long text may be needed in different modes:

1. **TL;DR** — bullets, 5 minutes of reading
2. **Structured summary** — paragraphs by topic, 20 minutes
3. **Full reference** — chapters like a book, one hour of reading, nothing lost

All three = one pipeline with different modes (see [USER_GUIDE → Processing modes](../guides/USER_GUIDE.md#processing-modes)).

## Anti-Patterns (What We Do NOT Want)

- ❌ A wall of raw text without paragraphs or headings
- ❌ Hard compression to 5% when the user wanted details
- ❌ Hallucinated facts not present in the video
- ❌ A list of Markdown tables with emoji where literary text is expected
- ❌ Hours of processing with no visible progress
- ❌ Loss of semantic boundaries — e.g., a thought cut off mid-sentence due to bad chunking

## Success Metrics

- **Compression ratio** — compression as a percentage (already shown in the UI)
- **Lossless score** (future) — what percentage of named entities, numbers, and dates from the source made it into the output
- **Processing time** — total and per 1K characters
- **Structure** — number of sections / paragraphs, average size

## Related Docs

- [USER_GUIDE.md](../guides/USER_GUIDE.md) — user processing modes
- [CLAUDE.md](../../CLAUDE.md) — technical architecture
- [open-questions.md](open-questions.md) — unresolved design questions
- [phase2-architecture.md](../engineering/phase2-architecture.md) — Map-Reduce details
- [backlog/BACKLOG.md](../delivery/backlog/BACKLOG.md) — epics
