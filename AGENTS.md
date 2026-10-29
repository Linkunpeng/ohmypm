# AGENTS.md — working on ohmypm

ohmypm is a local-first project memory + task manager + agent execution platform. This file tells
coding agents how to work in this repository. Keep it short; details live in `docs/`.

## Before you start
1. Read `.plan/handoff.md` (where the last session stopped) and `.plan/progress.md`.
2. Check `.plan/decisions.md` before changing architecture; append a new `D-xxx` entry for new decisions.
3. Run the test suite once to see the baseline.

## Architecture in one paragraph
uv workspace with four Python packages: `common/ohmypm_common` (PROJECT_ID discovery, enums, runner
protocol models, agent option whitelists, HTTP client, redaction), `backend/ohmypm` (FastAPI REST under
`/api`, FastMCP under `/mcp`, async SQLAlchemy services, Alembic migrations — the only package touching
PostgreSQL), `runner/ohmypm_runner` (host-native process supervisor + agent adapters; talks to the
backend only over HTTP), `cli/ohmypm_cli` (Typer `ohmypm` command). `frontend/` is React + Vite +
shadcn/ui, served by the backend in production. REST and MCP call the same functions in
`backend/ohmypm/services/` — never put business logic in `api/` or `mcp/`.

## Directory conventions
| Path | What goes there |
|---|---|
| `backend/ohmypm/models.py` | ORM models (all tables) |
| `backend/ohmypm/schemas.py` | Pydantic schemas shared by REST and MCP |
| `backend/ohmypm/services/` | Application services (one module per area) |
| `backend/ohmypm/api/`, `backend/ohmypm/mcp/` | Thin transports |
| `backend/ohmypm/migrations/versions/` | Alembic revisions (`NNNN_slug`) |
| `runner/ohmypm_runner/adapters/` | One module per agent CLI |
| `tests/` | pytest (unit, integration, E2E); `tests/fixtures/agent_output/` = real CLI transcripts |
| `frontend/src/{lib,components,pages}` | API client/types, shared UI, routes |

## Commands
```bash
uv sync                                    # Python deps (add UV_DEFAULT_INDEX=<mirror> if PyPI is slow)
uv run pytest -q                           # all backend/runner/CLI tests (spins up a throwaway PostgreSQL)
uv run ruff check . && uv run ruff format --check common backend runner cli tests
uv run mypy common/ohmypm_common backend/ohmypm runner/ohmypm_runner cli/ohmypm_cli
cd frontend && pnpm install && pnpm typecheck && pnpm test && pnpm lint && pnpm build

# migrations (needs OHMYPM_DATABASE_URL)
cd backend && uv run alembic revision --autogenerate -m "describe change"
cd backend && uv run alembic upgrade head && uv run alembic check

# dev servers
uv run python -m tests.support.pgserver /tmp/ohmypm-devpg 55433 --fresh   # throwaway DB (prints URL)
OHMYPM_DATABASE_URL=... OHMYPM_API_TOKEN=dev uv run ohmypm-server serve --migrate
cd frontend && pnpm dev                    # proxies /api and /mcp to :8765
```
Tests need either local `initdb`/`pg_ctl` binaries or `OHMYPM_TEST_DATABASE_URL`. Real-CLI smoke tests
are opt-in (`OHMYPM_SMOKE=1`) because they spend money.

## Code rules
- Python: type hints everywhere (`mypy --strict` clean), ruff clean, async services taking `Ctx`.
- Raise `ohmypm.errors.*` from services; transports map them to HTTP/MCP errors.
- Every task state change writes a `task_events` row in the same transaction.
- Checkpoints are append-only (DB trigger). Never add an update path.
- Runner: argv arrays only (never `shell=True`), options only through `ohmypm_common.agent_options`.
- Do not invent CLI flags — verify with the CLI's `--help` and add a transcript fixture for new parsers.
- TypeScript: strict + `noUncheckedIndexedAccess`; use shadcn components from `src/components/ui`.

## Recording progress (until ohmypm tracks itself)
- After a meaningful step: update `.plan/progress.md` (done/verified, failed attempts with results).
- Before ending a session: update `.plan/handoff.md` (state, next steps, open questions).
- Don't paste raw logs into these files or into this one.
