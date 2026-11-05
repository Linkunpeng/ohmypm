"""High-level operations shared by the CLI, the MCP server and the HTTP API.

Every method opens its own transaction and returns Pydantic models. Project
resolution is always explicit: callers pass a project reference (id, id
prefix or name) or a workspace path; the service never guesses from its own
working directory.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ohmypm.config import Settings, load_settings
from ohmypm.core import assets as assets_core
from ohmypm.core import entries as entries_core
from ohmypm.core import projects as projects_core
from ohmypm.core import search as search_core
from ohmypm.core import summaries as summaries_core
from ohmypm.core.context import ContextResult, build_context
from ohmypm.core.errors import ValidationError
from ohmypm.core.schemas import (
    AssetOut,
    EntryCreate,
    EntryOut,
    EntryRevisionOut,
    EntryUpdate,
    Page,
    ProjectOut,
    SearchHit,
    SummaryOut,
    SummaryUpdate,
)
from ohmypm.core.text import excerpt
from ohmypm.storage.database import Database
from ohmypm.storage.models import Project, SummaryRevision


class MemoryService:
    def __init__(self, settings: Settings | None = None, db: Database | None = None) -> None:
        self.settings = settings or load_settings()
        self.db = db or Database(self.settings)

    # ------------------------------------------------------------ helpers
    def _project(self, session: Session, project: str | None, path: str | os.PathLike[str] | None) -> Project:
        if project:
            return projects_core.get_project(session, project)
        if path is not None:
            return projects_core.require_project_for_path(session, path)
        raise ValidationError("Specify a project (id or name) or a workspace path")

    # ----------------------------------------------------------- projects
    def status(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        resolved = projects_core.canonical_path(path)
        with self.db.read() as s:
            project = projects_core.find_project_for_path(s, resolved)
            if project is None:
                return {
                    "registered": False,
                    "path": resolved,
                    "project": None,
                    "hint": "This directory is not registered with ohmypm. "
                    "Run `ohmypm register` in the project root to start recording.",
                }
            count = projects_core.entry_count(s, project)
            summary = summaries_core.get_summary(s, project)
            _, open_total = entries_core.list_entries(
                s, project_ids=[project.id], types=["issue"], statuses=["open"], limit=1
            )
            return {
                "registered": True,
                "path": resolved,
                "relative_path": os.path.relpath(resolved, project.root_path),
                "project": projects_core.to_out(project, count).model_dump(mode="json"),
                "summary_exists": not summary.is_empty,
                "summary_updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
                "open_issues": open_total,
            }

    def register(
        self, path: str | os.PathLike[str], *, name: str | None = None, description: str | None = None
    ) -> tuple[ProjectOut, str]:
        with self.db.write() as s:
            project, outcome = projects_core.register_project(s, path, name=name, description=description)
            return projects_core.to_out(project, projects_core.entry_count(s, project)), outcome

    def unregister(
        self, *, project: str | None = None, path: str | os.PathLike[str] | None = None, purge: bool = False
    ) -> ProjectOut:
        with self.db.write() as s:
            target = self._project(s, project, path)
            out = projects_core.to_out(target, projects_core.entry_count(s, target))
            if purge:
                projects_core.purge_project(s, self.settings, target)
            else:
                projects_core.unregister_project(s, target)
                out = projects_core.to_out(target, out.entry_count)
            return out

    def list_projects(self, *, include_archived: bool = False) -> list[ProjectOut]:
        with self.db.read() as s:
            return [
                projects_core.to_out(p, n)
                for p, n in projects_core.list_projects(s, include_archived=include_archived)
            ]

    def get_project(
        self, *, project: str | None = None, path: str | os.PathLike[str] | None = None
    ) -> ProjectOut:
        with self.db.read() as s:
            target = self._project(s, project, path)
            return projects_core.to_out(target, projects_core.entry_count(s, target))

    def update_project(
        self,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectOut:
        with self.db.write() as s:
            target = self._project(s, project, path)
            projects_core.update_project(s, target, name=name, description=description, metadata=metadata)
            return projects_core.to_out(target, projects_core.entry_count(s, target))

    def relink(
        self,
        new_path: str | os.PathLike[str],
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
    ) -> ProjectOut:
        with self.db.write() as s:
            target = self._project(s, project, path)
            projects_core.relink_project(s, target, new_path)
            return projects_core.to_out(target, projects_core.entry_count(s, target))

    # ------------------------------------------------------------ entries
    def add_entry(
        self, data: EntryCreate, *, project: str | None = None, path: str | os.PathLike[str] | None = None
    ) -> EntryOut:
        if data.author is None and self.settings.default_author:
            data = data.model_copy(update={"author": self.settings.default_author})
        with self.db.write() as s:
            target = self._project(s, project, path)
            entry = entries_core.add_entry(s, target, data, allowed_types=self.settings.entry_types)
            return entries_core.to_out(entry)

    def list_entries(
        self,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        all_projects: bool = False,
        types: list[str] | None = None,
        statuses: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        query: str | None = None,
        author: str | None = None,
        order: str = "asc",
        sort: str = "sequence",
        limit: int = 50,
        offset: int = 0,
        include_content: bool = False,
    ) -> Page[EntryOut]:
        with self.db.read() as s:
            project_ids = None if all_projects else [self._project(s, project, path).id]
            items, total = entries_core.list_entries(
                s,
                project_ids=project_ids,
                types=types,
                statuses=statuses,
                since=since,
                until=until,
                query=query,
                author=author,
                order=order,
                sort=sort,
                limit=limit,
                offset=offset,
            )
            return Page[EntryOut](
                items=[entries_core.to_out(e, include_content=include_content) for e in items],
                total=total,
                limit=limit,
                offset=offset,
            )

    def get_entry(
        self, ref: str, *, project: str | None = None, path: str | os.PathLike[str] | None = None
    ) -> EntryOut:
        with self.db.read() as s:
            target = self._project(s, project, path) if (project or path is not None) else None
            return entries_core.to_out(entries_core.get_entry(s, ref, project=target))

    def update_entry(
        self,
        ref: str,
        changes: EntryUpdate,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        changed_by: str | None = None,
        expected_revision: int | None = None,
    ) -> tuple[EntryOut, bool]:
        with self.db.write() as s:
            target = self._project(s, project, path) if (project or path is not None) else None
            entry = entries_core.get_entry(s, ref, project=target)
            entry, changed = entries_core.update_entry(
                s,
                entry,
                changes,
                changed_by=changed_by,
                allowed_types=self.settings.entry_types,
                expected_revision=expected_revision,
            )
            return entries_core.to_out(entry), changed

    def delete_entry(
        self,
        ref: str,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        changed_by: str | None = None,
    ) -> EntryOut:
        with self.db.write() as s:
            target = self._project(s, project, path) if (project or path is not None) else None
            entry = entries_core.get_entry(s, ref, project=target)
            out = entries_core.to_out(entry)
            entries_core.delete_entry(s, entry, changed_by=changed_by)
            return out

    def entry_history(
        self, ref: str, *, project: str | None = None, path: str | os.PathLike[str] | None = None
    ) -> list[EntryRevisionOut]:
        with self.db.read() as s:
            target = self._project(s, project, path) if (project or path is not None) else None
            entry = entries_core.get_entry(s, ref, project=target)
            return [entries_core.revision_to_out(r) for r in entries_core.list_revisions(s, entry.id)]

    def restore_entry(
        self,
        ref: str,
        revision: int,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        changed_by: str | None = None,
    ) -> EntryOut:
        with self.db.write() as s:
            target = self._project(s, project, path) if (project or path is not None) else None
            entry = entries_core.get_entry(s, ref, project=target)
            return entries_core.to_out(
                entries_core.restore_revision(s, entry, revision, changed_by=changed_by)
            )

    def deleted_entries(
        self, *, project: str | None = None, path: str | os.PathLike[str] | None = None
    ) -> list[EntryRevisionOut]:
        with self.db.read() as s:
            target = self._project(s, project, path)
            return [entries_core.revision_to_out(r) for r in entries_core.list_deleted(s, target)]

    # ------------------------------------------------------------ summary
    def get_summary(
        self, *, project: str | None = None, path: str | os.PathLike[str] | None = None
    ) -> SummaryOut:
        with self.db.read() as s:
            return summaries_core.get_summary(s, self._project(s, project, path))

    def set_summary(
        self,
        update: SummaryUpdate,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        replace: bool = False,
        changed_by: str | None = None,
        expected_revision: int | None = None,
    ) -> tuple[SummaryOut, bool]:
        with self.db.write() as s:
            target = self._project(s, project, path)
            return summaries_core.set_summary(
                s, target, update, replace=replace, changed_by=changed_by, expected_revision=expected_revision
            )

    def set_summary_markdown(
        self,
        markdown: str,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        replace: bool = False,
        changed_by: str | None = None,
    ) -> tuple[SummaryOut, bool]:
        sections = summaries_core.parse_summary_markdown(markdown)
        return self.set_summary(
            SummaryUpdate(**sections), project=project, path=path, replace=replace, changed_by=changed_by
        )

    def summary_history(
        self, *, project: str | None = None, path: str | os.PathLike[str] | None = None
    ) -> list[dict[str, Any]]:
        with self.db.read() as s:
            target = self._project(s, project, path)
            revisions: list[SummaryRevision] = summaries_core.list_summary_revisions(s, target)
            return [
                {
                    "revision": r.revision,
                    "changed_by": r.changed_by,
                    "replaced_at": r.created_at.isoformat(),
                    "data": r.data,
                }
                for r in revisions
            ]

    def restore_summary(
        self,
        revision: int,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        changed_by: str | None = None,
    ) -> SummaryOut:
        with self.db.write() as s:
            target = self._project(s, project, path)
            return summaries_core.restore_summary_revision(s, target, revision, changed_by=changed_by)

    # ------------------------------------------------------------ context
    def context(
        self,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        mode: str = "brief",
        max_tokens: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ContextResult:
        with self.db.read() as s:
            target = self._project(s, project, path)
            return build_context(s, target, mode=mode, max_tokens=max_tokens, page=page, page_size=page_size)

    # ------------------------------------------------------------- search
    def search(
        self,
        query: str,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        all_projects: bool = False,
        kinds: list[str] | None = None,
        types: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_archived: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> Page[SearchHit]:
        with self.db.read() as s:
            project_ids = None if all_projects else [self._project(s, project, path).id]
            hits, total = search_core.search(
                s,
                query,
                project_ids=project_ids,
                kinds=kinds,
                entry_types=types,
                since=since,
                until=until,
                include_archived=include_archived or not all_projects,
                limit=limit,
                offset=offset,
            )
            return Page[SearchHit](items=hits, total=total, limit=limit, offset=offset)

    # ------------------------------------------------------------- assets
    def add_asset(
        self,
        filename: str,
        data: bytes,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        entry: str | None = None,
    ) -> AssetOut:
        with self.db.write() as s:
            target = self._project(s, project, path)
            entry_obj = entries_core.get_entry(s, entry, project=target) if entry else None
            asset = assets_core.add_asset(s, self.settings, target, filename, data, entry=entry_obj)
            return assets_core.to_out(asset)

    def add_asset_file(
        self,
        file_path: str | os.PathLike[str],
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        entry: str | None = None,
        filename: str | None = None,
    ) -> AssetOut:
        source = Path(file_path).expanduser()
        if not source.is_file():
            raise ValidationError(f"Not a file: {source}")
        size = source.stat().st_size
        if size > self.settings.max_upload_bytes:
            raise ValidationError(
                f"File is too large ({size} bytes; limit {self.settings.max_upload_bytes})",
                details={"limit": self.settings.max_upload_bytes},
            )
        return self.add_asset(
            filename or source.name, source.read_bytes(), project=project, path=path, entry=entry
        )

    def get_asset(self, asset_id: str) -> tuple[AssetOut, Path]:
        with self.db.read() as s:
            asset = assets_core.get_asset(s, asset_id)
            return assets_core.to_out(asset), assets_core.asset_path(self.settings, asset)

    def list_assets(
        self,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        entry: str | None = None,
    ) -> list[AssetOut]:
        with self.db.read() as s:
            target = self._project(s, project, path)
            entry_id = entries_core.get_entry(s, entry, project=target).id if entry else None
            return [
                assets_core.to_out(a)
                for a in assets_core.list_assets(s, project_id=target.id, entry_id=entry_id)
            ]

    def gc_assets(
        self,
        *,
        apply: bool = False,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        grace: timedelta = assets_core.GC_GRACE,
    ) -> list[AssetOut]:
        with self.db.write() as s:
            project_id = self._project(s, project, path).id if (project or path is not None) else None
            orphans = assets_core.find_unreferenced(s, project_id=project_id, grace=grace)
            result = [assets_core.to_out(a) for a in orphans]
            if apply:
                for asset in orphans:
                    assets_core.delete_asset(s, self.settings, asset)
            return result

    # ---------------------------------------------------------- dashboard
    def dashboard(self, *, recent: int = 10) -> dict[str, Any]:
        with self.db.read() as s:
            projects = projects_core.list_projects(s)
            recent_entries, total = entries_core.list_entries(
                s,
                project_ids=[p.id for p, _ in projects],
                order="desc",
                sort="created_at",
                limit=recent,
            )
            names = {p.id: p.name for p, _ in projects}
            summaries = []
            for p, _ in projects:
                summary = summaries_core.get_summary(s, p)
                if summary.updated_at:
                    summaries.append(
                        {
                            "project_id": p.id,
                            "project_name": p.name,
                            "updated_at": summary.updated_at,
                            "updated_by": summary.updated_by,
                            "excerpt": excerpt(summary.current_state or summary.overview, 200),
                        }
                    )
            summaries.sort(key=lambda x: x["updated_at"], reverse=True)
            return {
                "projects": [projects_core.to_out(p, n).model_dump(mode="json") for p, n in projects],
                "recent_entries": [
                    {
                        **entries_core.to_out(e, include_content=False).model_dump(mode="json"),
                        "project_name": names.get(e.project_id),
                    }
                    for e in recent_entries
                ],
                "recent_summaries": [
                    {**x, "updated_at": x["updated_at"].isoformat()} for x in summaries[:recent]
                ],
                "type_counts": entries_core.type_counts(s),
                "total_entries": total,
            }
