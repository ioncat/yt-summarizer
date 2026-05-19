# YT Summarizer — User Guide

Complete guide to using YT Summarizer. For a one-page intro, see [README](../README.md). For minimal setup steps, see [Quick Start](quick-start-guide.md).

---

## Table of Contents

1. [Overview](#overview)
2. [Setup](#setup)
3. [Processing pipeline](#processing-pipeline)
4. [Processing modes](#processing-modes)
5. [Features](#features)
6. [Settings reference](#settings-reference)
7. [Troubleshooting](#troubleshooting)
8. [FAQ](#faq)

---

## Overview

YT Summarizer extracts a YouTube video's subtitles, cleans them up with a local LLM, and produces a summary you can scan in seconds. All LLM work runs on your machine via **Ollama** — no data leaves the device.

**Typical use cases:**
- Decide whether a video is worth watching before committing time
- Turn a 5-hour course into a structured reference document
- Search through video content as text (Ctrl+F on a transcript)
- Ask follow-up questions about the content via local chat

---

## Setup

### Prerequisites

1. **Ollama** — running locally. Default URL: `http://localhost:11434`. Pull at least one model:
   ```
   ollama pull qwen2.5:7b
   ```
2. **yt-dlp** — installed and accessible. Path is set in Settings.
3. **Node.js v18+** — only needed if running the frontend dev server directly.
4. **YouTube cookies** — required to bypass age-restriction and 429 rate limits. Export via "Get cookies.txt LOCALLY" Chrome extension into `app/data/www.youtube.com_cookies.txt`.

### First-time setup in the web UI

After launching the app, open **Settings → General** and fill in:

- **Ollama URL** — usually `http://localhost:11434`
- **yt-dlp path** — full path to your `yt-dlp` executable
- **Cookies path** — path to your exported cookies file (or upload via the **Upload** button)

Then go to **Settings → AI Cleanup** and **Settings → Summarization** and pick a model for each stage. Without a model selected, those stages will be skipped.

---

## Processing pipeline

```
YouTube URL
    ↓
① Extract        — yt-dlp pulls subtitles + metadata + chapters
    ↓
② Format         — VTT parsing, dedup, paragraph splitting (chapter- or gap-based)
    ↓
③ AI Cleanup     — Ollama cleans each paragraph: punctuation, fillers, fragments
    ↓
④ Summarize      — Ollama produces a summary or structured digest
    ↓
⑤ Chat Q&A       — ask questions about the content (preserves context)
```

Each stage's output is stored separately in SQLite and shown as its own tab in the Result page: **Subtitles · Cleaned · Summary**. You can re-run any stage independently.

---

## Processing modes

Summarization automatically picks a mode based on text length and whether the video has chapters. The selection is determined by **video content type** which falls into one of these categories:

### Video content types

| Type | Condition | Auto-selected mode |
|---|---|---|
| 📄 **Short** | text < 24,000 chars | Single-pass |
| 📑 **Long** | text ≥ 24,000 chars, no chapters | Map-Reduce |
| 📚 **Long Structured** | text ≥ 24,000 chars, has YouTube chapters | Full Extract |
| 📕 **XL** (planned, Epic 18) | text > 50,000 chars, no chapters | Hierarchical Map-Reduce |

This classification is shown as a label on the History page so you can see at a glance how each video will be processed.

### Auto-selection logic

When you trigger summarization, the backend picks the mode using these rules in order:

1. **Force Map-Reduce override:** if Settings → Summarization → Force Map-Reduce is **ON** → use Map-Reduce regardless of other factors.
2. **Long Structured detection:** if video has chapters (`video.chapters` is not empty in DB, populated from yt-dlp metadata) AND `len(text) >= 24,000` → use **Full Extract** (`extract_notes()`). Each `## ` section gets its own LLM call. No REDUCE step. Results concatenated in order, preserving chapter structure.
3. **Map-Reduce threshold:** if `len(text) >= 24,000` → use **Map-Reduce** (`summarize_text()` with `force_map_reduce=true`). Split into ~3K-char chunks → MAP each → REDUCE all into final summary.
4. **Default:** use **Single-pass**. One LLM call with full text → bullet-point summary.

### Mode behavior summary

| Mode | LLM calls | Compression | Preserves structure | Best for |
|---|---|---|---|---|
| Single-pass | 1 | High (5-7 bullets) | No | Short videos, single-topic clips |
| Map-Reduce | N MAP + 1 REDUCE | Medium | Sometimes | Long tutorials without chapters |
| Full Extract | N (one per chapter) | None (lossless) | Yes (`## ` headings) | Courses, lectures with chapters |
| Hierarchical | N MAP + M intermediate REDUCE + 1 final REDUCE | Medium | Sometimes | Very long flat content (planned) |

The active mode is shown in the Summary tab meta line:
- Single-pass: `Summarized in 4:12 · qwen2.5:7b`
- Map-Reduce: `Summarized in 4:12 · qwen2.5:7b · 28 chunks · 82% compressed`
- Full Extract: `Summarized in 4:12 · qwen2.5:7b · Full Extract · 12 chapters`

### When to use which

- **Short video / single topic** → Single-pass picks itself, no action needed
- **Tutorial without chapters** → Map-Reduce — gets condensed but loses detail
- **Long structured course with chapters** → Full Extract — preserves all content, structured by chapter
- **Force Map-Reduce override** → toggle in Settings → Summarization. Useful for A/B testing the same video across modes via the Benchmark page.

### Expected behavior per mode

How to recognize each mode is running correctly on your screen.

#### Single-pass (📄 Short videos)

**While running:**
- Summary tab shows `Summarizing: 0:XX` (no chunk/chapter counter — it's one LLM call)

**After completion:**
- Meta line: `Summarized in X:XX · <model>` (no mode label)
- Output: 5–7 bullet points capturing main ideas
- High compression (output is much shorter than input)

#### Map-Reduce (📑 Long videos, no chapters)

**While running:**
- Meta line shows `Summarizing: X:XX · chunk N / M` — model is going through chunks
- After all chunks done, REDUCE step runs (no separate counter for it)

**After completion:**
- Meta line: `Summarized in X:XX · <model> · N chunks · K% compressed`
- Output: narrative paragraphs grouped into thematic sections with `## ` headings invented by the LLM
- Medium compression (typically 50–85%)

**Watch out:** if you see `MAP chunk 1 failed — aborting` in the backend log, the model isn't responding correctly. Try a different model.

#### Full Extract (📚 Long Structured)

**While running:**
- Meta line shows `Summarizing: X:XX · chapter N / M` — note the word **"chapter"**, not "chunk"
- One LLM call per `## ` chapter heading in the formatted text

**After completion:**
- Meta line: `Summarized in X:XX · <model> · Full Extract · N chapters`
- Output preserves every original `## Chapter Title` from the video author
- Each chapter is processed independently — no REDUCE step, no cross-chapter compression
- Compression near 0% or sometimes negative (output longer than input). This is **correct**: Full Extract is lossless by design

**Verify correctness:**
- Meta says "Full Extract · N chapters" (not "N chunks")
- All chapter headings from the source video are present in the output

**Negative test:** to force Map-Reduce instead, enable Settings → Summarization → Force Map-Reduce. Re-run Summary; meta should show "chunks" instead of "chapters".

#### Hierarchical Map-Reduce (📕 XL, planned)

Not yet implemented. See Epic 18 in the backlog.

---

## Features

### AI Cleanup

Takes the raw subtitle text and fixes punctuation, removes filler words ("ну", "вот", "как бы", "you know"), and merges broken sentence fragments. Processes paragraph by paragraph. Chapter headings (`## Title`) bypass the LLM and pass through unchanged.

**Cancel:** "✕ Stop" button while running. Previous result is preserved on cancel (not erased).

**Live progress:** `Cleaning: 1:23 · paragraph 12 / 87`.

### AI Summarization

Generates a summary using the auto-selected mode. Live chunk/chapter counter while running. Cancel button stops cleanly.

**Compression ratio** shown in meta when done: `82% compressed`. Lower = more aggressive condensation. Full Extract typically shows close to 0% (lossless).

### Chat Q&A

On the Summary tab, ask follow-up questions about the video. Backend proxies to Ollama with full context (source text + summary hidden in system message). Multi-turn dialogue, copyable. Streaming response.

### Benchmark — model comparison (Epic 26)

Compare 2–4 models side by side on the same input text. From the Result page → **⚖ Benchmark** button → select models → Run.

- N-column layout (CSS Grid)
- Synchronized scroll across columns
- Mode badge + duration + compression per model
- Export HTML for sharing
- Same auto-mode logic as production pipeline

### Auto language detection

Default in the Home page dropdown is "Auto (detect)". Picks the video's original language from yt-dlp metadata. Manual override (en, ru, etc.) still available.

### Chapter-aware formatting

If the video creator defined YouTube chapters, subtitles are grouped by chapter boundaries with `## Chapter Title` headings. The headings are **immutable** — they pass through cleanup and summarization unchanged.

### Auto-pipeline

Checkbox on the Home page: "Run AI cleanup automatically" — runs Extract → Cleanup → Summarize in one go. Pre-flight check validates that all required settings are configured before starting.

### Completion notifications

When cleanup or summarization finishes while you're on another tab:
- Tab title changes to `✓ Done` for 10 seconds
- Browser Notification fires (if granted)

Permission is requested lazily on first action.

---

## Settings reference

### General tab

| Field | Description |
|---|---|
| **Ollama URL** | URL of your local Ollama instance. Default: `http://localhost:11434` |
| **yt-dlp path** | Full path to the `yt-dlp` executable |
| **Cookies path** | Path to YouTube cookies file (Netscape format). Required to avoid 429 errors |
| **Parallel workers** *(Epic 29)* | Number of paragraphs/chunks processed in parallel. Default 1. Must match `OLLAMA_NUM_PARALLEL` on your Ollama server for actual speedup |

### AI Cleanup tab

| Field | Description |
|---|---|
| **Model** | Ollama model used for cleanup. No default — must be selected |
| **System prompt** | Role-setting message sent first to the LLM |
| **User prompt template** | Per-paragraph prompt. `{text}` is replaced with the paragraph content |
| **Reset to defaults** | Restores hardcoded prompts (useful after Epic 25 heading-preservation update) |

### Summarization tab

Two sub-tabs:
- **Single-pass** — used for short texts
- **Map-Reduce** — used for long texts (MAP prompt + REDUCE prompt separately)

Plus:
- **Model** — applies to both sub-tabs
- **Force Map-Reduce** — toggle that bypasses Full Extract auto-selection

---

## Troubleshooting

### "Ollama failed on paragraph" warnings in the log; no actual cleanup happens

**Cause:** the model is timing out (default 120s) on large paragraphs from chapter-aware formatting. A 5-hour video may have chapters of 5K–10K chars each.

**Solutions:**
- Use a faster/smaller model (`qwen2.5:3b` instead of `qwen2.5:14b`)
- Increase `OLLAMA_KEEP_ALIVE` and `OLLAMA_NUM_CTX` on the server
- Enable parallel workers (Settings → Parallel workers) with `OLLAMA_NUM_PARALLEL` set on Ollama

### History page shows "No videos processed yet" but I know videos exist

Hard-refresh the page (Ctrl+F5). The first request may have timed out while the backend was busy with another task. Refresh re-queries the DB directly.

### 429 Too Many Requests from YouTube

**Cause:** YouTube rate-limit. Common after many rapid downloads or with expired cookies.

**Solutions:**
- Re-export cookies via "Get cookies.txt LOCALLY" (Chrome) and re-upload via Settings
- Wait 30+ minutes
- Use a different IP (VPN)

### "Language not available" error

The requested language has no subtitles for this video. The UI shows a list of **available** languages with one-click retry buttons. Pick one of those.

### Summary text empty after summarization "completed"

Likely all MAP chunks failed (model timeout, OOM, or unloaded). Check backend log for `Ollama failed` entries. Try a smaller model or shorter text.

### Cleanup/summary disappears after I cancel

**Fixed in current version** (`fix: preserve cleaned/summary text on cancel`). Cancel now resets only status and timestamps; the previous text remains visible.

### Backend says "Backend unreachable" in StatusBar

Backend process died. Check the terminal where you started uvicorn. Most common cause: port `8001` already in use, or `init_db()` failed due to a corrupted DB file (restore from `*.sqlite.bak`).

### Frontend shows white page after a deploy

Vite HMR didn't recover from a syntax error. Stop and restart `npm run dev`. Check browser console for the failed import.

---

## FAQ

**Q: Does any data leave my machine?**  
A: No. LLM work is local via Ollama. Only yt-dlp talks to YouTube (to download subtitles). No analytics, no telemetry.

**Q: Can I use this without Ollama?**  
A: Subtitle extraction works without Ollama. Cleanup and summarization require a running Ollama instance. Without it, those tabs are greyed out.

**Q: Can I run this in Docker?**  
A: Yes. `docker compose up --build` from the project root. Note: Ollama must be accessible from inside the container — point `Ollama URL` to your host's IP, not `localhost`.

**Q: How do I add a new prompt for cleanup?**  
A: Settings → AI Cleanup → edit the **User prompt template**. Use `{text}` as the placeholder for the paragraph being processed. Save.

**Q: Where is the data stored?**  
A: `app/data/db/yt_summarizer.sqlite`. Cookies in `app/data/www.youtube.com_cookies.txt`. Both gitignored. Back up the DB before any schema migration.

**Q: How do I delete a single video?**  
A: From the History page or the Result page — Delete button removes the video and all its associated subtitle/cleanup/summary data.

**Q: Can I export results?**  
A: Currently:
- Copy any tab content via the "Copy" button
- Benchmark page has HTML export
- Direct SQLite query if you need bulk export
