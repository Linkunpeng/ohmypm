# Architecture (as built) — short version

Full description: `docs/architecture.md`. Decisions: `decisions.md`.

- **common/** `ohmypm_common`: PROJECT_ID discovery, enums, runner protocol (pydantic), agent option
  whitelists (`agent_options.py`, validated on server *and* runner), sync/async HTTP client, client config,
  redaction.
- **backend/** `ohmypm`: `models.py` (16 tables), `schemas.py`, `services/*` (all business logic, async,
  take `Ctx(session, principal, settings)`), `api/*` (FastAPI, `Depends(..., scope="function")` so commits
  happen before the response), `mcp/server.py` (FastMCP 4 with a custom `TokenVerifier`; 20 tools),
  `main.py` (app factory; mounts MCP at `/mcp` with a path fix; serves `OHMYPM_WEB_DIST`; lease reaper task).
- **runner/** `ohmypm_runner`: `service.py` (RunnerService loops + RunExecutor), `process.py` (argv spawn,
  process groups), `workspace.py` (realpath allowlist), `adapters/` (claude, codex, pi, dsh, custom, fake),
  `fake_agent.py`, `discovery.py`.
- **cli/** `ohmypm_cli/main.py`: Typer; `ohmypm runner start` hosts the runner.
- **frontend/**: Vite 8, React 19, TS 7 strict, Tailwind 4, shadcn/ui (radix-nova), TanStack Query 5,
  react-router 8. `lib/api.ts` client, `lib/sse.ts` fetch-SSE, pages under `src/pages`.

Data flow for a run: dispatch (queued) → claim (lease + run token + prompt from ContextBuilder) →
runner spawns CLI (stdin prompt, cwd=workspace) → events batched with client ids → heartbeat/cancel →
finish (+ auto checkpoint if the agent wrote none).
