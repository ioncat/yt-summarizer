# Agent rules: project addendum

> The common rules for every agent session are in [`../team/AGENT_TEAM_RULES.md`](../team/AGENT_TEAM_RULES.md). This page holds only what is specific to this project; rule numbers are the same as in the common file. Role addenda: [`roles/`](roles/). Work modes and who pushes: [`../team/WORK_MODES.md`](../team/WORK_MODES.md).

## Project specifics, by rule

| Rule | In this project |
|---|---|
| 1-3 Reports | The CTO session is named `CTO`. The owner's panel: <<none / a page / a file>> |
| 4-5 Talking to the owner | Chat language: Russian. The first row of the question table carries the tracker id. Product or user-journey questions go first to <<the product-minded agent, if any>>; the owner gets only what is his by nature (pushes, live data writes, restarts, changes to team rules, the decisions marked as his) |
| 6-7 Commits | The working tree is shared by all sessions. Use a temporary index (`GIT_INDEX_FILE`) when the shared index holds other people's staged changes |
| 9 File ownership | See the table below |
| 10 Database | The live DB is <<path>>; backups go to <<path>>; a migration is an idempotent startup step; a live write waits for the owner's word |
| 11 Services | Run through <<command/script>>; restarts follow `../team/WORK_MODES.md` |
| 12 Personal data | The repository is public. <<What counts as personal data here?>> Guard tests: <<names>> |
| 14 Quality gates | Tests: <<command>>; static analysis: <<command>>; other gates: <<>> |
| 15 Docs | `CHANGELOG.md` and the tracker issue closed by the CTO, per `documentation-conventions.md` |
| 16 UI | <<How the owner confirms a visual change; is there a browser preview?>> |
| 19 Tests and the live DB | A fixture sets the DB path to a throwaway file for every test: <<file>> |
| 20 Task tracker | The board is `docs/delivery/backlog/BACKLOG.md` (epics in `docs/delivery/backlog/epics/`, written by `docs/delivery/product-delivery-conventions.md`), no tracker key. Only the CTO writes to it (among agents). Each handout carries an issue id; name it in your report and commit message. Issue format: `Origin:` first (who asked, when, in what words); user-facing issues use User story + Given/When/Then + edge cases + out of scope + dependencies; technical ones the short form Every issue also carries a `Value:` line right after `Origin:` (what gets better and for whom); an issue without it is not handed out. |
| 21 Labels | `by-backend`, `by-frontend`, `by-mcp`, `by-cto`, `reviewed`, `needs-owner` |
| 18 Session log | `.claude/sessions/YYYY-MM-DD-short-description.md` (gitignored) |

## File ownership (rule 9)

| Owner | Files |
|---|---|
| Backend | <<folders and their tests>> |
| Frontend | <<folders and their tests>> |
| MCP | <<agent interface folder>> (for example `mcp_server/`) and its tests |
| CTO | `docs/delivery/AGENT_RULES.md`, `docs/delivery/roles/`, the owner's panel |
| Reviewer | read-only; findings go to the CTO in the report |
| Shared, each for its own entries | `docs/delivery/CHANGELOG.md` |

## Role addenda

- [CTO](roles/cto.md)
- [backend](roles/backend.md)
- [frontend](roles/frontend.md)
- [mcp](roles/mcp.md)
- [code-reviewer](roles/code-reviewer.md)
