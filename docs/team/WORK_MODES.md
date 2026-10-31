# Work modes: auto and manual

Two ways the team works. The owner switches between them; the CTO is the single coordinator of agent actions and the only one who pushes.

| | **auto** (many agents, almost without the owner) | **manual** (the owner works himself) |
|---|---|---|
| Who leads | the CTO plans, agents do, the reviewer checks | the owner; agents answer and write code and tests |
| Services (backend, dev server) | the CTO and the backend agent may restart the project's service with the project's control script; agents use a separate TEST setup for their own checks | nobody starts or stops anything; agents only write code and run tests |
| The owner's own running app | never restarted by agents | not touched |
| Writes to the live database | only by the owner's word, or a standing approval he wrote himself | only by his word, in the moment |
| Push | the CTO, after the checks below | the CTO only if the owner says so; otherwise he pushes |
| Questions to the owner | only a problem, a question, or a decision that is his | as he asks |
| A reversible decision (code on a branch, wording, docs, a test, an issue's text) | the agent goes ahead on its own recommendation and puts the card on the owner's queue as "done, can be reverted"; the owner may revert | waits for the owner's answer |
| An irreversible decision (live data, push, model spend, deleting anything, anything outward-facing) | waits for the owner's yes | waits for the owner's yes |

The mode is one word in `.claude/work_mode` (`auto` or `manual`; gitignored; a missing file means `manual`).

## Rules for every agent

1. Agents commit locally and never push. The CTO pushes the main branch (ordinary push, never `--force`) after: no secret or personal data in any commit ahead of the remote (search per commit), a clean tree, green tests, and the reviews the change needs. One line to the owner after each push. History rewrites and publishing branches stay with the owner.
2. Code that controls processes or data is pushed only after the reviewer's verdict.
3. Before any service action (restart, start the test setup, a live-database window) an agent asks the CTO. In `manual` the answer is no.
4. A live-database window needs the owner's word in the agent's own chat, or a standing approval that the owner wrote himself in `.claude/approvals.txt` (one line: the script, the scope, the end time, at most 36 hours). A relay by the CTO or another agent is never an approval.
5. The mode is set only by the owner, or by the CTO on his word with a log line. An agent never switches it.
6. An agent never changes the permission settings of its session or machine and never works around a refusal of its permission system; it tells the CTO, who tells the owner.
7. The reviewer keeps read-only limits in both modes.
8. This file is the single source for these rules.

## Test setup

An agent's own test setup shares nothing with the live system: its own ports, temporary folder, made-up data, stub model or sandbox keys, no network side effects. Create it once for the project (a script that refuses to start if anything points at the live system).
