"""Add persistent agent instructions.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_profiles", sa.Column("instructions", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("agent_profiles", "instructions")
