# Start messages and launch order

A CTO cannot create full agent sessions. You (the owner) open each session and paste its one-line start message. Name the session as shown so the others can find it with `ListAgents`.

## Launch order

1. **CTO** (name it `CTO`). It reads the rules, sets up the tracker labels (`by-<role>`, `reviewed`, `needs-owner`) and tells you what to open next.
2. **Developer** (one session for backend, frontend and MCP).
3. **Independent Reviewer** (read-only; opened when the first risky change needs a look).

Open them one at a time; each sends the CTO a line "ready".

## Start messages (paste the whole line)

| Role | Session name | Message |
|---|---|---|
| CTO | `CTO` | `Read docs/team/roles/cto.md, then docs/delivery/roles/cto.md, then docs/team/AGENT_TEAM_RULES.md and CLAUDE.md, and follow them.` |
| Developer | `Developer` | `Read docs/team/roles/backend.md, docs/team/roles/frontend.md and docs/team/roles/mcp.md, then docs/delivery/roles/backend.md, docs/delivery/roles/frontend.md and docs/delivery/roles/mcp.md, and follow them. You are the one Developer session of this project: you own all three areas.` |
| Independent Reviewer | `Code Reviewer` | `Read docs/team/roles/code-reviewer.md, then docs/delivery/roles/code-reviewer.md, and follow them.` |

## When a session loses its context

Paste the same message again, then: "Read the latest file in `.claude/sessions/` and continue."

## Waking a sleeping session

The CTO can send a message to an existing session (it arrives as a user turn). It cannot create a new one.
