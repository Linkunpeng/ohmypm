"""SQLite engine, connection pragmas, sessions and schema migrations.

Concurrency model: every connection runs in WAL mode with a generous busy
timeout. Read sessions use deferred transactions (never blocked by writers in
WAL mode); write sessions open with ``BEGIN IMMEDIATE`` so the write lock is
taken up-front. That serialises writers across processes and makes
read-modify-write sequences (such as allocating entry sequence numbers) safe.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ohmypm.config import Settings, ensure_private_dir

# Keep in sync with the newest file in storage/migrations/versions.
# tests/test_migrations.py asserts that this matches Alembic's head.
SCHEMA_HEAD = "0001_initial"

BUSY_TIMEOUT_MS = 15_000
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _install_sqlite_hooks(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: sqlite3.Connection, _record: Any) -> None:
        # Let SQLAlchemy events control BEGIN instead of the sqlite3 module.
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Any) -> None:
        mode = conn.get_execution_options().get("sqlite_begin", "DEFERRED")
        conn.exec_driver_sql(f"BEGIN {mode}")


def create_sqlite_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": BUSY_TIMEOUT_MS / 1000, "check_same_thread": False},
    )
    _install_sqlite_hooks(engine)
    return engine


def _secure_file(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        with contextlib.suppress(OSError):
            if candidate.exists() and candidate.stat().st_mode & 0o077:
                candidate.chmod(0o600)


def _current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        has_table = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'")
        ).first()
        if not has_table:
            return None
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        return row[0] if row else None


def alembic_config(db_path: Path) -> Any:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def run_migrations(engine: Engine, db_path: Path) -> None:
    """Upgrade the schema to head. Cheap no-op when already current."""
    if _current_revision(engine) == SCHEMA_HEAD:
        return
    lock_path = db_path.with_name(db_path.name + ".migrate.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if _current_revision(engine) == SCHEMA_HEAD:
            return
        from alembic import command

        cfg = alembic_config(db_path)
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class Database:
    """Owns the engine and hands out read / write sessions."""

    def __init__(self, settings: Settings, *, migrate: bool = True) -> None:
        self.settings = settings
        ensure_private_dir(settings.data_dir)
        ensure_private_dir(settings.assets_dir)
        self.path = settings.db_path
        old_umask = os.umask(0o077)
        try:
            self.engine = create_sqlite_engine(self.path)
            if migrate:
                run_migrations(self.engine, self.path)
            else:
                with self.engine.connect():
                    pass
        finally:
            os.umask(old_umask)
        _secure_file(self.path)
        self._read = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._write = sessionmaker(
            bind=self.engine.execution_options(sqlite_begin="IMMEDIATE"), expire_on_commit=False
        )

    @contextlib.contextmanager
    def read(self) -> Iterator[Session]:
        session = self._read()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    @contextlib.contextmanager
    def write(self) -> Iterator[Session]:
        """A transactional session: commits on success, rolls back on error."""
        session = self._write()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            # Files written during a failed transaction (e.g. uploaded assets)
            # must not linger without their database rows.
            for path in session.info.get("ohmypm_new_files", []):
                with contextlib.suppress(OSError):
                    Path(path).unlink()
            raise
        finally:
            session.info.pop("ohmypm_new_files", None)
            session.close()

    def schema_revision(self) -> str | None:
        return _current_revision(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()
