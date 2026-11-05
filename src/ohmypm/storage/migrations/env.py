"""Alembic environment for ohmypm.

ohmypm runs migrations programmatically (``ohmypm.storage.database``), passing
an open connection via ``config.attributes["connection"]``. Running Alembic
from the command line with the repository ``alembic.ini`` also works.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from ohmypm.storage.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
