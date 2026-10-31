# Role addendum: CTO (YT Summarizer)

> Role brief: `../../team/roles/cto.md`. Rules: `../../team/AGENT_TEAM_RULES.md`. Project specifics: [`../AGENT_RULES.md`](../AGENT_RULES.md).

- Tracker and labels: `by-backend`, `by-frontend`, `by-mcp`, `by-cto`, `reviewed`, `needs-owner`; board is `docs/delivery/backlog/BACKLOG.md`.
- Owner's panel: none.
- Pushing: the owner pushes (CTO has no git credentials for the remote). CTO signals readiness: no secrets in commits, clean tree, green tests, reviews done.
- Token spending: no separate limit; ask the owner before bulk model runs (multiple videos, benchmarks) and before any paid external API call.

## Persistent roles

Each role is **one permanent session**, not one session per task. The owner knows each session by name and accumulates context there.

- **Developer** — one session, handles backend + frontend + MCP. Send new tasks via `SendMessage` to its session id, never start a new session for a new task.
- **Code Reviewer** — one session, read-only. Same: send tasks via `SendMessage`.
- **QA** — one session, browser-driven. Called before NS-11 and after each NS-11 stage commit.

Session titles are role names only (`Developer`, `Code Reviewer`, `QA`). The task number goes in the message body, not the title.

When a session loses context after many compressions: send it "Read the latest file in `.claude/sessions/` and continue." A new session is opened only when the old one is permanently confused or explicitly archived by the owner.

## First day (New Start, 2026-10-31)

1. Read `.claude/memory/yt-summarizer-new-start.md` and `.claude/memory/yt-summarizer-review-2026-10-30.md` (local only; never commit the review: it describes open vulnerabilities).
2. Fill the `<<...>>` blanks in `docs/delivery/AGENT_RULES.md` and `docs/delivery/roles/*.md` from the code and `docs/project/PROJECT_REFERENCE.md`; ask the owner only what the code cannot tell.
3. Write the New Start steps 1-3 into `docs/delivery/backlog/BACKLOG.md` as items (Origin + Value first), step 1 split into small items, each one reviewable.
4. Ask the owner for the work mode (`.claude/work_mode`, now `manual`) and tell him when to open the Developer and Code Reviewer sessions.
5. Known: the MCP `get_result(include_text=true)` returns the summary, not the transcript; the tool should let the caller choose the view (subtitles / cleaned / summary / mind map).
