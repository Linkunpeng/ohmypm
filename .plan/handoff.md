# Handoff

## State (2026-10-29, end of session 1)
All five roadmap phases are implemented and tested (see `progress.md`). Nothing is committed yet: the
repository has no commits; the user has not asked for one.

## How to resume
```bash
uv sync && uv run pytest -q
cd frontend && pnpm install && pnpm test && pnpm build
```
Demo setup used during development (scratch DB on :55433, server :8765, runner with fake agent) is
described in `docs/development.md`.

## Suggested next steps (priority order)
1. Live-verify Codex/Pi/dsh adapters on a machine with network/credentials
   (`OHMYPM_SMOKE=1 OHMYPM_SMOKE_AGENTS=codex uv run pytest tests/test_smoke_real_cli.py -s`) and add
   real success transcripts to `tests/fixtures/agent_output/`.
2. Interactive approvals: relay Claude permission prompts via `--permission-prompt-tool` / stream-json
   input to a `waiting_approval` UI (currently fail closed).
3. Managed artifact storage (copy + sha256 + versions) behind the existing `storage_mode`.
4. MCP resources (`project://`, `task://`) and a stdio proxy (`ohmypm mcp stdio`) for clients without HTTP.
5. Task-level SSE (dashboard currently polls), route-level code splitting in the UI.
6. Multi-user roles (principal already carries role/name; tokens table instead of env tokens).

## Open questions for the user
- Should agents be allowed to dispatch sub-runs by default (`OHMYPM_AGENT_MAX_DISPATCH_DEPTH`, currently 0)?
- Preferred default Claude/Codex profiles (models, budgets, allowed tools) for unattended runs.
