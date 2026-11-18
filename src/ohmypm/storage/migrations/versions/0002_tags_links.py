"""Entry tags and links between entries.

* ``entries.tags`` / ``entry_revisions.tags``: JSON list of normalised tags,
  so revisions and restores cover them like the other entry fields.
* ``entry_links``: directed links between entries of the same project
  (``relates``, ``fixes``, ``supersedes`` and the automatic ``mentions``
  derived from ``#N`` in the body). Mentions are backfilled here.

Revision ID: 0002_tags_links
Revises: 0001_initial
Create Date: 2026-11-18
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from ohmypm.core.text import entry_mentions

revision: str = "0002_tags_links"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("entries", sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("entry_revisions", sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
    op.create_table(
        "entry_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE", name="fk_entry_links_project_id_projects"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("entries.id", ondelete="CASCADE", name="fk_entry_links_source_id_entries"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.String(36),
            sa.ForeignKey("entries.id", ondelete="CASCADE", name="fk_entry_links_target_id_entries"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_id", "target_id", "kind", name="uq_entry_links_source_id"),
    )
    op.create_index("ix_entry_links_project_id", "entry_links", ["project_id"])
    op.create_index("ix_entry_links_target_id", "entry_links", ["target_id"])
    _backfill_mentions()


def _backfill_mentions() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, project_id, sequence, content FROM entries")).all()
    by_sequence = {(project_id, sequence): entry_id for entry_id, project_id, sequence, _ in rows}
    # Same text format SQLAlchemy uses for DateTime columns on SQLite.
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    links = [
        {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "source_id": entry_id,
            "target_id": by_sequence[(project_id, number)],
            "created_at": now,
        }
        for entry_id, project_id, sequence, content in rows
        for number in sorted(entry_mentions(content))
        if number != sequence and (project_id, number) in by_sequence
    ]
    if links:
        conn.execute(
            sa.text(
                "INSERT INTO entry_links (id, project_id, source_id, target_id, kind, created_at) "
                "VALUES (:id, :project_id, :source_id, :target_id, 'mentions', :created_at)"
            ),
            links,
        )


def downgrade() -> None:
    op.drop_index("ix_entry_links_target_id", "entry_links")
    op.drop_index("ix_entry_links_project_id", "entry_links")
    op.drop_table("entry_links")
    with op.batch_alter_table("entry_revisions") as batch:
        batch.drop_column("tags")
    with op.batch_alter_table("entries") as batch:
        batch.drop_column("tags")
