# Deployment

Target: a single user on their own machine(s). Server + PostgreSQL in Docker, runner on each host that
has workspaces.

## 1. Server (Docker Compose)

```bash
./scripts/init-env.sh        # .env with random POSTGRES_PASSWORD and API/runner/agent tokens (never overwrites)
docker compose up -d --build
docker compose ps            # db healthy, server healthy
curl -s http://127.0.0.1:8765/api/health
```

- Web UI: `http://127.0.0.1:8765/` — sign in with `OHMYPM_API_TOKEN` (or `ohmypm open` for a login link).
- REST docs: `/api/docs`. MCP: `/mcp`.
- Data: Docker volume `ohmypm_pgdata`. Migrations run automatically at server start.
- Ports are bound to `127.0.0.1` (`OHMYPM_HOST_PORT`, `OHMYPM_DB_PORT` in `.env`). To reach the server from
  other machines (remote runners), put it behind a TLS reverse proxy and set `OHMYPM_PUBLIC_URL` to the
  public URL. Never publish PostgreSQL.
- Slow PyPI/npm? Set `PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn` and/or `NPM_REGISTRY=…` in `.env`
  before `docker compose build`.

`.env` keys: see [`.env.example`](../.env.example). Server settings (all `OHMYPM_*`, see
`backend/ohmypm/config.py`): `DATABASE_URL`, `API_TOKEN`, `RUNNER_TOKEN`, `AGENT_TOKEN`, `PUBLIC_URL`,
`LEASE_SECONDS` (45), `HEARTBEAT_INTERVAL_SECONDS` (5), `DEFAULT_RUN_TIMEOUT_SECONDS` (3600),
`MAX_RUN_TIMEOUT_SECONDS`, `AGENT_MAX_DISPATCH_DEPTH` (0), `AGENT_MAX_CHILD_RUNS` (3), `CORS_ORIGINS`,
`LOG_LEVEL`.

## 2. Host: CLI + runner

```bash
uv tool install ./cli                     # puts `ohmypm` on PATH (CLI + runner)
ohmypm config --init --set-token "$(grep ^OHMYPM_API_TOKEN .env | cut -d= -f2)"   # ~/.config/ohmypm/config.toml (0600)
export OHMYPM_RUNNER_TOKEN=$(grep ^OHMYPM_RUNNER_TOKEN .env | cut -d= -f2)
ohmypm runner init-config --allowed-root ~/workspace     # optional: ~/.config/ohmypm/runner.yaml
ohmypm runner start --allowed-root ~/workspace
```

The runner appears in the Web UI (Agent Runner page) with the agent CLIs it found.

Run it as a user service (systemd example):

```ini
# ~/.config/systemd/user/ohmypm-runner.service
[Unit]
Description=ohmypm agent runner
After=network-online.target

[Service]
Environment=OHMYPM_RUNNER_TOKEN=<runner token>
ExecStart=%h/.local/bin/ohmypm runner start
Restart=on-failure

[Install]
WantedBy=default.target
```

`systemctl --user daemon-reload && systemctl --user enable --now ohmypm-runner`. Note: a systemd unit has a
minimal `PATH`; set `agents.<type>.executable` or `Environment=PATH=…` so the agent CLIs are found, and make
sure their auth (e.g. `~/.claude`, `~/.codex`) belongs to the same user.

## 3. Use it

```bash
cd ~/workspace/my-project
ohmypm project init
ohmypm task create "…" -c "acceptance criterion"
ohmypm run dispatch T-1 --agent claude --follow
```

## Running the server without Docker

```bash
uv sync
export OHMYPM_DATABASE_URL=postgresql+psycopg://ohmypm:<pw>@127.0.0.1:55432/ohmypm OHMYPM_API_TOKEN=… OHMYPM_RUNNER_TOKEN=…
(cd frontend && pnpm install && pnpm build)
OHMYPM_WEB_DIST=frontend/dist uv run ohmypm-server serve --migrate
```

## Troubleshooting

| Problem | Fix |
|---|---|
| Web UI asks for a token again | The token is invalid (401 clears it); use `OHMYPM_API_TOKEN` from `.env` |
| `docker compose up`: POSTGRES_PASSWORD required | Run `./scripts/init-env.sh` first |
| Port 8765/55432 in use | Change `OHMYPM_HOST_PORT` / `OHMYPM_DB_PORT` in `.env` |
| Build fails fetching `docker/dockerfile` or images | Docker Hub unreachable: pre-pull `postgres:18-alpine`, `python:3.12-slim`, `node:22-alpine` via a mirror |
| `cannot reach http://127.0.0.1:8765` from the CLI | Server not running or different port; set `OHMYPM_URL` |
| Runner: `runner token missing` | Export `OHMYPM_RUNNER_TOKEN` or set `token:` in runner.yaml |
| Runner registers but runs stay queued | Workspace `host_id` ≠ runner `host_id` (both default to the hostname; set `OHMYPM_HOST_ID` consistently), or path outside `allowed_roots` |
| MCP client gets 401 | Missing `Authorization: Bearer …`, or a run token whose run already ended |
| Run `lost` after laptop sleep | Expected (lease expired); dispatch again — the context includes everything up to the last checkpoint |
| Server log: `OHMYPM_API_TOKEN is not set` | Every request will be rejected; set it in `.env` |
