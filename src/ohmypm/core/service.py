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

from ohmypm.config import Settings, load_settings, normalize_author
from ohmypm.core import assets as assets_core
from ohmypm.core import context as context_core
from ohmypm.core import entries as entries_core
from ohmypm.core import gitinfo
from ohmypm.core import links as links_core
from ohmypm.core import projects as projects_core
from ohmypm.core import search as search_core
from ohmypm.core import similar as similar_core
from ohmypm.core import summaries as summaries_core
from ohmypm.core.context import ContextOptions, ContextResult, build_context
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
    SimilarEntry,
    SummaryOut,
    SummaryUpdate,
    clean_tags,
)
from ohmypm.core.text import excerpt
from ohmypm.storage.database import Database
from ohmypm.storage.models import Entry, Project, SummaryRevision


class MemoryService:
    def __init__(self, settings: Settings | None = None, db: Database | None = None) -> None:
        self.settings = settings or load_settings()
        self.db = db or Database(self.settings)

    # ------------------------------------------------------------ helpers
    def _author(self, name: str | None) -> str | None:
        return normalize_author(name, self.settings.author_aliases)

    @staticmethod
    def _detail(session: Session, entry: Entry) -> EntryOut:
        """``EntryOut`` with outgoing links and backlinks."""
        session.flush()
        outgoing, incoming = links_core.links_for(session, [entry.id])
        out = entries_core.to_out(entry)
        out.links = outgoing.get(entry.id, [])
        out.backlinks = incoming.get(entry.id, [])
        return out

    def _project(self, session: Session, project: str | None, path: str | os.PathLike[str] | None) -> Project:
        if project:
            return projects_core.get_project(session, project)
        if path is not None:
            return projects_core.require_project_for_path(session, path)
        raise ValidationError("Specify a project (id or name) or a workspace path")

    def _git_stamp(self, project: str | None, path: str | os.PathLike[str] | None) -> dict[str, Any] | None:
        """HEAD of the project's root. Runs before the write transaction so Git never holds the lock."""
        if not self.settings.git_stamps:
            return None
        with self.db.read() as s:
            root = self._project(s, project, path).root_path
        return gitinfo.head(root)

    def _summary_drift(self, session: Session, target: Project, summary: SummaryOut) -> dict[str, Any]:
        """How far the project moved since the summary last changed: new records and commits."""
        if summary.updated_at is None:
            return {"records_since_summary": None, "summary_commits_behind": None}
        behind = None
        if summary.git and self.settings.git_stamps:
            behind = gitinfo.commits_since(target.root_path, summary.git["commit"])
        return {
            "records_since_summary": entries_core.count_created_since(session, target, summary.updated_at),
            "summary_commits_behind": behind,
        }

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
            stale_days = context_core.resolve_options(self.settings, project).stale_issue_days
            now = datetime.now().astimezone()
            stale_total = sum(
                1
                for e in context_core.open_issues(s, project)
                if context_core.is_stale_issue(e, stale_days, now)
            )
            return {
                "registered": True,
                "path": resolved,
                "relative_path": os.path.relpath(resolved, project.root_path),
                "project": projects_core.to_out(project, count).model_dump(mode="json"),
                "summary_exists": not summary.is_empty,
                "summary_updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
                "summary_git": summary.git,
                **self._summary_drift(s, project, summary),
                "open_issues": open_total,
                "stale_open_issues": stale_total,
                "stale_issue_days": stale_days,
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
        author = self._author(data.author) or self.settings.default_author
        updates: dict[str, Any] = {"author": author}
        if "git" not in data.metadata and (stamp := self._git_stamp(project, path)):
            updates["metadata"] = {**data.metadata, "git": stamp}
        data = data.model_copy(update=updates)
        with self.db.write() as s:
            target = self._project(s, project, path)
            entry = entries_core.add_entry(s, target, data, allowed_types=self.settings.entry_types)
            links_core.sync_mentions(s, entry)
            for link in data.links:
                links_core.add_link(s, entry, link.target, link.kind, changed_by=author)
            return self._detail(s, entry)

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
        tags: list[str] | None = None,
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
                author=self._author(author),
                tags=tags,
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
            return self._detail(s, entries_core.get_entry(s, ref, project=target))

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
            changed_by = self._author(changed_by)
            entry, changed = entries_core.update_entry(
                s,
                entry,
                changes,
                changed_by=changed_by,
                allowed_types=self.settings.entry_types,
                expected_revision=expected_revision,
            )
            if changes.content is not None:
                links_core.sync_mentions(s, entry)
            for ref_ in changes.remove_links:
                changed |= links_core.remove_links(s, entry, ref_) > 0
            for link in changes.add_links:
                changed |= links_core.add_link(s, entry, link.target, link.kind, changed_by=changed_by)
            return self._detail(s, entry), changed

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
            entries_core.delete_entry(s, entry, changed_by=self._author(changed_by))
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
            entry = entries_core.restore_revision(s, entry, revision, changed_by=self._author(changed_by))
            links_core.sync_mentions(s, entry)
            return self._detail(s, entry)

    def deleted_entries(
        self, *, project: str | None = None, path: str | os.PathLike[str] | None = None
    ) -> list[EntryRevisionOut]:
        with self.db.read() as s:
            target = self._project(s, project, path)
            return [entries_core.revision_to_out(r) for r in entries_core.list_deleted(s, target)]

    def similar_entries(
        self,
        ref: str | None = None,
        *,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        types: list[str] | None = None,
        statuses: list[str] | None = None,
        include_obsolete: bool = False,
        limit: int = 5,
        min_score: float = similar_core.DEFAULT_MIN_SCORE,
    ) -> list[SimilarEntry]:
        """Records similar to entry ``ref`` or to a draft (title / content / tags).

        Given values override the ones of ``ref``. Use it before adding an
        issue to find one that should be extended instead.
        """
        if not 1 <= limit <= 100 or not 0 <= min_score <= 1:
            raise ValidationError("limit must be 1-100 and min_score 0-1")
        with self.db.read() as s:
            target = self._project(s, project, path) if (project or path is not None) else None
            source = entries_core.get_entry(s, ref, project=target) if ref else None
            if source is not None:
                target = source.project
                title = source.title if title is None else title
                content = source.content if content is None else content
                tags = list(source.tags or []) if tags is None else tags
            if target is None:
                raise ValidationError("Specify a project (id or name) or a workspace path")
            if not (title or "").strip() and not (content or "").strip():
                raise ValidationError("Give a record or a title / content to compare")
            matches = similar_core.find_similar(
                s,
                target,
                title=title or "",
                content=content or "",
                tags=clean_tags(tags or []),
                exclude=source,
                types=types,
                statuses=statuses,
                include_obsolete=include_obsolete,
                limit=limit,
                min_score=min_score,
            )
            return [SimilarEntry.model_validate(similar_core.to_out(m)) for m in matches]

    def tags(
        self,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        all_projects: bool = False,
    ) -> list[dict[str, Any]]:
        with self.db.read() as s:
            project_ids = None if all_projects else [self._project(s, project, path).id]
            return [{"tag": tag, "count": n} for tag, n in entries_core.tag_counts(s, project_ids)]

    def authors(
        self,
        *,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
        all_projects: bool = False,
        apply: bool = False,
    ) -> list[dict[str, Any]]:
        """Author names with counts and their normalised form; ``apply`` rewrites them.

        Only the ``author`` field changes: no revision is created and
        ``updated_at`` is kept, so record ages stay meaningful.
        """
        with self.db.write() if apply else self.db.read() as s:
            project_ids = None if all_projects else [self._project(s, project, path).id]
            rows = entries_core.author_counts(s, project_ids)
            result = []
            for author, count in rows:
                normalized = self._author(author)
                if apply and normalized != author:
                    entries_core.rename_author(s, author, normalized, project_ids)
                result.append({"author": author, "count": count, "normalized": normalized})
            return result

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
        stamp = self._git_stamp(project, path)
        with self.db.write() as s:
            target = self._project(s, project, path)
            return summaries_core.set_summary(
                s,
                target,
                update,
                replace=replace,
                changed_by=self._author(changed_by),
                expected_revision=expected_revision,
                git=stamp,
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
        stamp = self._git_stamp(project, path)
        with self.db.write() as s:
            target = self._project(s, project, path)
            return summaries_core.restore_summary_revision(
                s, target, revision, changed_by=self._author(changed_by), git=stamp
            )

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
        tag: str | None = None,
    ) -> ContextResult:
        with self.db.read() as s:
            target = self._project(s, project, path)
            return build_context(
                s,
                target,
                mode=mode,
                max_tokens=max_tokens,
                page=page,
                page_size=page_size,
                options=context_core.resolve_options(self.settings, target),
                tag=tag,
                check_git=self.settings.git_stamps,
            )

    def summary_cut(
        self, *, project: str | None = None, path: str | os.PathLike[str] | None = None
    ) -> list[dict[str, Any]]:
        """Summary sections that the default (brief) context cannot show in full."""
        return self.context(project=project, path=path, mode="brief").stats["summary_sections_cut"]

    def context_settings(
        self, *, project: str | None = None, path: str | os.PathLike[str] | None = None
    ) -> ContextOptions:
        with self.db.read() as s:
            return context_core.resolve_options(self.settings, self._project(s, project, path))

    def update_context_settings(
        self,
        values: dict[str, int | None],
        *,
        reset: bool = False,
        project: str | None = None,
        path: str | os.PathLike[str] | None = None,
    ) -> ContextOptions:
        """Set (or with ``None`` remove) project overrides; ``reset`` removes all first."""
        context_core.validate_overrides(values)
        with self.db.write() as s:
            target = self._project(s, project, path)
            current = {} if reset else context_core.project_overrides(target)
            for key, value in values.items():
                if value is None:
                    current.pop(key, None)
                else:
                    current[key] = value
            meta = dict(target.meta or {})
            if current:
                meta[context_core.PROJECT_SETTINGS_KEY] = current
            else:
                meta.pop(context_core.PROJECT_SETTINGS_KEY, None)
            projects_core.update_project(s, target, metadata=meta)
            return context_core.resolve_options(self.settings, target)

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
        tags: list[str] | None = None,
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
                tags=tags,
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
