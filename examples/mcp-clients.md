# MCP client configuration examples

Replace the URL if your server is elsewhere; `OHMYPM_AGENT_TOKEN` comes from `.env`.

**Claude Code** (user scope):
```bash
claude mcp add --transport http ohmypm http://127.0.0.1:8765/mcp --header "Authorization: Bearer ${OHMYPM_AGENT_TOKEN}"
```

**Codex** (`~/.codex/config.toml`):
```toml
[mcp_servers.ohmypm]
url = "http://127.0.0.1:8765/mcp"
bearer_token_env_var = "OHMYPM_AGENT_TOKEN"
```

**Project `.mcp.json`** (Claude Code and other clients that read `mcpServers`):
```json
{
  "mcpServers": {
    "ohmypm": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp",
      "headers": { "Authorization": "Bearer ${OHMYPM_AGENT_TOKEN}" }
    }
  }
}
```

Suggested instruction for your `AGENTS.md` / `CLAUDE.md`:

> This project is tracked by ohmypm. At the start of a session call `pm_bootstrap` with your working
> directory and the content of `PROJECT_ID`. Save progress with `pm_checkpoint` before stopping, ask the
> user through `pm_manage_decision` for high-impact choices, and only call `pm_complete_task` with
> evidence for every acceptance criterion.
