"""Pydantic models used at the boundary of the core (inputs and outputs).

ORM objects never leave ``ohmypm.core``; interfaces receive these models and
serialise them with ``model_dump(mode="json")``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ohmypm.storage.models import SUMMARY_FIELDS

BUILTIN_ENTRY_TYPES: dict[str, str] = {
    "note": "General development note",
    "milestone": "Completed stage or achievement",
    "issue": "Problem, error and its investigation",
    "decision": "Technical choice and its rationale",
    "knowledge": "Long-lived project knowledge",
    "artifact": "Deliverable (program, script, model...) and how to use it",
}
ENTRY_STATUSES = ("open", "resolved", "obsolete")
ENTRY_SOURCES = ("cli", "mcp", "web", "api", "import")

MAX_TITLE_CHARS = 500
MAX_CONTENT_CHARS = 2_000_000
MAX_METADATA_BYTES = 64 * 1024
TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

EntryStatus = Literal["open", "resolved", "obsolete"]


def _clean_title(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("title must not be empty")
    if len(value) > MAX_TITLE_CHARS:
        raise ValueError(f"title is longer than {MAX_TITLE_CHARS} characters")
    return value


def _check_content(value: str) -> str:
    if len(value) > MAX_CONTENT_CHARS:
        raise ValueError(f"content is longer than {MAX_CONTENT_CHARS} characters")
    return value.replace("\r\n", "\n")


def _check_metadata(value: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metadata must be JSON-serialisable: {exc}") from exc
    if len(encoded.encode()) > MAX_METADATA_BYTES:
        raise ValueError("metadata is too large (max 64 KiB)")
    return value


def _check_type(value: str) -> str:
    value = value.strip().lower()
    if not TYPE_PATTERN.match(value):
        raise ValueError("type must be a short lowercase identifier such as 'note' or 'milestone'")
    return value


class _Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- inputs


class EntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "note"
    title: str
    content: str = ""
    status: EntryStatus | None = None
    author: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return _clean_title(v)

    @field_validator("content")
    @classmethod
    def _content(cls, v: str) -> str:
        return _check_content(v)

    @field_validator("metadata")
    @classmethod
    def _metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _check_metadata(v)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        return _check_type(v)


class EntryUpdate(BaseModel):
    """Partial update; ``None`` means "leave unchanged".

    To clear the status explicitly set ``clear_status=True``.
    """

    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    title: str | None = None
    content: str | None = None
    status: EntryStatus | None = None
    clear_status: bool = False
    metadata: dict[str, Any] | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return None if v is None else _clean_title(v)

    @field_validator("content")
    @classmethod
    def _content(cls, v: str | None) -> str | None:
        return None if v is None else _check_content(v)

    @field_validator("metadata")
    @classmethod
    def _metadata(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if v is None else _check_metadata(v)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str | None) -> str | None:
        return None if v is None else _check_type(v)


class SummaryUpdate(BaseModel):
    """Summary sections; ``None`` means "not provided"."""

    model_config = ConfigDict(extra="forbid")

    overview: str | None = None
    architecture: str | None = None
    current_state: str | None = None
    important_decisions: str | None = None
    known_issues: str | None = None
    next_steps: str | None = None

    def provided(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in SUMMARY_FIELDS if getattr(self, name) is not None}


# -------------------------------------------------------------------------- outputs


class ProjectOut(_Model):
    id: str
    name: str
    root_path: str
    description: str | None
    archived: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime | None
    metadata: dict[str, Any]
    root_exists: bool
    entry_count: int | None = None


class EntryOut(_Model):
    id: str
    project_id: str
    sequence: int
    type: str
    title: str
    content: str | None
    excerpt: str
    status: str | None
    author: str | None
    source: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]
    asset_ids: list[str] = Field(default_factory=list)


class EntryRevisionOut(_Model):
    id: str
    entry_id: str
    sequence: int
    revision: int
    type: str
    title: str
    content: str
    status: str | None
    reason: str
    changed_by: str | None
    created_at: datetime


class SummaryOut(_Model):
    project_id: str
    overview: str = ""
    architecture: str = ""
    current_state: str = ""
    important_decisions: str = ""
    known_issues: str = ""
    next_steps: str = ""
    revision: int = 0
    updated_by: str | None = None
    updated_at: datetime | None = None
    is_empty: bool = True


class AssetOut(_Model):
    id: str
    project_id: str
    entry_id: str | None
    filename: str
    mime_type: str
    size: int
    sha256: str
    created_at: datetime
    uri: str
    markdown: str


class SearchHit(_Model):
    kind: Literal["entry", "summary", "project"]
    project_id: str
    project_name: str
    ref_id: str
    title: str
    snippet: str
    entry_type: str | None = None
    sequence: int | None = None
    created_at: datetime | None = None
    score: float | None = None


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
