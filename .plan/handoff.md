# Handoff

## State (2026-10-30)
Multica agent core configuration and remote runner continuation are adapted to ohmypm. Named profiles
have reusable instructions; continuing a run pins its native session, runner, workspace and profile
snapshot, serializes concurrent turns, sends incremental instructions and rejects reported session-ID
mismatches. Web supports phone navigation and continuation; CLI, REST and MCP accept `continue_run_id`.
See `progress.md`, D-010 and D-011. MCP task T-1 tracks the broader port.
Migration 0002 must be applied before using the updated server.

## Remaining work
- Live-verify native session resume for each CLI and measure cache read/write and latency over two real
  turns; project rules require explicit authorization for real CLI smoke tests. A resume request is not
  proof that a provider restored a session or hit cache.
- Test remote Web on a real phone through authenticated HTTPS. No native mobile app or live in-turn
  steering/interactive approval relay is implemented; approval prompts still fail closed.
- Assess remaining Multica features: agent chat/AI builder, skills and external MCP config, additional
  CLI adapters and multi-user invocation permissions. Preserve the runner trust boundary.
- Older priorities remain: managed artifact storage, MCP resources/stdio, task-level SSE, multi-user roles.

## Verification and environment
- Isolated Docker PostgreSQL: 68 passed, 4 real-CLI smoke tests skipped. Unset inherited HTTP(S)_PROXY
  and ALL_PROXY for local HTTP tests. Ruff, strict mypy, frontend typecheck/test/lint/build passed; lint
  reports three existing shadcn warnings.
- A continued run waits for its original runner; retain its state directory/runner ID. `write_mode` is a
  scheduling flag only; configure CLI sandbox/permissions for actual read-only enforcement.
