# ohmypm — Oh My Project Manager

**Project memory + task management + agent execution + artifact registry**, local-first and built for
AI coding agents.

ohmypm keeps the durable state of your work — the original request, structured task state, append-only
checkpoints (what was done, what failed, what is next), user decisions, project knowledge and produced
artifacts — in PostgreSQL, and lets different agent CLIs (Claude Code, Codex, Pi, DeepSeek Harness, or
your own) pick up the same task across sessions without re-reading the whole project.

```
Web UI ─┐                     ┌─ PostgreSQL (authoritative state, FTS search, run queue with leases)
CLI ────┼─ REST /api ─┐       │
Agents ─┴─ MCP  /mcp ─┴─ ohmypm server ─┘
                               ▲  runner protocol (bearer token, leases + heartbeats)
                               │
                     ohmypm runner (on your machine) ── claude / codex / pi / dsh / custom CLI ── workspace
```

It does not reimplement an agent loop: it starts the real CLIs non-interactively in the right workspace
(with their native config, skills and MCP servers), streams their output as normalized events, and gives
them ohmypm's MCP tools to record progress.

## Features

- **Projects & workspaces** — a `PROJECT_ID` file (UUIDv4) identifies a project independent of its path;
  one project can have many workspaces on many hosts. Directories without one are anonymous workspaces.
- **Tasks** — verbatim `raw_request` kept forever, structured description, status machine, priorities,
  dependencies + ready queue, full event history, optimistic locking, idempotent creation.
  Completion requires acceptance evidence; a CLI exiting 0 never completes a task.
- **Agent memory** — sessions, append-only checkpoints (attempts, verified facts vs. hypotheses, next
  steps, verification commands) and a deterministic, token-budgeted **ContextBuilder** (`brief`/`standard`/`full`).
- **Decisions** — agents ask, users answer (Web/CLI); blocking decisions pause the task and resolving can
  resume it with the same agent.
- **Knowledge & artifacts** — long-lived project knowledge with supersession; artifact registry with usage,
  build, verification and version history.
- **Agent Runner** — host-native service; PostgreSQL lease queue; process-group supervision with timeouts,
  cancellation, crash recovery, single-writer-per-workspace; workspace path allowlist; fail-closed
  permission defaults; secret redaction; live SSE log with replay.
- **MCP server** (FastMCP, streamable HTTP) with 20 `pm_*` tools sharing the same services as REST.
- **Web UI** (React + shadcn/ui): dashboard, projects, tasks, agent runner, live run logs, decisions,
  artifacts, knowledge, search; dark/light.
- **CLI** `ohmypm`: projects, tasks, context, checkpoints, runs (with live follow), runner, MCP config.

## Quick start

Requirements: Docker + Docker Compose, Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/) on the host
(for the CLI and runner), and whichever agent CLIs you want to use.

```bash
git clone <this repo> ohmypm && cd ohmypm
./scripts/init-env.sh            # writes .env with random DB password and tokens (prints the admin token)
docker compose up -d             # PostgreSQL + server (REST, MCP, Web UI) on http://127.0.0.1:8765

# Host side: install the CLI (includes the runner)
uv tool install ./cli           # installs `ohmypm` (CLI + runner); or: uv sync && source .venv/bin/activate
export OHMYPM_TOKEN=$(grep ^OHMYPM_API_TOKEN .env | cut -d= -f2)
export OHMYPM_RUNNER_TOKEN=$(grep ^OHMYPM_RUNNER_TOKEN .env | cut -d= -f2)
ohmypm status

# Start a runner; agents may only run in workspaces below the allowed roots
ohmypm runner start --allowed-root ~/workspace

# In a project directory
cd ~/workspace/my-project
ohmypm project init                      # creates PROJECT_ID (never overwrites) and registers it
ohmypm task create "Add a --verbose flag to the CLI" -c "tests pass" -c "README documents the flag"
ohmypm run dispatch T-1 --agent claude --follow
ohmypm context T-1                       # what the next agent will see
ohmypm open                              # Web UI URL with a one-time login token
```

See [docs/deployment.md](docs/deployment.md) for details, mirrors, and troubleshooting.

## Using ohmypm from an agent you start yourself

```bash
ohmypm mcp config claude    # prints: claude mcp add --transport http ohmypm http://127.0.0.1:8765/mcp --header ...
ohmypm mcp config codex     # prints a [mcp_servers.ohmypm] block for ~/.codex/config.toml
```

Use `OHMYPM_AGENT_TOKEN` from `.env` as the bearer token. Agents launched *by* the runner get a
per-run token and the MCP server automatically. Details: [docs/mcp.md](docs/mcp.md).

## Documentation

| Doc | Content |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Components, data flow, trust boundaries, design decisions |
| [docs/database.md](docs/database.md) | Tables, invariants, migrations |
| [docs/api.md](docs/api.md) | REST conventions and endpoints |
| [docs/mcp.md](docs/mcp.md) | MCP tools and client configuration |
| [docs/runner.md](docs/runner.md) | Runner, adapters, profiles, custom CLIs, security |
| [docs/deployment.md](docs/deployment.md) | Docker Compose, host setup, troubleshooting |
| [docs/development.md](docs/development.md) | Repo layout, dev loop, tests |

## Status

`0.1.0` — single-user, local deployment. All phases of the initial plan are implemented and covered by
tests (see [.plan/progress.md](.plan/progress.md)). Verified against real Claude Code 2.1.303; Codex,
Pi and dsh adapters are verified against their real `--help` and captured output, but full live runs could
not be completed on the development machine (network/credentials) — see [docs/runner.md](docs/runner.md).

## License

Apache-2.0 — see [LICENSE](LICENSE).
