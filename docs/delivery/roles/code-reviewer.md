# Role addendum: Independent Reviewer (YT Summarizer)

> Role brief: `../../team/roles/code-reviewer.md`. Rules: `../../team/AGENT_TEAM_RULES.md`. Project specifics: [`../AGENT_RULES.md`](../AGENT_RULES.md).

- Lenses used here: code and security (default); others on request (see the role brief).
- No findings register at this depth: report findings to the CTO, who keeps what matters in the tracker.
- Tests on a clean export: <<command>>.
- Security focus here: <<endpoints that take outside input, network sends, SQL from input, subprocess calls, file paths from input, personal data>>.
- Never read personal files or user profiles.
