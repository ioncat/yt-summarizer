# Role addendum: Backend agent (YT Summarizer)

> Role brief: `../../team/roles/backend.md`. Rules: `../../team/AGENT_TEAM_RULES.md`. Project specifics: [`../AGENT_RULES.md`](../AGENT_RULES.md).

- Stack and entry points: Python 3.12 + FastAPI; entry point `app/backend/main.py`; venv at `app/backend/.venv`; backend runs on `localhost:9010`.
- Files you own: `app/backend/` and `app/backend/tests/` — see full table in `../AGENT_RULES.md`.
- Test command: `cd app/backend && python -m pytest -q`; live data is never touched by tests (conftest patches engine to `:memory:`).
