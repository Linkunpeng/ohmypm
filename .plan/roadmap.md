# Roadmap

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done and verified by tests

## Phase 1 — Backend foundation, Project/Task
- [x] uv workspace (common / backend / runner / cli), Docker Compose, PostgreSQL
- [x] SQLAlchemy models + Alembic initial migration
- [x] Project / Workspace / PROJECT_ID discovery / anonymous workspaces
- [x] Task CRUD, status machine, dependencies, ready tasks, task events
- [x] REST API with auth, pagination, error envelope, idempotency, optimistic locking
- Acceptance: DB starts, create Project + Task, query status (pytest against real PostgreSQL)

## Phase 2 — Memory + MCP
- [x] AgentSession, Checkpoint (append-only), Decision, ProjectKnowledge
- [x] ContextBuilder (brief/standard/full, token budget, deterministic)
- [x] FastMCP server mounted at `/mcp`, tools sharing the application services
- Acceptance: agent A checkpoints, agent B gets structured resume context (test)

## Phase 3 — Agent Runner
- [x] AgentRun / RunEvent / Runner models, lease + heartbeat queue in PostgreSQL
- [x] Runner service (`ohmypm runner start`), adapter protocol, process supervision
- [x] Claude + Codex adapters (verified against local `--help` + real output samples)
- [x] Timeout, cancel, lost/interrupted detection, workspace single-writer, path allowlist
- [x] Fake agent adapter for E2E tests
- Acceptance: dispatch via API → runner executes → events + result persisted (E2E test)

## Phase 4 — Web UI
- [x] Vite + React + TS strict + Tailwind + shadcn/ui + TanStack Query
- [x] Dashboard, Projects, Task view, Runner view (SSE log), Decisions, Artifacts, Search
- Acceptance: create task, dispatch agent, watch log, cancel from the browser

## Phase 5 — Artifacts + extensions
- [x] Artifact registry (reference mode), Pi / DSH / Custom adapters, search, CLI
- [x] Docs + deployment verification
- Acceptance: Web, MCP and CLI see consistent tasks/runs/artifacts

## Later
- Managed artifact storage, interactive approvals, remote runners over WAN, LLM summaries,
  semantic search, multi-user roles.

Status 2026-10-29: all phases implemented and covered by tests; see progress.md for verification
details and known limits (Codex/Pi/dsh not live-verified on the dev machine).
