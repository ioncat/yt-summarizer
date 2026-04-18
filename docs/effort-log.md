# Effort Log — yt-summarizer

Time analysis based on git history (commit timestamps).

> Methodology: session time = difference between first and last commit of the day.
> Sessions with a single commit are estimated at 15 min (minimum).

---

## Session log

| Date | Commits | Work description | Session time |
|------|---------|-----------------|-------------|
| 2026-04-18 | 13 | Full project bootstrap: discovery docs, repo structure, FastAPI backend, DB models, subtitle extractor (yt-dlp, cookies, 429 fix), text formatter, DB service layer, REST API (5 endpoints), Phase 2 architecture docs | ~1 h 35 min (15:06–16:41) |

*Table updated after each session.*

---

## Phase summary

| Phase | Commits | Time |
|-------|---------|------|
| Docs & Planning | 3 | ~15 min |
| Phase 1 — Backend (extractor + formatter + API) | 7 | ~1 h |
| Phase 1 — Docs (Phase 2 architecture) | 3 | ~20 min |
| **Total** | **13** | **~1 h 35 min** |

---

## How to update

After each session run:

```bash
# View commits with timestamps
git log --pretty=format:"%h %ad %s" --date=format:"%Y-%m-%d %H:%M"

# View commits for a specific day
git log --after="2026-04-18 00:00" --before="2026-04-18 23:59" --pretty=format:"%h %ad %s" --date=format:"%H:%M"
```

Then update the tables above manually (or ask Claude).

---

## Session 1 — 2026-04-18

| Parameter | Value |
|-----------|-------|
| Date | 2026-04-18 |
| Status | ✅ Phase 1 backend complete |
| Completed | Discovery docs, repo structure (Docker, Makefile, .gitignore), FastAPI + DB models (4 tables), subtitle extractor via yt-dlp (fixed 429 with single-call approach, deduplicated rolling window VTT cues), text formatter (map-reduce overlap removal + time-gap paragraphs), DB service layer (CRUD), REST API (POST /process, GET /status, GET /result, GET /history, DELETE /result), Phase 2 map-reduce architecture documented |
| Blockers | HTTP 429 on VTT download (resolved: combined --print-json + --write-subs into single yt-dlp call). YouTube cookies required (Get cookies.txt LOCALLY extension). |
| Commits | 13 |
| Time | ~1 h 35 min (15:06–16:41) |
| Next | Frontend (React + TypeScript, Epic 5) |
