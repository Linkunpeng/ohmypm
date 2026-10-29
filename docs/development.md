# Development

## Layout

```
ohmypm/
├── PROJECT_ID, AGENTS.md, CLAUDE.md, README.md, LICENSE
├── pyproject.toml / uv.lock      # uv workspace root (dev tools, pytest/ruff/mypy config)
├── common/ohmypm_common/         # shared: project_id, enums, protocol, agent_options, client, config, redact
├── backend/ohmypm/               # server
│   ├── main.py  config.py  db.py  models.py  schemas.py  errors.py
│   ├── api/                      # FastAPI routers (thin)
│   ├── mcp/server.py             # FastMCP tools (thin)
│   ├── services/                 # application services (business logic)
│   └── migrations/               # Alembic
├── runner/ohmypm_runner/         # service.py, process.py, workspace.py, discovery.py, fake_agent.py, adapters/
├── cli/ohmypm_cli/main.py        # Typer app
├── frontend/                     # Vite + React + TS + Tailwind v4 + shadcn/ui + TanStack Query
├── tests/                        # pytest; support/pgserver.py; fixtures/agent_output/
├── docs/  examples/  scripts/
├── Dockerfile  docker-compose.yml  .env.example
└── .plan/                        # agent handoff files
```

## Setup

```bash
uv sync                                    # Python 3.12+ venv with all four packages (editable) + dev tools
cd frontend && pnpm install                # Node ≥ 22, pnpm 12
```

If PyPI is slow in your network: `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync`
(the committed `uv.lock` points at pypi.org; don't commit mirror URLs).

## Dev loop

```bash
# database: throwaway cluster using local postgres binaries (or use `docker compose up -d db`)
uv run python -m tests.support.pgserver /tmp/ohmypm-devpg 55433 --fresh
export OHMYPM_DATABASE_URL=postgresql+psycopg://ohmypm@127.0.0.1:55433/ohmypm OHMYPM_API_TOKEN=dev OHMYPM_RUNNER_TOKEN=devrunner
uv run ohmypm-server serve --migrate                    # :8765
cd frontend && pnpm dev                                 # :5173, proxies /api and /mcp
OHMYPM_URL=http://127.0.0.1:8765 OHMYPM_RUNNER_TOKEN=devrunner uv run ohmypm runner start --allowed-root /tmp --enable-fake-agent
```

## Tests

```bash
uv run pytest -q                           # ~64 tests, ~10 s; starts an ephemeral PostgreSQL per session
OHMYPM_TEST_DATABASE_URL=postgresql+psycopg://… uv run pytest   # use an existing server instead
OHMYPM_SMOKE=1 OHMYPM_SMOKE_AGENTS=claude uv run pytest tests/test_smoke_real_cli.py -s   # real CLI, costs money
cd frontend && pnpm typecheck && pnpm test && pnpm lint && pnpm build
```

| File | Covers |
|---|---|
| `test_project_id.py` | PROJECT_ID discovery, anonymous workspaces, never-overwrite |
| `test_api_tasks.py` | Auth, projects, workspaces, task lifecycle, transitions, acceptance, dependencies/cycles/ready, optimistic locking, idempotency (incl. concurrent), search (CJK), pagination |
| `test_memory.py` | Checkpoints (append-only trigger), ContextBuilder modes/budget/determinism, decisions, knowledge, artifacts |
| `test_mcp.py` | MCP auth + Phase-2 handoff (agent A → agent B) over real HTTP |
| `test_adapters.py` | argv construction and parsing of real CLI transcripts, option whitelists, workspace allowlist, custom agent trust, redaction, env scrubbing |
| `test_runner_e2e.py` | Full E2E with the fake agent: dispatch → claim → execute → events → checkpoint → second agent completes; cancel, timeout, failure, unavailable CLI, symlink escape, dangerous options, single writer, crash recovery, lease expiry, idempotent dispatch, SSE resume |
| `test_cli.py` | CLI flows against a live server |
| `test_smoke_real_cli.py` | Opt-in real-CLI runs |

## Quality gates

```bash
uv run ruff check common backend runner cli tests
uv run ruff format --check common backend runner cli tests
uv run mypy common/ohmypm_common backend/ohmypm runner/ohmypm_runner cli/ohmypm_cli   # strict
cd backend && uv run alembic check
```

## Adding things

- **Schema change**: edit `models.py` → `alembic revision --autogenerate` → review → test upgrade/downgrade.
- **Endpoint**: service function in `services/` (raise `ohmypm.errors`), schema in `schemas.py`, thin
  router in `api/`, optional MCP tool in `mcp/server.py`, tests.
- **Agent adapter**: capture a real transcript into `tests/fixtures/agent_output/`, add options to
  `agent_options.py`, adapter in `runner/ohmypm_runner/adapters/`, register in `registry.py`, add it to
  `BUILTIN_AGENTS` in `services/profiles.py`, tests in `test_adapters.py`, docs in `runner.md`.
