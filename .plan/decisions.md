# Decision log (append-only)

## D-001 Monorepo as a uv workspace with four Python packages
- `common/` (`ohmypm_common`): PROJECT_ID discovery, enums, runner↔server protocol models, HTTP client.
- `backend/` (`ohmypm`): FastAPI + FastMCP + SQLAlchemy + Alembic. Only package touching the DB.
- `runner/` (`ohmypm_runner`): host-native process supervisor; talks to backend over HTTP only.
- `cli/` (`ohmypm_cli`): `ohmypm` command (Typer); includes `ohmypm runner start`.
Why: runner/CLI install on the host without DB drivers; import boundaries enforce "API only".

## D-002 Async SQLAlchemy 2 + psycopg 3
One driver for app (async) and Alembic (sync). Services are async functions taking an `AsyncSession`.

## D-003 Queue = `agent_runs` table with leases
Runner polls `POST /api/runner/claim`; claim uses `FOR UPDATE SKIP LOCKED`. Lease extended by
heartbeat; expired leases → `lost` (reaper in backend lifespan + on every claim).
Single-writer per workspace enforced by a partial unique index over active write runs.

## D-004 Auth: three bearer-token roles
- `admin`: `OHMYPM_API_TOKEN` (Web, CLI).
- `runner`: `OHMYPM_RUNNER_TOKEN` (runner endpoints only).
- `agent`: per-run tokens minted at claim time (stored hashed, valid while run is active, scoped to
  the run's task, cannot dispatch runs beyond a depth limit); plus optional static `OHMYPM_AGENT_TOKEN`.
Single-user local deployment; roles leave room for multi-user later.

## D-005 Runner trust boundary
The server never sends executables or raw argv. Agent profiles carry only whitelisted, typed
options validated by each adapter. Custom CLIs are defined only in the runner host's local config
(explicit host-user authorization). Workspace paths are resolved with `realpath` on the runner and
must sit under `allowed_roots` from the runner config. Dangerous modes (bypass permissions, full
sandbox access) require `allow_dangerous: true` in the runner config.

## D-006 Unattended approval policy = fail closed
Claude: `--permission-prompts none` (prompts are auto-denied) with `acceptEdits` default.
Codex: `--sandbox workspace-write` default; no bypass flags unless dangerous mode is allowed.

## D-007 Search = PostgreSQL FTS (`simple` config) + `pg_trgm` ILIKE fallback
`simple` keeps behaviour language-neutral; trigram ILIKE handles CJK text that FTS cannot tokenize.

## D-008 SSE via DB polling with `Last-Event-ID`
Run events carry a per-run monotonic `seq`. The SSE endpoint replays `seq > last` and polls.
Robust across processes, no LISTEN/NOTIFY dependency. Frontend uses fetch-streaming (headers for auth).

## D-009 Backend serves the built Web UI
Single container (multi-stage build) serves `/api`, `/mcp`, and the SPA. Vite dev server proxies in dev.

## D-010 Reusable agents extend existing profiles
Model a named agent's description, instructions and execution defaults as an agent profile, retaining
the existing runner trust boundary and whitelisted options. Snapshot the instructions with the options
at dispatch so profile edits or deletion cannot change queued or historical runs. Run instructions
remain separate. Multica's multi-user access and runtime models are not implicitly mapped to the
single-user deployment.

## D-011 Explicit native session continuation
Continue from a specific run by preserving its session, runner, workspace and profile snapshot. Serialize
queued and active runs per reused session using a session row lock. Fail explicitly when no native session
exists or an adapter reports a different one; do not silently start over. Resume turns send incremental
instructions rather than rebuilding the full platform context. Cross-agent handoff remains a new session
using checkpoint context. Runner IDs must persist across restarts for queued continuations to resume.
