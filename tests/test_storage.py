from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ohmypm.config import load_settings
from ohmypm.storage.database import SCHEMA_HEAD, Database, alembic_config


def test_schema_head_constant_matches_alembic(settings) -> None:
    script = ScriptDirectory.from_config(alembic_config(settings.db_path))
    assert script.get_current_head() == SCHEMA_HEAD


def test_database_is_created_privately(db: Database, settings) -> None:
    assert db.schema_revision() == SCHEMA_HEAD
    assert oct(settings.data_dir.stat().st_mode & 0o777) == "0o700"
    assert oct(settings.db_path.stat().st_mode & 0o777) == "0o600"


def test_pragmas(db: Database) -> None:
    with db.read() as s:
        assert s.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert s.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert s.execute(text("PRAGMA busy_timeout")).scalar() >= 5000


def test_foreign_keys_enforced(db: Database) -> None:
    with pytest.raises(IntegrityError), db.write() as s:
        s.execute(
            text(
                "INSERT INTO entries (id, project_id, sequence, type, title, content, revision, created_at,"
                " updated_at, metadata) VALUES ('x', 'missing', 1, 'note', 't', '', 1, '2026-01-01', '2026-01-01', '{}')"
            )
        )


def test_reopen_is_idempotent(settings) -> None:
    Database(settings).dispose()
    Database(settings).dispose()
    con = sqlite3.connect(settings.db_path)
    assert con.execute("SELECT count(*) FROM alembic_version").fetchone()[0] == 1
    con.close()


def test_config_is_tolerant_of_foreign_keys(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "config.toml").write_text(
        'server_url = "http://127.0.0.1:8765"\ntoken = "abc"\n[web]\nport = 9999\n'
    )
    s = load_settings()
    assert s.web_port == 9999
    (cfg / "config.toml").write_text("this is [not toml")
    assert load_settings().web_port == 8737
