"""MCP server (official MCPServer, stdio) exposing project memory to agents.

The server process' working directory says nothing about the calling agent's
workspace, so every project-scoped tool takes either ``project`` (id, id
prefix or name) or ``workspace_path`` (absolute path inside the project).

Errors are returned as MCP tool errors whose text is JSON:
``{"error": {"code": "...", "message": "...", "details": {...}}}``.
"""

# No `from __future__ import annotations`: MCPServer resolves the annotations of
# the wrapped tool functions at registration time.

import base64
import binascii
import functools
import json
import os
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from pydantic import Field
from pydantic import ValidationError as PydanticValidationError

from ohmypm import __version__
from ohmypm.core.dates import parse_when
from ohmypm.core.errors import OhmypmError, ValidationError
from ohmypm.core.schemas import BUILTIN_ENTRY_TYPES, EntryCreate, EntryUpdate, SummaryUpdate
from ohmypm.core.service import MemoryService
from ohmypm.core.summaries import render_summary_markdown

SERVER_INSTRUCTIONS = """\
ohmypm is the local project memory (development records + project summary).
Pass `workspace_path` (your absolute working directory) or `project` to every
project tool - never rely on the server's own directory.
Start with pm_get_status, then pm_get_context. Record only information with
lasting value (milestones, non-trivial issues, decisions, durable knowledge,
artifact usage) via pm_add_entry; never store secrets. Update the summary
with pm_update_summary when the project state changed meaningfully.
Write readable Markdown in the user's language. For longer, multi-topic records,
use headings and focused bullet points; separate paragraphs with blank lines and
mark paths/commands with backticks. Keep facts, failed attempts and uncertainty intact.
Do not register projects unless the user asks (use the `ohmypm register` CLI).
"""

ProjectArg = Annotated[
    str | None,
    Field(description="Project id, id prefix or exact name. Alternative to workspace_path."),
]
WorkspaceArg = Annotated[
    str | None,
    Field(description="Absolute path of the agent's workspace (any directory inside the project)."),
]
EntryRefArg = Annotated[str, Field(description="Entry sequence number ('12' or '#12') or entry id.")]
EntryType = Annotated[
    str,
    Field(description="Entry type: " + ", ".join(f"{k} ({v})" for k, v in BUILTIN_ENTRY_TYPES.items())),
]
Status = Literal["open", "resolved", "obsolete"]


def _error(code: str, message: str, details: dict[str, Any] | None = None) -> ToolError:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return ToolError(json.dumps({"error": payload}, ensure_ascii=False))


def _pydantic_problems(exc: PydanticValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg'].removeprefix('Value error, ')}"
        for e in exc.errors()
    )


class _OhmypmServer(MCPServer):
    """Preserve the documented JSON error contract across SDK validation."""

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        try:
            return await super().call_tool(name, arguments, context)
        except UnexpectedToolError:
            raise
        except ToolError as exc:
            cause = exc.__cause__
            if isinstance(cause, PydanticValidationError):
                raise _error("validation_error", _pydantic_problems(cause)) from None
            if isinstance(cause, ToolError):
                raise cause from None
            raise


def _tool_errors[F: Callable[..., Any]](fn: F) -> F:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except OhmypmError as exc:
            raise _error(exc.code, exc.message, exc.details) from None
        except PydanticValidationError as exc:
            raise _error("validation_error", _pydantic_problems(exc)) from None

    return wrapper  # type: ignore[return-value]


def _scope(project: str | None, workspace_path: str | None) -> dict[str, Any]:
    if project:
        return {"project": project}
    if workspace_path:
        if not os.path.isabs(os.path.expanduser(workspace_path)):
            raise ValidationError("workspace_path must be an absolute path")
        return {"path": os.path.expanduser(workspace_path)}
    raise ValidationError("Pass `workspace_path` (absolute path of your workspace) or `project`")


def build_server(service: MemoryService | None = None) -> MCPServer:
    service = service or MemoryService()
    mcp = _OhmypmServer("ohmypm", instructions=SERVER_INSTRUCTIONS, version=__version__)
    read_only = {"readOnlyHint": True, "openWorldHint": False}
    writes = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}

    @mcp.tool(annotations=read_only)
    @_tool_errors
    def pm_get_status(
        workspace_path: Annotated[str, Field(description="Absolute path of the agent's current workspace.")],
    ) -> dict[str, Any]:
        """Check whether a workspace belongs to a registered ohmypm project (call this first)."""
        _scope(None, workspace_path)
        return service.status(os.path.expanduser(workspace_path))

    @mcp.tool(annotations=read_only)
    @_tool_errors
    def pm_list_projects(
        include_archived: Annotated[bool, Field(description="Include unregistered projects.")] = False,
    ) -> dict[str, Any]:
        """List registered projects, most recently active first."""
        projects = service.list_projects(include_archived=include_archived)
        return {"projects": [p.model_dump(mode="json") for p in projects]}

    @mcp.tool(annotations=read_only)
    @_tool_errors
    def pm_get_project(project: ProjectArg = None, workspace_path: WorkspaceArg = None) -> dict[str, Any]:
        """Get project details (name, root path, description, record count)."""
        return service.get_project(**_scope(project, workspace_path)).model_dump(mode="json")

    @mcp.tool(annotations=read_only)
    @_tool_errors
    def pm_get_context(
        project: ProjectArg = None,
        workspace_path: WorkspaceArg = None,
        mode: Annotated[
            Literal["brief", "standard", "full"],
            Field(description="brief: session start; standard: more records; full: paginated history."),
        ] = "brief",
        max_tokens: Annotated[
            int | None, Field(description="Token budget (200-200000).", ge=200, le=200_000)
        ] = None,
        page: Annotated[int, Field(description="Page for full mode.", ge=1)] = 1,
        page_size: Annotated[int, Field(description="Records per page for full mode.", ge=1, le=200)] = 20,
        output: Annotated[
            Literal["markdown", "json"],
            Field(description="markdown: compact text; json: structured sections plus markdown."),
        ] = "markdown",
    ) -> dict[str, Any]:
        """Deterministic project context: summary, open issues, recent important records, next steps."""
        result = service.context(
            mode=mode,
            max_tokens=max_tokens,
            page=page,
            page_size=page_size,
            **_scope(project, workspace_path),
        )
        if output == "json":
            return result.model_dump(mode="json")
        return {
            "project_id": result.project.id,
            "mode": result.mode,
            "truncated": result.budget.truncated,
            "used_tokens": result.budget.used_tokens,
            "pagination": result.pagination.model_dump() if result.pagination else None,
            "markdown": result.markdown,
        }

    @mcp.tool(annotations=read_only)
    @_tool_errors
    def pm_get_summary(project: ProjectArg = None, workspace_path: WorkspaceArg = None) -> dict[str, Any]:
        """Get the project summary (structured sections and an equivalent Markdown document)."""
        summary = service.get_summary(**_scope(project, workspace_path))
        return {**summary.model_dump(mode="json"), "markdown": render_summary_markdown(summary)}

    @mcp.tool(annotations=writes)
    @_tool_errors
    def pm_update_summary(
        project: ProjectArg = None,
        workspace_path: WorkspaceArg = None,
        markdown: Annotated[
            str | None,
            Field(
                description="Summary document with '## Overview', '## Architecture', '## Current State', "
                "'## Important Decisions', '## Known Issues', '## Next Steps' headings."
            ),
        ] = None,
        overview: Annotated[str | None, Field(description="Project goal and introduction.")] = None,
        architecture: Annotated[str | None, Field(description="Main technical architecture.")] = None,
        current_state: Annotated[str | None, Field(description="Completed work and current status.")] = None,
        important_decisions: Annotated[str | None, Field(description="Settled technical decisions.")] = None,
        known_issues: Annotated[str | None, Field(description="Unresolved problems.")] = None,
        next_steps: Annotated[str | None, Field(description="Recommended next steps.")] = None,
        replace: Annotated[bool, Field(description="Clear sections that are not provided.")] = False,
        author: Annotated[str | None, Field(description="Who updates the summary (agent name).")] = None,
    ) -> dict[str, Any]:
        """Update the project summary. Only provided sections change unless replace=true. Old versions are kept."""
        scope = _scope(project, workspace_path)
        sections = SummaryUpdate(
            overview=overview,
            architecture=architecture,
            current_state=current_state,
            important_decisions=important_decisions,
            known_issues=known_issues,
            next_steps=next_steps,
        )
        if markdown is not None:
            from ohmypm.core.summaries import parse_summary_markdown

            parsed = parse_summary_markdown(markdown)
            sections = SummaryUpdate(**{**parsed, **sections.provided()})
        if not sections.provided() and not replace:
            raise ValidationError("Provide `markdown` or at least one section")
        summary, changed = service.set_summary(sections, replace=replace, changed_by=author, **scope)
        return {"changed": changed, "summary": summary.model_dump(mode="json")}

    @mcp.tool(annotations=writes)
    @_tool_errors
    def pm_add_entry(
        title: Annotated[str, Field(description="Short, specific title.")],
        type: EntryType = "note",
        content: Annotated[
            str,
            Field(
                description="Markdown body in the user's language. Use headings and focused bullets for longer, multi-topic records, blank lines between paragraphs, and backticks for paths/commands. Preserve facts and uncertainty."
            ),
        ] = "",
        project: ProjectArg = None,
        workspace_path: WorkspaceArg = None,
        status: Annotated[Status | None, Field(description="Issues default to 'open'.")] = None,
        author: Annotated[str | None, Field(description="Agent or user name.")] = None,
        metadata: Annotated[
            dict[str, Any] | None,
            Field(description='Optional extra fields, e.g. {"confidence": "hypothesis", "files": [...]}.'),
        ] = None,
    ) -> dict[str, Any]:
        """Append a development record (milestone, issue, decision, knowledge, artifact or note)."""
        entry = service.add_entry(
            EntryCreate(
                type=type,
                title=title,
                content=content,
                status=status,
                author=author,
                source="mcp",
                metadata=metadata or {},
            ),
            **_scope(project, workspace_path),
        )
        return entry.model_dump(mode="json")

    @mcp.tool(annotations=read_only)
    @_tool_errors
    def pm_list_entries(
        project: ProjectArg = None,
        workspace_path: WorkspaceArg = None,
        types: Annotated[list[str] | None, Field(description="Filter by entry types.")] = None,
        statuses: Annotated[
            list[str] | None, Field(description="Filter by status (open/resolved/obsolete/none).")
        ] = None,
        query: Annotated[str | None, Field(description="Substring filter on title and body.")] = None,
        since: Annotated[str | None, Field(description="ISO date/time or relative (7d, 12h).")] = None,
        until: Annotated[str | None, Field(description="ISO date/time (inclusive).")] = None,
        order: Annotated[Literal["asc", "desc"], Field(description="Timeline order.")] = "desc",
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
        include_content: Annotated[bool, Field(description="Return full Markdown bodies.")] = False,
    ) -> dict[str, Any]:
        """List records (newest first by default) with excerpts."""
        page = service.list_entries(
            types=types,
            statuses=statuses,
            query=query,
            since=parse_when(since),
            until=parse_when(until, end_of_day=True),
            order=order,
            limit=limit,
            offset=offset,
            include_content=include_content,
            **_scope(project, workspace_path),
        )
        return page.model_dump(mode="json")

    @mcp.tool(annotations=read_only)
    @_tool_errors
    def pm_get_entry(
        entry: EntryRefArg, project: ProjectArg = None, workspace_path: WorkspaceArg = None
    ) -> dict[str, Any]:
        """Get one record with its full Markdown body."""
        scope = _scope(project, workspace_path) if (project or workspace_path) else {}
        return service.get_entry(entry, **scope).model_dump(mode="json")

    @mcp.tool(annotations=writes)
    @_tool_errors
    def pm_update_entry(
        entry: EntryRefArg,
        project: ProjectArg = None,
        workspace_path: WorkspaceArg = None,
        title: Annotated[str | None, Field(description="New title.")] = None,
        type: Annotated[str | None, Field(description="New type.")] = None,
        content: Annotated[
            str | None,
            Field(
                description="Replace the Markdown body. Use headings and focused bullets for longer, multi-topic records, blank lines between paragraphs, and backticks for paths/commands. Preserve facts and uncertainty."
            ),
        ] = None,
        append_content: Annotated[
            str | None,
            Field(
                description="Append Markdown as a separate paragraph or section. Use focused bullets for multiple points; preserve facts and uncertainty."
            ),
        ] = None,
        status: Annotated[Status | None, Field(description="New status, e.g. 'resolved'.")] = None,
        metadata: Annotated[
            dict[str, Any] | None, Field(description="Metadata keys to set (merged).")
        ] = None,
        author: Annotated[str | None, Field(description="Who makes the change.")] = None,
    ) -> dict[str, Any]:
        """Edit a record (e.g. resolve an issue). The previous version is kept as a revision."""
        if content is not None and append_content is not None:
            raise ValidationError("Use either content or append_content")
        scope = _scope(project, workspace_path) if (project or workspace_path) else {}
        current = service.get_entry(entry, **scope)
        body = content
        if append_content is not None:
            body = (current.content or "").rstrip("\n") + "\n\n" + append_content
        meta = {**current.metadata, **metadata} if metadata else None
        updated, changed = service.update_entry(
            current.id,
            EntryUpdate(title=title, type=type, content=body, status=status, metadata=meta),
            changed_by=author,
        )
        return {"changed": changed, "entry": updated.model_dump(mode="json")}

    @mcp.tool(annotations=read_only)
    @_tool_errors
    def pm_search(
        query: Annotated[
            str, Field(description='Words or "quoted phrases"; all must match. Chinese supported.')
        ],
        project: ProjectArg = None,
        workspace_path: WorkspaceArg = None,
        all_projects: Annotated[bool, Field(description="Search every project instead of one.")] = False,
        types: Annotated[list[str] | None, Field(description="Entry type filter.")] = None,
        kinds: Annotated[
            list[Literal["entry", "summary", "project"]] | None, Field(description="What to search.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 10,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        """Full-text search over records, summaries and projects."""
        scope = {} if all_projects else _scope(project, workspace_path)
        page = service.search(
            query, all_projects=all_projects, types=types, kinds=kinds, limit=limit, offset=offset, **scope
        )
        return page.model_dump(mode="json")

    @mcp.tool(annotations=writes)
    @_tool_errors
    def pm_register_asset(
        project: ProjectArg = None,
        workspace_path: WorkspaceArg = None,
        file_path: Annotated[
            str | None, Field(description="Absolute path of a local image/text file.")
        ] = None,
        content_base64: Annotated[
            str | None, Field(description="File content as base64 (alternative).")
        ] = None,
        filename: Annotated[
            str | None, Field(description="File name (required with content_base64).")
        ] = None,
        entry: Annotated[str | None, Field(description="Attach to this record (sequence or id).")] = None,
    ) -> dict[str, Any]:
        """Store an image (PNG/JPEG/WebP/GIF/SVG) or text file; returns a Markdown reference for a record."""
        scope = _scope(project, workspace_path)
        if (file_path is None) == (content_base64 is None):
            raise ValidationError("Provide exactly one of file_path or content_base64")
        if file_path is not None:
            if not os.path.isabs(os.path.expanduser(file_path)):
                raise ValidationError("file_path must be absolute")
            asset = service.add_asset_file(file_path, entry=entry, filename=filename, **scope)
        else:
            if not filename:
                raise ValidationError("filename is required with content_base64")
            try:
                data = base64.b64decode(content_base64 or "", validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValidationError(f"Invalid base64 content: {exc}") from exc
            asset = service.add_asset(filename, data, entry=entry, **scope)
        return asset.model_dump(mode="json")

    return mcp


def run_stdio(service: MemoryService | None = None) -> None:
    build_server(service).run(transport="stdio")


def main() -> None:
    run_stdio()


if __name__ == "__main__":
    main()
