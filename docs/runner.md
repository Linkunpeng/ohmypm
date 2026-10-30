# Agent Runner

The runner is a host-native service that executes agent CLIs for queued runs. It is part of the `ohmypm`
CLI:

```bash
ohmypm runner start --allowed-root ~/workspace [--max-parallel 2] [--name laptop] [--config runner.yaml]
ohmypm runner status            # runners known to the server
ohmypm agent doctor [PATH]      # local CLI availability + which instruction files each agent will read
```

It needs `OHMYPM_RUNNER_TOKEN` (env or `token:` in the config) and the server URL (`OHMYPM_URL`,
`--url` or `server_url:`; default `http://127.0.0.1:8765`).

## Configuration — `~/.config/ohmypm/runner.yaml`

`ohmypm runner init-config --allowed-root ~/workspace` writes a starter file (mode 600). Full example:
[`examples/runner.yaml`](../examples/runner.yaml).

| Key | Default | Meaning |
|---|---|---|
| `server_url` | `http://127.0.0.1:8765` | Backend URL (also used to build the MCP URL given to agents) |
| `token` | — | Runner token (prefer env `OHMYPM_RUNNER_TOKEN`) |
| `name`, `host_id` | hostname | Display name; host id must match the `host_id` of workspaces (CLI uses the same default) |
| `allowed_roots` | `[]` (= run nowhere) | Workspaces must resolve (`realpath`) inside one of these |
| `max_parallel` | 2 | Concurrent runs on this runner |
| `allow_dangerous` | false | Permit profiles requesting bypass/full-access modes or Pi `bash` |
| `enable_fake_agent` | false | Enable the deterministic `fake` agent (tests/demos) |
| `agents.<type>` | enabled | `{enabled, executable, max_parallel, env}` per built-in agent |
| `custom_agents_dir` | `~/.config/ohmypm/agents.d` | Custom CLI definitions |
| `trusted_custom_agents` | `[]` | Custom agent ids you explicitly authorize |
| `cancel_grace_seconds` | 10 | SIGTERM → SIGKILL grace period |

State (runner id, pid files for orphan cleanup) lives in `~/.local/state/ohmypm/`.

## Lifecycle

1. `register` (reports available agents via `--version` checks). The server marks runs that this runner
   id still had active as `interrupted`; the runner kills orphaned agent processes recorded in its pid files
   (only if the command line still matches, to avoid PID reuse accidents).
2. Loops: **claim** (every `poll_interval`, ~2 s) and **heartbeat** (every ~5 s; extends leases, delivers
   cancel requests). Leases expire after 45 s without heartbeat → server marks the run `lost`.
3. Per run: validate workspace → validate agent/profile → spawn → stream → finish. A run never completes
   its task; agents do that through `pm_complete_task` with evidence.
4. SIGINT/SIGTERM: stop claiming, terminate running agents, report them `interrupted`.

## Execution environment

- `cwd` = the workspace root; the CLI discovers its own config, skills, `CLAUDE.md`/`AGENTS.md` and MCP
  servers exactly as if you had opened it there (no `--bare`/`--safe-mode`, no config translation).
- Environment = the runner's environment (your `HOME`, `PATH`, CLI auth) **minus** `OHMYPM_RUNNER_TOKEN`,
  `OHMYPM_TOKEN`, `OHMYPM_API_TOKEN`, plus `OHMYPM_URL`, `OHMYPM_AGENT_TOKEN` (run-scoped),
  `OHMYPM_RUN_ID`, `OHMYPM_TASK_ID`, `OHMYPM_WORKSPACE` and `agents.<type>.env`.
- Prompt on stdin (never in argv): resume context from the ContextBuilder + run instructions + reporting
  protocol. Agents without MCP can still record progress with `ohmypm checkpoint add …`, which picks up
  the run token from the environment.
- One process group per run; timeout/cancel kill the whole group.

## Built-in adapters

Verified on 2026-10-29 against the installed versions' `--help` and real output (fixtures in
`tests/fixtures/agent_output/`).

| Agent | Command (prompt on stdin) | Defaults (fail closed) | Native resume | Verification status |
|---|---|---|---|---|
| `claude` (2.1.303) | `claude -p --output-format stream-json --verbose --permission-prompts none --permission-mode acceptEdits [--model …] [--allowed-tools …] [--mcp-config <0600 tmp file>]` | edits allowed, anything that would prompt is denied (`approval.denied` events) | `--resume <session_id>` | **live end-to-end run verified** (file written, MCP checkpoint + completion, Bash denied) |
| `codex` (0.164.0) | `codex exec [resume <id>] --json -c sandbox_mode="workspace-write" -c approval_policy="never" --skip-git-repo-check [-m …] [-c mcp_servers.ohmypm.url=… -c mcp_servers.ohmypm.bearer_token_env_var="OHMYPM_AGENT_TOKEN"] -` | workspace-write sandbox, never asks | `exec resume <thread_id>` | parser verified on a real transcript; live run blocked by network on dev machine |
| `pi` (0.85.1) | `pi -p --mode json --tools read,edit,write,grep,find,ls [--provider/--model/--thinking]` | no `bash` (Pi has no approval system) | `--session <id>` | parser verified on a real transcript (model error case); **exit code is 0 even on model errors** — detected from `stopReason: "error"` |
| `dsh` (0.2.0-rc.2) | `dsh --profile headless --json [--session-id <id>] -` + env `DSH_PERMISSION_MODE=workspace-write` | workspace-write | `--session-id` | parser verified on a real transcript (missing credential case) |

Unknown event types are kept as `agent.status`/`agent.output` rather than dropped.

## Agent profiles

Agents are created as profiles on the server (Web → Agent Runner → New agent,
`ohmypm agent profile-add`, or `POST /api/agent-profiles`). A profile has a name, description,
reusable instructions, execution defaults, and whitelisted options (`common/ohmypm_common/agent_options.py`).
Edit and delete profiles in the Agent Runner page or through the API. The chosen profile's options
and instructions are snapshotted when a run is queued, so later edits or deletion do not change it.
Run-specific instructions are provided separately and appear alongside the agent instructions.

| Agent | Options |
|---|---|
| claude | `model`, `fallback_model`, `permission_mode` (`default/acceptEdits/plan/dontAsk/auto/bypassPermissions`*), `allowed_tools`, `disallowed_tools`, `effort`, `max_budget_usd`, `append_system_prompt`, `inject_mcp` |
| codex | `model`, `sandbox` (`read-only/workspace-write/danger-full-access`*), `reasoning_effort`, `config_profile`, `skip_git_repo_check`, `network_access`*, `inject_mcp` |
| pi | `provider`, `model`, `thinking`, `tools` (`bash`*), `no_extensions`, `no_skills` |
| dsh | `profile`, `permission_mode` (`danger-full-access`*) |
| fake | `script`, `exit_code` |

\* dangerous: refused by the runner unless `allow_dangerous: true`. Unrestricted `Bash` in Claude's
`allowed_tools` is also dangerous; scoped rules such as `Bash(npm test:*)` are fine.

Examples ([`examples/profiles.md`](../examples/profiles.md)):

```bash
ohmypm agent profile-add claude-default --agent claude --default \
  --options '{"model": "sonnet", "allowed_tools": ["Bash(npm test:*)", "Bash(git diff:*)"], "max_budget_usd": 5}'
ohmypm agent profile-add codex-default --agent codex --default --options '{"sandbox": "workspace-write"}'
ohmypm agent profile-add claude-review --agent claude --read-only --options '{"permission_mode": "plan"}'
ohmypm agent profile-add reviewer --agent codex --read-only --options '{"sandbox":"read-only"}' \
  --instructions 'Review changes for correctness.'
```

Read-only profiles (`write_mode=false`) may run concurrently with a writer in the same workspace;
write runs are serialized per workspace. This flag controls queue scheduling, not filesystem permissions;
configure the CLI's own read-only sandbox or permissions separately.

## Continuing a native session

From a finished run, use **Continue with** in the Web UI and enter the next instruction. Alternatively,
run `ohmypm run dispatch T-1 --continue-run <run-id> -i 'next instruction'`, or pass
`continue_run_id` to `POST /api/runs` / MCP `pm_dispatch_task`. A continuation retains the original
workspace, runner, session and profile snapshot. Only one queued or active run may use a session at once.
If its original runner is offline, the continuation waits for that runner to reconnect.

The runner starts a new CLI process and requests native session resume; it does not keep a live interactive
process between turns. It sends the new instruction without rebuilding the full platform context. If no
native session was recorded, continuation is rejected. If an adapter reports a different session ID, the
runner stops the run and reports `resume_mismatch`. Native resume support and error reporting depend on
the CLI; custom adapters do not support it. A successful request is not proof of a provider cache hit.
The run detail shows provider usage when reported; availability and field names vary by agent.

## Custom CLIs

Define them on the runner host only (the server can select but never define commands):

```yaml
# ~/.config/ohmypm/agents.d/my-agent.yaml
id: my-agent
name: My Agent
executable: /usr/local/bin/my-agent        # absolute path
args: ["--non-interactive", "--cwd", "{workspace}"]   # placeholders: {workspace} {run_id} {task_id} {prompt} {prompt_file}
prompt_delivery: stdin                     # stdin | arg | file
output: {format: jsonl}                    # jsonl (ohmypm events) | text (each line = agent.output)
runtime: {timeout_seconds: 3600, max_parallel: 1}
env: {MY_AGENT_MODE: batch}
```

and authorize it in `runner.yaml`: `trusted_custom_agents: [my-agent]`. Then dispatch with
`--agent my-agent`. JSONL lines look like `{"type": "agent.message", "text": "…"}`,
`{"type": "tool.started", "tool": "…", "input": …}`, `{"type": "result", "text": "…", "is_error": false}`,
`{"type": "session", "id": "…"}`. See `runner/ohmypm_runner/fake_agent.py` for a complete example.

## Approvals

Interactive approval relays are not implemented yet. Unattended runs **fail closed**: whatever the CLI
would ask about is denied (Claude) or not permitted by the sandbox (Codex, dsh), and the denial is visible
in the run log. Grant capabilities explicitly through profile options (e.g. scoped `allowed_tools`).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Run stays `queued` | No online runner on the workspace's `host_id`, agent unavailable on it, workspace outside `allowed_roots` (server-side prefilter), or another write run active in the workspace. Check `ohmypm runner status` and `ohmypm agent doctor`. |
| `workspace_not_allowed` | The path resolves (after symlinks) outside `allowed_roots`, or doesn't exist on that host |
| `dangerous_options_denied` | Profile asks for elevated permissions; set `allow_dangerous: true` only if you accept that |
| `agent_unavailable` | CLI missing / `--version` failed; set `agents.<type>.executable` |
| Run `lost` | Runner stopped heartbeating for 45 s (crash, sleep, network) |
| Claude tool calls show `approval.denied` | Expected under the fail-closed default; allow the specific tool in the profile |
| Codex: "Reconnecting… workspace routing discovery timed out" | Network to OpenAI; shown as `agent.warning`, run fails if the turn fails |
| Pi run `failed` with exit code 0 | Model/provider error reported in the event stream (e.g. local model OOM) |
