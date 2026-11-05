# Role addendum: Backend agent (YT Summarizer)

> Role brief: `../../team/roles/backend.md`. Rules: `../../team/AGENT_TEAM_RULES.md`. Project specifics: [`../AGENT_RULES.md`](../AGENT_RULES.md).

- Stack and entry points: Python 3.12 + FastAPI; entry point `app/backend/main.py`; venv at `app/backend/.venv`; backend runs on `localhost:9010`.
- Files you own: `app/backend/` and `app/backend/tests/` — see full table in `../AGENT_RULES.md`.
- Test command: `cd app/backend && python -m pytest -q`; live data is never touched by tests (conftest patches engine to `:memory:`).
- Before every commit run all three suites (backend, MCP `cd app && python -m pytest -q tests`, frontend `cd app/frontend && npm test`) and read the exit code and the summary line of each: pytest -q must print "N passed" and exit 0 (a collection error is red), npm test must exit 0. Never judge green from `tail` or `grep` of the output. Put the three counts in the commit report (origin: commit 552d34a did not build, a SyntaxError in a test file).
