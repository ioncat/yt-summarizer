# Documentation conventions: tasks, changelog, epics

## Document map

| Document | Location | Contains | Never contains |
|---|---|---|---|
| Task tracker | named in `AGENT_RULES.md` row 20 | Open work: issues with status, priority, labels | History, delivered features |
| CHANGELOG | `docs/delivery/CHANGELOG.md` | Delivered features and fixes, reverse-chronological | Plans, open tasks |
| Ideas | `docs/discovery/*.md` | Designs not yet committed to | — |
| Sessions | `.claude/sessions/` | Per-session logs (gitignored) | — |

## Tasks

- Only the CTO writes to the tracker; the owner may write too and his edits win.
- First line of every issue: `Origin: <who asked, when, in what words>`.
- Second line of every issue: `Value: <what gets better and for whom, and what hurts without it>`. An issue without a stated value is not handed out.
- User-facing issue: User story (As a / I want / So that), acceptance criteria as Given / When / Then, edge cases, out of scope, dependencies. Technical issue: Origin, goal, acceptance criteria, out of scope.
- Every issue carries an executor label per role (`by-backend`, `by-frontend`, ...) and `reviewed` after an independent review. The closing comment names who did it, the commit hashes, the tests and who reviewed.
- Delivered: close the issue and add a CHANGELOG bullet that names the issue id, in the same session.

## CHANGELOG

One `## YYYY-MM-DD` section per delivery date, one bullet per feature or fix: `**Name**: what changed; key files; test delta`. Bug fixes: `**Bug fix — ...**` with the root cause. Append-only: corrections are new entries. A backend or client change that adds something the user sees says "User-visible: yes".


## Session end checklist

1. A CHANGELOG bullet for every delivered feature.
2. Delivered issues closed (CTO).
3. A session log written.
