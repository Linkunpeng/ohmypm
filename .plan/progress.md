# Progress

## 2026-10-29 — session 1 (all five phases)

### Done and verified
Automated (`uv run pytest -q` → 64 passed + 4 opt-in smoke skipped; ruff + mypy --strict clean;
frontend `tsc` strict, 6 vitest tests, oxlint clean except shadcn-generated files, `vite build` OK):
- Phase 1: uv workspace, models + Alembic `0001` (roundtrip + `alembic check` in a test), projects,
  workspaces (resolve/upsert, anonymous, PROJECT_ID linking), tasks (status machine, acceptance-gated
  completion, dependencies + cycle detection, ready queue, events), auth roles, idempotency (incl.
  concurrent), optimistic locking, FTS + trigram search (CJK).
- Phase 2: sessions, append-only checkpoints (DB trigger), ContextBuilder, decisions (blocking + resume),
  knowledge, artifacts, FastMCP `/mcp` (20 tools); agent A→B handoff test over HTTP.
- Phase 3: lease queue, runner service, adapters (claude/codex/pi/dsh/custom/fake), timeout, cancel,
  crash recovery (interrupted + orphan kill), lease expiry → lost, single writer per workspace,
  workspace allowlist (symlink escape), dangerous-option refusal, env scrubbing, redaction, SSE resume.
- Phase 4: Web UI (dashboard, projects, tasks, task view with tabs, agent runner, run view with live SSE log
  + cancel + hand-off, decisions, artifacts, knowledge, search, dark mode).
- Phase 5: CLI (project/task/context/checkpoint/run/agent/runner/decision/artifact/search/mcp/open),
  docs, examples, Dockerfile + compose, `.env` generator.

Manual verification (2026-10-29, this machine):
- Browser (agent-browser, headless Chrome): login via `#token=`, dashboard, task view, dispatch dialog →
  run view live log → Cancel (process group killed, exit -15) → hand-off buttons; decision resolve
  restores task status; artifact sheet; dark mode.
- `docker compose up -d --build` (with PYPI_MIRROR): db + server healthy, migrations at startup, Web UI
  served, REST + MCP (20 tools) reachable from the host.
- **Real Claude Code 2.1.303 run through the runner**: wrote the file under acceptEdits, Bash denied
  fail-closed (`approval.denied`), used injected MCP to checkpoint and complete with evidence.
  Cost $0.30 (6 turns).

### Not verified / known limits
- Codex, Pi, dsh live runs: blocked here by network (codex: OpenAI routing timeouts), local model OOM (pi),
  missing DEEPSEEK_API_KEY (dsh). Their parsers are tested on real transcripts of those failures plus
  synthetic success lines built from their documented/typed event schemas.
- Codex MCP injection uses `-c mcp_servers.ohmypm.url/bearer_token_env_var` (keys confirmed in the binary,
  not exercised live). Whether Codex auto-approves MCP tool calls under `approval_policy=never` is unverified.
- Interactive approval relay not implemented (fail closed by design). Managed artifact storage not
  implemented (reference mode only). MCP resources not exposed (tools only).

### Failed attempts / lessons
- `claude -p` without stdin data waits 3 s then warns → always pipe the prompt via stdin.
- Pi exits 0 on model errors → detect `stopReason: "error"`.
- Under `--permission-prompts none`, injected MCP tools are denied too → adapter adds `mcp__ohmypm`.
- `# syntax=docker/dockerfile:1` makes BuildKit pull from Docker Hub (unreachable here) → removed.
- `OHMYPM_PORT` collided between compose host-port var and the server's own setting → `OHMYPM_HOST_PORT`.
- Async SQLAlchemy: server-generated `updated_at` must be fetched eagerly (`eager_defaults=True`),
  otherwise serialising after flush triggers a lazy load (MissingGreenlet).
- Nested async fixtures calling `request.getfixturevalue` break pytest-asyncio → DB cleanup is a sync fixture.

### Environment notes
- PyPI is slow here: `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync`. `uv.lock` was
  rewritten to canonical pypi.org/files.pythonhosted.org URLs (same hashes; `uv lock --check` OK).
- Host has unrelated postgres on :5432; ohmypm compose uses :55432; dev scratch cluster :55433.

## 2026-10-30 — Multica agent core adaptation

- Compared Multica's agent configuration and runtime model with ohmypm's existing profiles and runner.
- Added reusable agent instructions, profile editing (including name), and dispatch-time instruction snapshots;
  updated Web creation/editing, CLI creation and runner documentation. Dispatch UI now respects profile
  write scheduling defaults. Migration `0002` adds the instructions column.
- Verified in an isolated PostgreSQL container: `pytest -q` 65 passed, 4 real-CLI smoke tests skipped;
  ruff and mypy passed; frontend typecheck, 6 tests, lint (three existing shadcn warnings), and build passed.
- First DB-backed attempt failed because inherited SOCKS proxy settings affected local HTTP and the health
  test expected revision 0001. Unsetting proxy variables and updating the assertion resolved the failures.
- Multica's agent chat/builder, per-user invocation permissions, skills/MCP configuration, runtime binding,
  and additional CLI adapters have not been ported. Actual CLI execution for the new instructions was not
  smoke-tested; the runner claim prompt and snapshot were integration-tested with a fake runtime.

## 2026-10-30 — Remote runner continuation

- Added explicit `continue_run_id` for Web, REST, MCP and CLI: continuation retains the source session,
  runner, workspace and profile snapshot, rejects stale/missing sessions, and serializes competing runs
  through a session row lock. The original runner must reconnect to claim a queued continuation.
- Resume prompts carry the new instruction instead of rebuilding full platform context. The runner rejects
  unsupported resume adapters and stops if a CLI reports a different native session ID. Run details expose
  provider-reported usage; Pi cache read/write fields are retained.
- Added a mobile navigation drawer, a scrollable dispatch dialog, and remote access documentation.
- Verified with isolated PostgreSQL: 68 passed, 4 opt-in real-CLI smoke tests skipped; targeted adapter tests
  15 passed; ruff, mypy, frontend typecheck, 7 tests, lint (3 existing shadcn warnings), and build passed.
  Tests include concurrent resume, runner pinning, compact prompts and changed native IDs using fake agents.
- Test development: restarting the same stopped RunnerService left the test run queued; constructing a new
  service with the same persistent runner ID fixed the test. Mobile component test needed a theme mock for
  jsdom's missing matchMedia; final test passes.
- Not verified: real CLI session resume, actual provider cache hit/latency, mobile browser over a real HTTPS
  endpoint. No native mobile app, interactive permission relay, or live in-turn message steering exists.
