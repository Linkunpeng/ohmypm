"""SQLAlchemy ORM models.

The schema itself is owned by Alembic migrations (``storage/migrations``);
these models must stay in sync with them. The FTS5 search index and its
triggers live only in the migrations because they are raw SQLite objects.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator[datetime]):
    """Store timezone-aware datetimes as naive UTC; load them back as aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    # Canonical (realpath) project root. Unique among active projects only
    # (partial unique index in the migration), so archived projects keep their
    # last known path for re-registration.
    root_path: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    next_sequence: Mapped[int] = mapped_column(Integer, default=1)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    entries: Mapped[list[Entry]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    summary: Mapped[ProjectSummary | None] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("project_id", "sequence", name="uq_entries_project_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, default="")
    # Lifecycle for entries where it matters: issues are "open"/"resolved";
    # any entry may be marked "obsolete" (superseded). NULL means not tracked.
    status: Mapped[str | None] = mapped_column(String(32), default=None)
    author: Mapped[str | None] = mapped_column(String(200), default=None)
    source: Mapped[str | None] = mapped_column(String(32), default=None)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    project: Mapped[Project] = relationship(back_populates="entries")


class EntryRevision(Base):
    """Snapshot of an entry *before* an edit or deletion."""

    __tablename__ = "entry_revisions"
    __table_args__ = (UniqueConstraint("entry_id", "revision", name="uq_entry_revisions_entry_revision"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Deliberately not a foreign key: revisions of deleted entries are kept so
    # deletions can be recovered. They are removed together with their project.
    entry_id: Mapped[str] = mapped_column(String(36))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(32), default=None)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    reason: Mapped[str] = mapped_column(String(16), default="edit")  # edit | delete
    changed_by: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


SUMMARY_FIELDS: tuple[str, ...] = (
    "overview",
    "architecture",
    "current_state",
    "important_decisions",
    "known_issues",
    "next_steps",
)


class ProjectSummary(Base):
    __tablename__ = "project_summaries"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    overview: Mapped[str] = mapped_column(Text, default="")
    architecture: Mapped[str] = mapped_column(Text, default="")
    current_state: Mapped[str] = mapped_column(Text, default="")
    important_decisions: Mapped[str] = mapped_column(Text, default="")
    known_issues: Mapped[str] = mapped_column(Text, default="")
    next_steps: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="summary")


class SummaryRevision(Base):
    """Snapshot of a summary before it was overwritten."""

    __tablename__ = "summary_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "revision", name="uq_summary_revisions_project_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    changed_by: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    entry_id: Mapped[str | None] = mapped_column(ForeignKey("entries.id", ondelete="SET NULL"), default=None)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # Relative to the assets directory; never an absolute path.
    storage_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
