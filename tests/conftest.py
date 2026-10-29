"""Shared fixtures: a real PostgreSQL (ephemeral cluster or OHMYPM_TEST_DATABASE_URL), migrated once.

Every test starts from empty tables. ``client`` talks to the app in-process; ``live_server``
runs uvicorn on a free port for tests that need real HTTP (MCP, runner subprocesses).
"""

from __future__ import annotations

import asyncio
import os
import socket
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import uvicorn
from pydantic import SecretStr

from ohmypm.config import Settings
from ohmypm.db import Database
from ohmypm.main import create_app, migrate
from tests.support.pgserver import EphemeralPostgres, binaries_available

ADMIN_TOKEN = "test-admin-token-0123456789"
RUNNER_TOKEN = "test-runner-token-0123456789"
AGENT_TOKEN = "test-agent-token-0123456789"

TABLES = [
    "run_events",
    "agent_runs",
    "checkpoints",
    "agent_sessions",
    "artifact_versions",
    "artifacts",
    "decisions",
    "project_knowledge",
    "task_dependencies",
    "task_events",
    "tasks",
    "workspaces",
    "projects",
    "agent_profiles",
    "runners",
    "idempotency_keys",
]


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    external = os.environ.get("OHMYPM_TEST_DATABASE_URL")
    if external:
        migrate(external)
        yield external
        return
    if not binaries_available():
        pytest.skip("no PostgreSQL available: install initdb/pg_ctl or set OHMYPM_TEST_DATABASE_URL")
    base = Path(tempfile.mkdtemp(prefix="ohmypm-pg-"))
    pg = EphemeralPostgres(base)
    pg.start()
    try:
        url = pg.create_database("ohmypm_test")
        migrate(url)
        yield url
    finally:
        pg.stop()


def make_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": database_url,
        "api_token": SecretStr(ADMIN_TOKEN),
        "runner_token": SecretStr(RUNNER_TOKEN),
        "agent_token": SecretStr(AGENT_TOKEN),
        "lease_seconds": 30.0,
        "heartbeat_interval_seconds": 0.5,
        "poll_interval_seconds": 0.2,
        "reaper_interval_seconds": 3600.0,
        "sse_poll_interval_seconds": 0.05,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return make_settings(database_url)


@pytest_asyncio.fixture(scope="session")
async def db(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings.database_url)
    yield database
    await database.dispose()


@pytest.fixture(autouse=True)
def clean_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    """Empty all tables before each DB-backed test (sync connection: works for any test type)."""
    if "database_url" in request.fixturenames:
        import psycopg

        url = request.getfixturevalue("database_url").replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
    yield


@pytest_asyncio.fixture
async def app(settings: Settings, db: Database) -> AsyncIterator[Any]:
    application = create_app(settings, db)
    yield application


@dataclass
class Clients:
    admin: httpx.AsyncClient
    runner: httpx.AsyncClient
    agent: httpx.AsyncClient
    anon: httpx.AsyncClient

    def with_token(self, token: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.admin._transport, base_url="http://test", headers={"Authorization": f"Bearer {token}"}
        )


@pytest_asyncio.fixture
async def clients(app: Any) -> AsyncIterator[Clients]:
    transport = httpx.ASGITransport(app=app)

    def make(token: str | None) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers)

    c = Clients(make(ADMIN_TOKEN), make(RUNNER_TOKEN), make(AGENT_TOKEN), make(None))
    yield c
    for client in (c.admin, c.runner, c.agent, c.anon):
        await client.aclose()


@pytest.fixture
def client(clients: Clients) -> httpx.AsyncClient:
    return clients.admin


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class LiveServer:
    url: str
    settings: Settings


@pytest.fixture(scope="session")
def live_server(database_url: str) -> Iterator[LiveServer]:
    """uvicorn in a background thread with its own event loop and DB pool."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    settings = make_settings(database_url, public_url=url)
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("live server did not start")
        time.sleep(0.05)
    yield LiveServer(url=url, settings=settings)
    server.should_exit = True
    thread.join(timeout=10)


# ---------------------------------------------------------------- helpers


async def create_project(client: httpx.AsyncClient, name: str = "Robot", **extra: Any) -> dict[str, Any]:
    r = await client.post("/api/projects", json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def create_workspace(
    client: httpx.AsyncClient, path: str = "/home/u/robot", project_id: str | None = None, host_id: str = "test-host"
) -> dict[str, Any]:
    r = await client.post(
        "/api/workspaces/resolve", json={"host_id": host_id, "root_path": path, "project_id": project_id}
    )
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def create_task(client: httpx.AsyncClient, raw: str = "Implement the thing", **extra: Any) -> dict[str, Any]:
    r = await client.post("/api/tasks", json={"raw_request": raw, **extra})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]
