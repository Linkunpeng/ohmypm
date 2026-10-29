# Database

PostgreSQL ≥ 16 (tested with 18). Schema managed by Alembic (`backend/ohmypm/migrations`); the ORM
models in `backend/ohmypm/models.py` are the source of truth and `alembic check` must report no drift.

## Conventions

- UUID primary keys for entities; `bigint identity` for append-only event tables and `tasks.number`
  (human key `T-<number>`).
- Enumerations are `text` + `CHECK` constraints (values in `ohmypm_common.enums`).
- Every entity has `created_at`, most have `updated_at`, `created_by` (actor string such as `admin`,
  `runner`, `agent:run:<uuid>`, `system`), `metadata JSONB` and, where useful, `schema_version`.
- Optimistic locking: `version` column (SQLAlchemy `version_id_col`) on projects, tasks, decisions,
  knowledge, artifacts, agent profiles.
- Search: generated `search_vector tsvector` columns (`to_tsvector('simple', …)`) with GIN indexes, plus
  `pg_trgm` GIN indexes for substring/CJK matching.

## Tables

| Table | Purpose | Notes |
|---|---|---|
| `projects` | Projects (id = PROJECT_ID) | `archived` instead of delete |
| `workspaces` | `(host_id, root_path)` → optional project | unique `(host_id, root_path)`; `last_seen_at`; project link history in metadata |
| `tasks` | Current task state | `raw_request` never updated; `acceptance_result` set on completion |
| `task_dependencies` | `task_id` depends on `depends_on_id` | PK pair, no self-edges; cycles prevented in the service (recursive CTE under an advisory lock) |
| `task_events` | Task history | written in the same transaction as each change |
| `agent_profiles` | Named, validated agent options | ≤ 1 default per agent type (partial unique index) |
| `agent_sessions` | Agent conversations per task | `native_session_id` for CLI resume |
| `runners` | Registered runners | capabilities (`agents`), `allowed_roots`, `last_heartbeat_at` |
| `agent_runs` | Run queue + execution record | lease fields, `cancel_requested_at`, `agent_token_hash`, `event_seq`; partial unique index = one active **write** run per workspace |
| `run_events` | Normalized run events | unique `(run_id, seq)`; unique `(run_id, client_id)` for idempotent uploads |
| `checkpoints` | Resumable state | **append-only**: `BEFORE UPDATE` trigger raises |
| `decisions` | Questions for the user | `blocking` → task `awaiting_user` |
| `project_knowledge` | Long-lived knowledge | `superseded_by`, `tags text[]` |
| `artifacts` / `artifact_versions` | Artifact registry | version row appended when location/hash/version changes |
| `idempotency_keys` | Stored responses for `Idempotency-Key` | PK `(scope, key)`; scope = actor + operation |

## Invariants worth knowing

- **Event ordering**: run event sequence numbers are allocated with
  `UPDATE agent_runs SET event_seq = event_seq + n … RETURNING`, which row-locks the run until commit, so
  commit order equals `seq` order and SSE readers polling `seq > last` never miss an event.
- **Leases**: active runs (`starting|running|waiting_approval`) have `lease_expires_at`; the reaper (every
  15 s and on each claim) marks expired ones `lost`.
- **Run tokens** are only accepted while their run is active.

## Migrations

```bash
cd backend
export OHMYPM_DATABASE_URL=postgresql+psycopg://ohmypm:<pw>@127.0.0.1:55432/ohmypm
uv run alembic upgrade head                       # or: ohmypm-server migrate
uv run alembic revision --autogenerate -m "add x" # review the generated file!
uv run alembic check                              # models vs. migrations
uv run alembic downgrade -1
```

The server image runs `ohmypm-server serve --migrate`, applying migrations at startup.

## Backup

```bash
docker compose exec db pg_dump -U ohmypm ohmypm > ohmypm-$(date +%F).sql
```
