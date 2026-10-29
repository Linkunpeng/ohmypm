"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-29 13:18:57.794933
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CHECKPOINT_IMMUTABLE_FN = """
CREATE OR REPLACE FUNCTION ohmypm_reject_checkpoint_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'checkpoints are append-only (id=%)', OLD.id USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "agent_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("agent_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "options", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("write_mode", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_profiles")),
        sa.UniqueConstraint("name", name=op.f("uq_agent_profiles_name")),
    )
    op.create_index(
        "uq_agent_profiles_default_per_type",
        "agent_profiles",
        ["agent_type"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("scope", "key", name=op.f("pk_idempotency_keys")),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("archived", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(description, ''))", persisted=True
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(
        "ix_projects_name_trgm",
        "projects",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index("ix_projects_search", "projects", ["search_vector"], unique=False, postgresql_using="gin")
    op.create_table(
        "runners",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("host_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), server_default="", nullable=False),
        sa.Column("max_parallel", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "allowed_roots",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "agents", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runners")),
    )
    op.create_index(op.f("ix_runners_host_id"), "runners", ["host_id"], unique=False)
    op.create_table(
        "workspaces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("host_id", sa.Text(), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_workspaces_project_id_projects"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("host_id", "root_path", name=op.f("uq_workspaces_host_id_root_path")),
    )
    op.create_index(op.f("ix_workspaces_project_id"), "workspaces", ["project_id"], unique=False)
    op.create_index(
        "ix_workspaces_root_path_trgm",
        "workspaces",
        ["root_path"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"root_path": "gin_trgm_ops"},
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("parent_task_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("raw_request", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.Text(), server_default="todo", nullable=False),
        sa.Column("priority", sa.Text(), server_default="normal", nullable=False),
        sa.Column(
            "acceptance_criteria",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("acceptance_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "completed_items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "remaining_items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("next_action", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "blockers", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(description, '') || ' ' || coalesce(raw_request, '') || ' ' || coalesce(next_action, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name=op.f("ck_tasks_priority")),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'blocked', 'awaiting_user', 'completed', 'cancelled')",
            name=op.f("ck_tasks_status"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_task_id"], ["tasks.id"], name=op.f("fk_tasks_parent_task_id_tasks"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_tasks_project_id_projects"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_tasks_workspace_id_workspaces"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
        sa.UniqueConstraint("number", name=op.f("uq_tasks_number")),
    )
    op.create_index(op.f("ix_tasks_parent_task_id"), "tasks", ["parent_task_id"], unique=False)
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
    op.create_index(
        "ix_tasks_raw_request_trgm",
        "tasks",
        ["raw_request"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"raw_request": "gin_trgm_ops"},
    )
    op.create_index("ix_tasks_search", "tasks", ["search_vector"], unique=False, postgresql_using="gin")
    op.create_index("ix_tasks_status_updated", "tasks", ["status", "updated_at"], unique=False)
    op.create_index(
        "ix_tasks_title_trgm",
        "tasks",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(op.f("ix_tasks_workspace_id"), "tasks", ["workspace_id"], unique=False)
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("agent_type", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("native_session_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.CheckConstraint("status IN ('active', 'closed')", name=op.f("ck_agent_sessions_status")),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_agent_sessions_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_sessions")),
    )
    op.create_index(op.f("ix_agent_sessions_task_id"), "agent_sessions", ["task_id"], unique=False)
    op.create_table(
        "artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("storage_mode", sa.Text(), server_default="reference", nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("version_label", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "usage", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "build", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "environment",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "deployment", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "verification",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || coalesce(storage_uri, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint("storage_mode IN ('reference', 'managed')", name=op.f("ck_artifacts_storage_mode")),
        sa.CheckConstraint(
            "type IN ('executable', 'script', 'library', 'document', 'model', 'dataset', 'resource', 'container', 'report', 'other')",
            name=op.f("ck_artifacts_type"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_artifacts_project_id_projects"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_artifacts_task_id_tasks"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_artifacts_workspace_id_workspaces"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
    )
    op.create_index(
        "ix_artifacts_name_trgm",
        "artifacts",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(op.f("ix_artifacts_project_id"), "artifacts", ["project_id"], unique=False)
    op.create_index("ix_artifacts_search", "artifacts", ["search_vector"], unique=False, postgresql_using="gin")
    op.create_index(op.f("ix_artifacts_task_id"), "artifacts", ["task_id"], unique=False)
    op.create_table(
        "decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "options", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("blocking", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("selected_option", sa.Text(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(question, '') || ' ' || coalesce(context, '') || ' ' || coalesce(response, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('pending', 'resolved', 'cancelled')", name=op.f("ck_decisions_status")),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_decisions_project_id_projects"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_decisions_task_id_tasks"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decisions")),
    )
    op.create_index(op.f("ix_decisions_project_id"), "decisions", ["project_id"], unique=False)
    op.create_index(
        "ix_decisions_question_trgm",
        "decisions",
        ["question"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"question": "gin_trgm_ops"},
    )
    op.create_index("ix_decisions_search", "decisions", ["search_vector"], unique=False, postgresql_using="gin")
    op.create_index("ix_decisions_status", "decisions", ["status"], unique=False)
    op.create_index(op.f("ix_decisions_task_id"), "decisions", ["task_id"], unique=False)
    op.create_table(
        "project_knowledge",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), server_default="other", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_task_id", sa.UUID(), nullable=True),
        sa.Column("verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("superseded_by", sa.UUID(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))", persisted=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('architecture', 'environment', 'constraint', 'algorithm', 'experience', 'known_issue', 'other')",
            name=op.f("ck_project_knowledge_category"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_project_knowledge_project_id_projects"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_task_id"],
            ["tasks.id"],
            name=op.f("fk_project_knowledge_source_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"],
            ["project_knowledge.id"],
            name=op.f("fk_project_knowledge_superseded_by_project_knowledge"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_knowledge")),
    )
    op.create_index(
        "ix_project_knowledge_content_trgm",
        "project_knowledge",
        ["content"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )
    op.create_index(op.f("ix_project_knowledge_project_id"), "project_knowledge", ["project_id"], unique=False)
    op.create_index(
        "ix_project_knowledge_search", "project_knowledge", ["search_vector"], unique=False, postgresql_using="gin"
    )
    op.create_index("ix_project_knowledge_tags", "project_knowledge", ["tags"], unique=False, postgresql_using="gin")
    op.create_index(
        "ix_project_knowledge_title_trgm",
        "project_knowledge",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_table(
        "task_dependencies",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("depends_on_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("task_id <> depends_on_id", name=op.f("ck_task_dependencies_no_self_dependency")),
        sa.ForeignKeyConstraint(
            ["depends_on_id"], ["tasks.id"], name=op.f("fk_task_dependencies_depends_on_id_tasks"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_task_dependencies_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("task_id", "depends_on_id", name=op.f("pk_task_dependencies")),
    )
    op.create_index(op.f("ix_task_dependencies_depends_on_id"), "task_dependencies", ["depends_on_id"], unique=False)
    op.create_table(
        "task_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_task_events_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_events")),
    )
    op.create_index("ix_task_events_task_id_id", "task_events", ["task_id", "id"], unique=False)
    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("version_label", sa.Text(), nullable=True),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_artifact_versions_artifact_id_artifacts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_versions")),
    )
    op.create_index(op.f("ix_artifact_versions_artifact_id"), "artifact_versions", ["artifact_id"], unique=False)
    op.create_table(
        "checkpoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "completed", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "remaining", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("current_issue", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "attempts", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "findings", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "relevant_files",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "next_steps", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "verification",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("auto_generated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_checkpoints_session_id_agent_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_checkpoints_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkpoints")),
    )
    op.create_index(op.f("ix_checkpoints_run_id"), "checkpoints", ["run_id"], unique=False)
    op.create_index("ix_checkpoints_task_created", "checkpoints", ["task_id", "created_at"], unique=False)
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("runner_id", sa.UUID(), nullable=True),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("agent_type", sa.Text(), nullable=False),
        sa.Column("agent_profile_id", sa.UUID(), nullable=True),
        sa.Column(
            "profile_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("write_mode", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("instructions", sa.Text(), server_default="", nullable=False),
        sa.Column("context_mode", sa.Text(), server_default="standard", nullable=False),
        sa.Column("from_checkpoint_id", sa.UUID(), nullable=True),
        sa.Column("resume_native", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column(
            "usage", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("native_session_id", sa.Text(), nullable=True),
        sa.Column(
            "command", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_seq", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("dispatch_depth", sa.Integer(), server_default="0", nullable=False),
        sa.Column("parent_run_id", sa.UUID(), nullable=True),
        sa.Column("agent_token_hash", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'starting', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled', 'interrupted', 'lost')",
            name=op.f("ck_agent_runs_status"),
        ),
        sa.CheckConstraint("timeout_seconds > 0", name=op.f("ck_agent_runs_timeout_positive")),
        sa.ForeignKeyConstraint(
            ["agent_profile_id"],
            ["agent_profiles.id"],
            name=op.f("fk_agent_runs_agent_profile_id_agent_profiles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["from_checkpoint_id"],
            ["checkpoints.id"],
            name=op.f("fk_agent_runs_from_checkpoint_id_checkpoints"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_runs_parent_run_id_agent_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["runner_id"], ["runners.id"], name=op.f("fk_agent_runs_runner_id_runners"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_agent_runs_session_id_agent_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_agent_runs_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_agent_runs_workspace_id_workspaces"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint("agent_token_hash", name=op.f("uq_agent_runs_agent_token_hash")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_agent_runs_idempotency_key")),
    )
    op.create_index(op.f("ix_agent_runs_runner_id"), "agent_runs", ["runner_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_session_id"), "agent_runs", ["session_id"], unique=False)
    op.create_index("ix_agent_runs_status_created", "agent_runs", ["status", "created_at"], unique=False)
    op.create_index(op.f("ix_agent_runs_task_id"), "agent_runs", ["task_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_workspace_id"), "agent_runs", ["workspace_id"], unique=False)
    op.create_index(
        "uq_agent_runs_active_writer_per_workspace",
        "agent_runs",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("write_mode AND status IN ('starting', 'running', 'waiting_approval')"),
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["agent_runs.id"], name=op.f("fk_run_events_run_id_agent_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_events")),
        sa.UniqueConstraint("run_id", "seq", name=op.f("uq_run_events_run_id_seq")),
    )
    op.create_index(
        "uq_run_events_client_id",
        "run_events",
        ["run_id", "client_id"],
        unique=True,
        postgresql_where=sa.text("client_id IS NOT NULL"),
    )
    # ### end Alembic commands ###
    op.execute(CHECKPOINT_IMMUTABLE_FN)
    op.execute(
        "CREATE TRIGGER checkpoints_append_only BEFORE UPDATE ON checkpoints "
        "FOR EACH ROW EXECUTE FUNCTION ohmypm_reject_checkpoint_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS checkpoints_append_only ON checkpoints")
    op.execute("DROP FUNCTION IF EXISTS ohmypm_reject_checkpoint_update()")
    op.drop_index("uq_run_events_client_id", table_name="run_events", postgresql_where=sa.text("client_id IS NOT NULL"))
    op.drop_table("run_events")
    op.drop_index(
        "uq_agent_runs_active_writer_per_workspace",
        table_name="agent_runs",
        postgresql_where=sa.text("write_mode AND status IN ('starting', 'running', 'waiting_approval')"),
    )
    op.drop_index(op.f("ix_agent_runs_workspace_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_task_id"), table_name="agent_runs")
    op.drop_index("ix_agent_runs_status_created", table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_session_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_runner_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_checkpoints_task_created", table_name="checkpoints")
    op.drop_index(op.f("ix_checkpoints_run_id"), table_name="checkpoints")
    op.drop_table("checkpoints")
    op.drop_index(op.f("ix_artifact_versions_artifact_id"), table_name="artifact_versions")
    op.drop_table("artifact_versions")
    op.drop_index("ix_task_events_task_id_id", table_name="task_events")
    op.drop_table("task_events")
    op.drop_index(op.f("ix_task_dependencies_depends_on_id"), table_name="task_dependencies")
    op.drop_table("task_dependencies")
    op.drop_index(
        "ix_project_knowledge_title_trgm",
        table_name="project_knowledge",
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.drop_index("ix_project_knowledge_tags", table_name="project_knowledge", postgresql_using="gin")
    op.drop_index("ix_project_knowledge_search", table_name="project_knowledge", postgresql_using="gin")
    op.drop_index(op.f("ix_project_knowledge_project_id"), table_name="project_knowledge")
    op.drop_index(
        "ix_project_knowledge_content_trgm",
        table_name="project_knowledge",
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )
    op.drop_table("project_knowledge")
    op.drop_index(op.f("ix_decisions_task_id"), table_name="decisions")
    op.drop_index("ix_decisions_status", table_name="decisions")
    op.drop_index("ix_decisions_search", table_name="decisions", postgresql_using="gin")
    op.drop_index(
        "ix_decisions_question_trgm",
        table_name="decisions",
        postgresql_using="gin",
        postgresql_ops={"question": "gin_trgm_ops"},
    )
    op.drop_index(op.f("ix_decisions_project_id"), table_name="decisions")
    op.drop_table("decisions")
    op.drop_index(op.f("ix_artifacts_task_id"), table_name="artifacts")
    op.drop_index("ix_artifacts_search", table_name="artifacts", postgresql_using="gin")
    op.drop_index(op.f("ix_artifacts_project_id"), table_name="artifacts")
    op.drop_index(
        "ix_artifacts_name_trgm",
        table_name="artifacts",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_table("artifacts")
    op.drop_index(op.f("ix_agent_sessions_task_id"), table_name="agent_sessions")
    op.drop_table("agent_sessions")
    op.drop_index(op.f("ix_tasks_workspace_id"), table_name="tasks")
    op.drop_index(
        "ix_tasks_title_trgm", table_name="tasks", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}
    )
    op.drop_index("ix_tasks_status_updated", table_name="tasks")
    op.drop_index("ix_tasks_search", table_name="tasks", postgresql_using="gin")
    op.drop_index(
        "ix_tasks_raw_request_trgm",
        table_name="tasks",
        postgresql_using="gin",
        postgresql_ops={"raw_request": "gin_trgm_ops"},
    )
    op.drop_index(op.f("ix_tasks_project_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_parent_task_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(
        "ix_workspaces_root_path_trgm",
        table_name="workspaces",
        postgresql_using="gin",
        postgresql_ops={"root_path": "gin_trgm_ops"},
    )
    op.drop_index(op.f("ix_workspaces_project_id"), table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_index(op.f("ix_runners_host_id"), table_name="runners")
    op.drop_table("runners")
    op.drop_index("ix_projects_search", table_name="projects", postgresql_using="gin")
    op.drop_index(
        "ix_projects_name_trgm", table_name="projects", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}
    )
    op.drop_table("projects")
    op.drop_table("idempotency_keys")
    op.drop_index(
        "uq_agent_profiles_default_per_type", table_name="agent_profiles", postgresql_where=sa.text("is_default")
    )
    op.drop_table("agent_profiles")
    # ### end Alembic commands ###
