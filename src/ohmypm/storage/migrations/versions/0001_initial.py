"""Initial schema: projects, entries, revisions, summaries, assets, FTS5 index.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime()


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("archived_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("last_activity_at", TS, nullable=True),
        sa.Column("next_sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_projects_root_path", "projects", ["root_path"])
    op.create_index(
        "uq_projects_active_root_path",
        "projects",
        ["root_path"],
        unique=True,
        sqlite_where=sa.text("archived_at IS NULL"),
    )
    op.create_index("ix_projects_last_activity_at", "projects", ["last_activity_at"])

    op.create_table(
        "entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE", name="fk_entries_project_id_projects"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("project_id", "sequence", name="uq_entries_project_sequence"),
    )
    op.create_index("ix_entries_project_created", "entries", ["project_id", "created_at"])
    op.create_index("ix_entries_project_type", "entries", ["project_id", "type"])
    op.create_index("ix_entries_project_status", "entries", ["project_id", "status"])
    op.create_index("ix_entries_created_at", "entries", ["created_at"])

    op.create_table(
        "entry_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entry_id", sa.String(36), nullable=False),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE", name="fk_entry_revisions_project_id_projects"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.String(16), nullable=False, server_default="edit"),
        sa.Column("changed_by", sa.String(200), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("entry_id", "revision", name="uq_entry_revisions_entry_revision"),
    )
    op.create_index("ix_entry_revisions_project_id", "entry_revisions", ["project_id"])

    op.create_table(
        "project_summaries",
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_summaries_project_id_projects"),
            primary_key=True,
        ),
        sa.Column("overview", sa.Text(), nullable=False, server_default=""),
        sa.Column("architecture", sa.Text(), nullable=False, server_default=""),
        sa.Column("current_state", sa.Text(), nullable=False, server_default=""),
        sa.Column("important_decisions", sa.Text(), nullable=False, server_default=""),
        sa.Column("known_issues", sa.Text(), nullable=False, server_default=""),
        sa.Column("next_steps", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(200), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )

    op.create_table(
        "summary_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE", name="fk_summary_revisions_project_id_projects"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("changed_by", sa.String(200), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("project_id", "revision", name="uq_summary_revisions_project_revision"),
    )

    op.create_table(
        "assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE", name="fk_assets_project_id_projects"),
            nullable=False,
        ),
        sa.Column(
            "entry_id",
            sa.String(36),
            sa.ForeignKey("entries.id", ondelete="SET NULL", name="fk_assets_entry_id_entries"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_assets_project_id", "assets", ["project_id"])
    op.create_index("ix_assets_entry_id", "assets", ["entry_id"])

    _create_search_index()


# Full-text search. ``search_map`` gives every indexed document a stable
# integer rowid (implicit rowids of non-INTEGER-PK tables may change on VACUUM).
# The trigram tokenizer makes substring search work for CJK text; queries
# shorter than three characters fall back to LIKE in ohmypm.core.search.
SEARCH_SQL = [
    """
    CREATE TABLE search_map (
        rowid INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        ref_id TEXT NOT NULL,
        UNIQUE (kind, ref_id)
    )
    """,
    """
    CREATE VIRTUAL TABLE search_index USING fts5(
        kind UNINDEXED,
        ref_id UNINDEXED,
        project_id UNINDEXED,
        entry_type UNINDEXED,
        created_at UNINDEXED,
        title,
        body,
        tokenize = 'trigram'
    )
    """,
    # -- entries --------------------------------------------------------------
    """
    CREATE TRIGGER search_entries_ai AFTER INSERT ON entries BEGIN
        INSERT OR IGNORE INTO search_map(kind, ref_id) VALUES ('entry', new.id);
        INSERT INTO search_index(rowid, kind, ref_id, project_id, entry_type, created_at, title, body)
        VALUES ((SELECT rowid FROM search_map WHERE kind = 'entry' AND ref_id = new.id),
                'entry', new.id, new.project_id, new.type, new.created_at, new.title, new.content);
    END
    """,
    """
    CREATE TRIGGER search_entries_au AFTER UPDATE OF title, content, type, project_id, created_at ON entries
    BEGIN
        DELETE FROM search_index
        WHERE rowid = (SELECT rowid FROM search_map WHERE kind = 'entry' AND ref_id = old.id);
        INSERT INTO search_index(rowid, kind, ref_id, project_id, entry_type, created_at, title, body)
        VALUES ((SELECT rowid FROM search_map WHERE kind = 'entry' AND ref_id = new.id),
                'entry', new.id, new.project_id, new.type, new.created_at, new.title, new.content);
    END
    """,
    """
    CREATE TRIGGER search_entries_ad AFTER DELETE ON entries BEGIN
        DELETE FROM search_index
        WHERE rowid = (SELECT rowid FROM search_map WHERE kind = 'entry' AND ref_id = old.id);
        DELETE FROM search_map WHERE kind = 'entry' AND ref_id = old.id;
    END
    """,
    # -- summaries ------------------------------------------------------------
    """
    CREATE TRIGGER search_summaries_ai AFTER INSERT ON project_summaries BEGIN
        INSERT OR IGNORE INTO search_map(kind, ref_id) VALUES ('summary', new.project_id);
        INSERT INTO search_index(rowid, kind, ref_id, project_id, entry_type, created_at, title, body)
        VALUES ((SELECT rowid FROM search_map WHERE kind = 'summary' AND ref_id = new.project_id),
                'summary', new.project_id, new.project_id, NULL, new.updated_at, 'Project summary',
                new.overview || char(10) || new.architecture || char(10) || new.current_state || char(10) ||
                new.important_decisions || char(10) || new.known_issues || char(10) || new.next_steps);
    END
    """,
    """
    CREATE TRIGGER search_summaries_au AFTER UPDATE ON project_summaries BEGIN
        DELETE FROM search_index
        WHERE rowid = (SELECT rowid FROM search_map WHERE kind = 'summary' AND ref_id = old.project_id);
        INSERT INTO search_index(rowid, kind, ref_id, project_id, entry_type, created_at, title, body)
        VALUES ((SELECT rowid FROM search_map WHERE kind = 'summary' AND ref_id = new.project_id),
                'summary', new.project_id, new.project_id, NULL, new.updated_at, 'Project summary',
                new.overview || char(10) || new.architecture || char(10) || new.current_state || char(10) ||
                new.important_decisions || char(10) || new.known_issues || char(10) || new.next_steps);
    END
    """,
    """
    CREATE TRIGGER search_summaries_ad AFTER DELETE ON project_summaries BEGIN
        DELETE FROM search_index
        WHERE rowid = (SELECT rowid FROM search_map WHERE kind = 'summary' AND ref_id = old.project_id);
        DELETE FROM search_map WHERE kind = 'summary' AND ref_id = old.project_id;
    END
    """,
    # -- projects -------------------------------------------------------------
    """
    CREATE TRIGGER search_projects_ai AFTER INSERT ON projects BEGIN
        INSERT OR IGNORE INTO search_map(kind, ref_id) VALUES ('project', new.id);
        INSERT INTO search_index(rowid, kind, ref_id, project_id, entry_type, created_at, title, body)
        VALUES ((SELECT rowid FROM search_map WHERE kind = 'project' AND ref_id = new.id),
                'project', new.id, new.id, NULL, new.created_at, new.name,
                coalesce(new.description, '') || char(10) || new.root_path);
    END
    """,
    """
    CREATE TRIGGER search_projects_au AFTER UPDATE OF name, description, root_path ON projects BEGIN
        DELETE FROM search_index
        WHERE rowid = (SELECT rowid FROM search_map WHERE kind = 'project' AND ref_id = old.id);
        INSERT INTO search_index(rowid, kind, ref_id, project_id, entry_type, created_at, title, body)
        VALUES ((SELECT rowid FROM search_map WHERE kind = 'project' AND ref_id = new.id),
                'project', new.id, new.id, NULL, new.created_at, new.name,
                coalesce(new.description, '') || char(10) || new.root_path);
    END
    """,
    """
    CREATE TRIGGER search_projects_ad AFTER DELETE ON projects BEGIN
        DELETE FROM search_index
        WHERE rowid = (SELECT rowid FROM search_map WHERE kind = 'project' AND ref_id = old.id);
        DELETE FROM search_map WHERE kind = 'project' AND ref_id = old.id;
    END
    """,
]


def _create_search_index() -> None:
    for statement in SEARCH_SQL:
        op.execute(statement)


def downgrade() -> None:
    for trigger in (
        "search_entries_ai",
        "search_entries_au",
        "search_entries_ad",
        "search_summaries_ai",
        "search_summaries_au",
        "search_summaries_ad",
        "search_projects_ai",
        "search_projects_au",
        "search_projects_ad",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute("DROP TABLE IF EXISTS search_index")
    op.execute("DROP TABLE IF EXISTS search_map")
    op.drop_table("assets")
    op.drop_table("summary_revisions")
    op.drop_table("project_summaries")
    op.drop_table("entry_revisions")
    op.drop_table("entries")
    op.drop_table("projects")
