# Claude Code Guidelines — YT Summarizer

**Project:** extract, clean, summarize and store YouTube (and local) video transcripts, so the user can scan a video before deciding to watch it.
**Version:** 2.0 (2026-10-31): the team works by TeamKit.
**Status:** in use by the owner; New Start, the team restarted after the review of 2026-10-30.
**Kind / stack / depth:** web / Python FastAPI + React TypeScript / MVP

---

## Project overview

**What:** a local web app with an MCP server. A video URL or file goes through subtitles or speech-to-text, then LLM cleanup, a summary and a mind map, all stored in SQLite.
**Why:** reduce the time spent on videos that turn out not to be worth watching.
**Current goal:** New Start, in this order:
1. The security minimum: bind to 127.0.0.1, a safe cookie upload, URL checks with `--` before the URL in yt-dlp calls, no HTML in the mind map, uploads and cookies gitignored.
2. Housekeeping: one launcher and one port, tests green, "processing" status reset on start, `.env` loading, `kill-backend.bat` scoped.
3. Restructure with no new features: one pipeline instead of two, the large files split into modules.
4. Only then new features.

The review behind it is in `.claude/memory/yt-summarizer-review-2026-10-30.md` (local, gitignored); the plan is in `.claude/memory/yt-summarizer-new-start.md`.

## Technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 (backend, MCP), TypeScript (frontend) |
| Framework | FastAPI, SQLAlchemy async; React + Vite + Tailwind |
| Storage | SQLite (aiosqlite) |
| Video and speech | yt-dlp (+ Node.js runtime), ffmpeg; STT engines Whisper and Qwen3-ASR |
| LLM | Ollama, local |
| Tests | pytest (`app/backend/tests`, `app/tests`), vitest (`app/frontend`) |
| Agent interface | MCP server `app/mcp_server.py` |

## Project structure

```
app/backend/        FastAPI app: routers/, services/, models/, tests/   — Developer
app/frontend/       React app: src/pages, src/components, tests        — Developer
app/mcp_server.py   MCP server (+ app/tests)                            — Developer
app/data/           runtime data: DB, uploads, cookies (gitignored)     — nobody commits it
docs/delivery/      backlog/, CHANGELOG, team addenda                   — CTO
docs/team/          TeamKit rules and role briefs                       — do not edit per project
docs/project/       PROJECT_REFERENCE.md (history, API, implementation details), plan, effort log
```

Ownership in detail: `docs/delivery/AGENT_RULES.md`. The full former reference (epics, API endpoints, implementation details): `docs/project/PROJECT_REFERENCE.md`.

## Rules by kind and depth

- Web: a browser smoke plan covers every screen and function before a release.
- Depth MVP: small and fast; only risky changes (data, security, money, outward calls) are reviewed. During New Start steps 1-3, every change is reviewed: they touch security and structure.

## Team

This project is built by a team of agent sessions under one owner (the human). Read, once at session start:
1. `docs/team/AGENT_TEAM_RULES.md` (common rules),
2. your role brief in `docs/team/roles/`,
3. the project addendum `docs/delivery/AGENT_RULES.md` and `docs/delivery/roles/<your role>.md`.

Sessions:
- **CTO**: plans, writes the backlog, routes reviews and pushes.
- **Developer**: one session for backend, frontend and MCP; it reads all three role briefs.
- **Code Reviewer**: read-only.

Start messages: `docs/team/START_PROMPTS.md`. Work mode and who pushes: `docs/team/WORK_MODES.md`.

## Session memory (mandatory)

- Session logs: `.claude/sessions/YYYY-MM-DD-short-description.md` (gitignored). On start read the latest; on end write Done, Decisions, Next, Commits.
- Project memory: `.claude/memory/` (gitignored).

## Documentation

- Open tasks: `docs/delivery/backlog/BACKLOG.md` and `docs/delivery/backlog/epics/`, by `docs/delivery/product-delivery-conventions.md`.
- Delivered work: `docs/delivery/CHANGELOG.md`.
- Follow `docs/delivery/documentation-conventions.md`.
- `docs/project/effort-log.md` stays the owner's time log.

## Common commands

| Command | Purpose |
|---|---|
| `cd app/backend && python -m pytest -q` | Backend tests |
| `cd app && python -m pytest -q tests` | MCP server tests |
| `cd app/frontend && npm test` | Frontend tests (vitest) |
| `make dev` (or `start.vbs` on Windows) | Start backend + frontend. Until New Start step 2 there are several launchers and ports; step 2 leaves one |

## Critical rules

- **Run the tests before every commit.** A red test blocks the commit; never delete or weaken a test to get green.
- **The backend listens on 127.0.0.1 only.** No endpoint accepts a path or a program to run from the request, and every file name from input is reduced to its base name.
- **External programs** (yt-dlp, ffmpeg) get a list of arguments, never a shell string, and `--` before any user-supplied URL.
- **Model output is untrusted text.** It is never rendered as HTML.
- **One pipeline.** New processing stages go into the one pipeline, never into a second copy.
- **Keep files small.** A file over about 400 lines is split before features are added to it.
- **No personal data, secrets, cookies or user media in tracked files.** `app/data/` stays gitignored; fixtures are synthetic.
- **Tests grow cumulatively.** Each chunk adds tests and never removes them. Tests never touch the live database (rule 19).

**Last updated:** 2026-10-31
