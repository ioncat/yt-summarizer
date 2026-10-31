# Role addendum: CTO (YT Summarizer)

> Role brief: `../../team/roles/cto.md`. Rules: `../../team/AGENT_TEAM_RULES.md`. Project specifics: [`../AGENT_RULES.md`](../AGENT_RULES.md).

- Tracker and labels: <<set up on the first day: `by-<role>`, `reviewed`, `needs-owner`>>.
- Owner's panel: <<none / where>>.
- Pushing: only under `docs/team/WORK_MODES.md`; run the personal-data search per commit before each push.
- Token spending: <<the limit the owner sets, and what the CTO may start within it without asking; empty means every model run asks the owner>>.

## First day (New Start, 2026-10-31)

1. Read `.claude/memory/yt-summarizer-new-start.md` and `.claude/memory/yt-summarizer-review-2026-10-30.md` (local only; never commit the review: it describes open vulnerabilities).
2. Fill the `<<...>>` blanks in `docs/delivery/AGENT_RULES.md` and `docs/delivery/roles/*.md` from the code and `docs/project/PROJECT_REFERENCE.md`; ask the owner only what the code cannot tell.
3. Write the New Start steps 1-3 into `docs/delivery/backlog/BACKLOG.md` as items (Origin + Value first), step 1 split into small items, each one reviewable.
4. Ask the owner for the work mode (`.claude/work_mode`, now `manual`) and tell him when to open the Developer and Code Reviewer sessions.
5. Known: the MCP `get_result(include_text=true)` returns the summary, not the transcript; the tool should let the caller choose the view (subtitles / cleaned / summary / mind map).
