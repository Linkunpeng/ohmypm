"""Alembic: full downgrade/upgrade cycle on a scratch database and no drift between models and migrations."""

from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config

import ohmypm.main


def _cfg(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(ohmypm.main.__file__).parent / "migrations"))
    cfg.attributes["configure_logger"] = False
    cfg.attributes["database_url"] = url
    return cfg


def test_migrations_roundtrip_and_no_drift(database_url: str) -> None:
    admin = database_url.replace("postgresql+psycopg://", "postgresql://").rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS ohmypm_migrations WITH (FORCE)")
        conn.execute("CREATE DATABASE ohmypm_migrations")
    url = database_url.rsplit("/", 1)[0] + "/ohmypm_migrations"
    cfg = _cfg(url)
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises if models and migrations differ
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as conn:
        tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    assert {"projects", "tasks", "agent_runs", "run_events", "checkpoints", "artifacts"} <= tables
