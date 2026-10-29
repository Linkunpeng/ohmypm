# MCP server

ohmypm exposes a [FastMCP](https://gofastmcp.com) server over **streamable HTTP** at
`<OHMYPM_PUBLIC_URL>/mcp` (default `http://127.0.0.1:8765/mcp`). Tools call the same application services
as the REST API, so behaviour, validation and permissions are identical.

## Authentication

Bearer token in the `Authorization` header:
- **Runs started by the ohmypm runner** receive a run-scoped token automatically (env
  `OHMYPM_AGENT_TOKEN`) and, for Claude Code and Codex, the MCP server configuration is injected for that
  run (`inject_mcp: true` in the profile, default). Claude additionally gets `mcp__ohmypm` pre-approved so
  the tools are not auto-denied under `--permission-prompts none`.
- **Agents you start yourself**: use `OHMYPM_AGENT_TOKEN` from `.env` (role *agent*), or the admin token if
  the agent should be able to resolve decisions.

The runner token is rejected by the MCP endpoint.

## Client configuration

`ohmypm mcp config <claude|codex|json>` prints these for your server URL.

Claude Code:
```bash
claude mcp add --transport http ohmypm http://127.0.0.1:8765/mcp --header "Authorization: Bearer ${OHMYPM_AGENT_TOKEN}"
```

Codex (`~/.codex/config.toml`):
```toml
[mcp_servers.ohmypm]
url = "http://127.0.0.1:8765/mcp"
bearer_token_env_var = "OHMYPM_AGENT_TOKEN"
```

Generic `mcpServers` JSON (e.g. `.mcp.json`):
```json
{"mcpServers": {"ohmypm": {"type": "http", "url": "http://127.0.0.1:8765/mcp",
  "headers": {"Authorization": "Bearer ${OHMYPM_AGENT_TOKEN}"}}}}
```

## Tools

| Tool | Purpose |
|---|---|
| `pm_bootstrap(cwd?, project_id?, host_id?)` | Start here: identity, current run's task + brief context, project, open/ready tasks |
| `pm_list_projects(query?)`, `pm_get_project(project_id)` | Projects with stats and workspaces |
| `pm_list_tasks(project_id?, status?, query?, ready_only?, anonymous_only?)` | Task list |
| `pm_get_task(task)` | Task by UUID or `T-12` |
| `pm_create_task(raw_request, title?, description?, acceptance_criteria?, priority?, project_id?, workspace_id?, parent_task_id?, depends_on?, idempotency_key?)` | Create a task (keep `raw_request` verbatim) |
| `pm_update_task(task_id, status?, description?, …, note?, expected_version?)` | Update task fields/status |
| `pm_complete_task(task_id, summary, results[{criterion, passed, evidence}], verification_command?)` | Complete with acceptance evidence |
| `pm_checkpoint(task_id, summary, completed?, remaining?, current_issue?, attempts?, findings?, relevant_files?, next_steps?, verification?, idempotency_key?)` | Save resumable progress |
| `pm_get_context(task_id, mode=brief|standard|full, max_tokens=3000)` | Resume context |
| `pm_manage_decision(action=create|list|get|resolve|cancel, …)` | Ask the user; agents may create/list/get, only admins resolve/cancel |
| `pm_knowledge(action=search|add|update|supersede, …)` | Project knowledge |
| `pm_register_artifact(name, storage_uri, type?, task_id?, description?, usage?, build?, verification?, environment?, sha256?, version_label?, idempotency_key?)` | Register a deliverable |
| `pm_list_artifacts(project_id?, task_id?, query?, type?)` | Artifacts |
| `pm_search(query, kinds?)` | Cross-entity search |
| `pm_list_runs(task_id?, active_only?)`, `pm_get_run(run_id, include_events?, after_seq?)` | Runs and their event logs |
| `pm_dispatch_task(task_id, agent_type?, profile_name?, instructions?, workspace_id?)` | Queue a run (agents: only within `OHMYPM_AGENT_MAX_DISPATCH_DEPTH`, max `agent_max_child_runs` children) |
| `pm_cancel_run(run_id, reason?)` | Cancel (agents: own run or runs they dispatched) |
| `pm_resume_task(task_id, agent_type?, instructions?)` | New run from the latest checkpoint |

Domain errors surface as tool errors like `[acceptance_not_met] acceptance criteria not satisfied details={…}`.

## Recommended agent workflow

1. `pm_bootstrap` (pass `cwd`, and the content of `PROJECT_ID` if you found one).
2. `pm_get_context` for the task you work on.
3. Work. After meaningful progress and before stopping: `pm_checkpoint` — what is done, what remains,
   failed attempts with results, findings labelled `verified` / `inferred` / `hypothesis`, relevant files,
   next steps, verification commands.
4. High-impact choice? `pm_manage_decision(action="create", blocking=true, …)` and stop.
5. Deliverables → `pm_register_artifact`. Done and verified → `pm_complete_task` with evidence.

Resources are not exposed yet; everything is available through tools (MCP clients support tools most
consistently).
