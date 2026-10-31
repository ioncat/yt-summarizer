# Role addendum: MCP agent (YT Summarizer)

> Role brief: `../../team/roles/mcp.md`. Rules: `../../team/AGENT_TEAM_RULES.md`. Project specifics: [`../AGENT_RULES.md`](../AGENT_RULES.md).

- Server folder and entry point: `app/mcp_server.py` (stdio MCP server); venv at `app/backend/.venv`.
- The product API it calls: `http://127.0.0.1:9010/api`; no auth (localhost-only bind after NS-01).
- Tools that spend money or tokens: none — all LLM calls go through the local Ollama instance.
- Test command: `cd app && python -m pytest -q tests`.
- Supported client apps and config paths: Claude Desktop — `%APPDATA%\Claude\claude_desktop_config.json` (Windows).
