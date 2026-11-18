"""Git commit stamp on project summaries.

``project_summaries.git``: ``{"commit", "branch"}`` of the project's HEAD
when the summary last changed (``NULL`` when unknown), so the context can
report how many commits the summary is behind.

Revision ID: 0003_summary_git
Revises: 0002_tags_links
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_summary_git"
down_revision: str | None = "0002_tags_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("project_summaries", sa.Column("git", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project_summaries") as batch:
        batch.drop_column("git")
