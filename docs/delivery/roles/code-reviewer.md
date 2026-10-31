# Role addendum: Independent Reviewer (YT Summarizer)

> Role brief: `../../team/roles/code-reviewer.md`. Rules: `../../team/AGENT_TEAM_RULES.md`. Project specifics: [`../AGENT_RULES.md`](../AGENT_RULES.md).

- Lenses used here: code and security (default); others on request (see the role brief).
- No findings register at this depth: report findings to the CTO, who keeps what matters in the tracker.
- Tests on a clean export: `cd app/backend && python -m pytest -q` and `cd app && python -m pytest -q tests`.
- Security focus here: `/api/process` (URL input), `/api/settings/upload-cookies` (file path from client), `/api/download/direct` (URL + subprocess), `/api/settings/app` (sets executable path), mind map render (LLM HTML → DOM), all yt-dlp subprocess calls.
- Never read personal files or user profiles.
