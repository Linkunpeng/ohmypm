# Architecture

## Components

| Component | Package | Runs where | Responsibility |
|---|---|---|---|
| Server | `backend/ohmypm` | Docker (or host) | REST `/api`, MCP `/mcp`, Web UI `/`, application services, PostgreSQL, lease reaper |
| Runner | `runner/ohmypm_runner` | Host with the workspaces | Claims runs, starts agent CLIs, streams events, enforces local security |
| CLI | `cli/ohmypm_cli` | Host | `ohmypm` command; `ohmypm runner start` hosts the runner |
| Common | `common/ohmypm_common` | Everywhere | PROJECT_ID discovery, enums, runner protocol, agent option whitelists, HTTP client, redaction |
| Web | `frontend/` | Browser (served by server) | React + TanStack Query + shadcn/ui |

A modular monolith: one server process, one database. The runner is separate because agent CLIs, their
credentials, skills and the workspaces live on the user's machine, which the server container cannot
(and should not) see.

```
             Web (React) ─┐            ┌──────────── ohmypm server ─────────────┐
             ohmypm CLI ──┼─ REST ───▶ │ api/ (FastAPI)   mcp/ (FastMCP)        │
 Agents (Claude, Codex…) ─┴─ MCP ────▶ │        └──── services/ ────┘           │──▶ PostgreSQL
                                       │ projects tasks memory decisions        │
                                       │ knowledge artifacts context runs search│
                                       └───────────────▲────────────────────────┘
                                         /api/runner/* │ (runner token, X-Runner-Id)
                               ┌───────────────────────┴───────────────┐
                               │ ohmypm runner (host)                   │
                               │  claim loop · heartbeat loop           │
                               │  RunExecutor → adapter → subprocess ───┼──▶ claude / codex / pi / dsh / custom
                               └────────────────────────────────────────┘        (cwd = workspace)
```

## Core concepts

- **Project** — identified by the UUID in a `PROJECT_ID` file; path- and name-independent.
- **Workspace** — `(host_id, root_path)`; belongs to zero or one project. Paths are only *resolved* on the
  runner of that host (`realpath` + allowlist); the server stores them as opaque strings.
- **Task** — the unit of work. Keeps the verbatim `raw_request` and current structured state; history goes
  to `task_events`.
- **AgentSession** — one agent's logical conversation on a task (may span several runs, may carry the CLI's
  native session id for `--resume`).
- **AgentRun** — one CLI process execution. Ending a run never completes the task.
- **Checkpoint** — append-only resumable state written by agents (or by the system when a run ends
  without one).
- **Decision** — a question for the user; blocking decisions move the task to `awaiting_user`.
- **ProjectKnowledge** — long-lived facts; can be superseded.
- **Artifact** — registered deliverable (reference mode) with version history.

## Request flow: running an agent

1. Web/CLI/MCP `POST /api/runs` → `services.runs.dispatch_run`: validates task state, dependencies,
   profile and workspace; creates/reuses an AgentSession; inserts `agent_runs(status=queued)` + events.
2. Runner `POST /api/runner/claim` (every ~2 s when it has capacity): `SELECT … FOR UPDATE SKIP LOCKED`
   on queued runs for its host and available agent types, skipping workspaces with an active writer and
   paths outside its allowed roots. Each claimed run gets a lease, a fresh **run token** (stored hashed)
   and a **prompt** built by the ContextBuilder.
3. Runner validates the workspace (`realpath` under `allowed_roots`), the agent's availability and the
   profile options (dangerous options need `allow_dangerous`), then spawns the CLI with an argv array in a
   new process group, prompt on stdin, `cwd` = workspace, user environment minus ohmypm secrets plus
   `OHMYPM_*` run variables.
4. stdout lines → adapter parser → normalized events (`agent.message`, `tool.started`, `file.changed`, …),
   redacted and uploaded in batches with client ids (idempotent). stderr → `agent.stderr`.
5. Heartbeats extend leases and deliver cancellation requests. Timeouts/cancels terminate the process
   group (SIGTERM → grace → SIGKILL).
6. `POST /api/runner/runs/{id}/finish` records status, exit code, final message, usage and native session
   id. If the agent wrote no checkpoint, the server writes an auto checkpoint so the next agent still
   gets a handoff.
7. Meanwhile, the agent can use MCP (`pm_checkpoint`, `pm_manage_decision`, `pm_complete_task`, …) with its
   run token; the server attributes those writes to `agent:run:<id>`.

## Failure handling

| Failure | Detection | Result |
|---|---|---|
| Runner crash / host reboot | lease not renewed | reaper marks run `lost` (+ auto checkpoint) |
| Runner restart | `POST /api/runner/register` with same runner id | previous active runs → `interrupted`; orphan processes from the pid files are killed |
| Agent hangs | run `timeout_seconds` | process group killed, run `failed/timeout` |
| User cancel | `cancel_requested_at` → heartbeat response | process group killed, run `cancelled` |
| Server unreachable | runner retries with backoff; events buffered, finish retried | |
| Duplicate requests | `Idempotency-Key` table / event client ids / idempotent finish | |
| Concurrent edits | `version` columns, `If-Match` / `expected_version` | 409 `version_conflict` |

## Trust boundaries & security

- Three bearer-token roles: **admin** (Web/CLI), **runner** (runner endpoints only), **agent**
  (run-scoped tokens valid only while the run is active, or an optional static agent token).
  Run-scoped agents can only modify their own task, its subtasks and tasks they created, cannot resolve
  decisions or force completion, and cannot dispatch runs unless `OHMYPM_AGENT_MAX_DISPATCH_DEPTH > 0`.
- The server never sends executables or raw argv: profiles carry typed options validated against per-agent
  whitelists (`ohmypm_common.agent_options`) on both sides. Custom CLIs exist only in the runner host's
  config and must be listed in `trusted_custom_agents`.
- Workspace allowlist on the runner; symlink escapes are rejected via `realpath`.
- Fail-closed approvals: Claude runs with `--permission-prompts none` (prompting tools are denied, recorded
  as `approval.denied`), Codex with `approval_policy="never"` + `workspace-write` sandbox, Pi without `bash`
  by default, dsh with `DSH_PERMISSION_MODE=workspace-write`. Elevated modes need `allow_dangerous: true`.
- Secrets: the runner strips its own tokens from the child environment and redacts known token patterns
  and literal secrets from events before upload; the server redacts again. CLI auth tokens are never
  stored by ohmypm. Errors returned to clients never include stack traces.
- PostgreSQL and the server are published on `127.0.0.1` only by default.

## Design decisions

The decision log is in [`.plan/decisions.md`](../.plan/decisions.md) (D-001 … ). Highlights: uv workspace
split by deployment boundary; async SQLAlchemy + psycopg 3; PostgreSQL lease queue (no Redis/Celery);
SSE via DB polling with `Last-Event-ID`; FTS `simple` config + trigram ILIKE for CJK; backend serves
the built UI.

## Extension points

- New agent CLI: add an adapter in `runner/ohmypm_runner/adapters/`, its option model in
  `common/ohmypm_common/agent_options.py`, and a transcript fixture + tests.
- New client: everything is in the REST API (`/api/openapi.json`); runners use `/api/runner/*`.
- Remote runners: already supported over HTTP; put the server behind TLS and set `OHMYPM_PUBLIC_URL`.
- Semantic search / LLM summaries: plug into `services/search.py` / `services/context.py`; the
  ContextBuilder is deliberately deterministic today.
