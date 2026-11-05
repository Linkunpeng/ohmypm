"""``ohmypm log``: create, list, show, edit and delete entries."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ohmypm.cli.common import (
    AuthorOpt,
    CwdOpt,
    JsonOpt,
    ProjectOpt,
    confirm_or_fail,
    emit_json,
    get_service,
    local_time,
    out,
    parse_meta,
    parse_when,
    read_text_input,
    workspace,
)
from ohmypm.core.errors import ValidationError
from ohmypm.core.schemas import BUILTIN_ENTRY_TYPES, EntryCreate, EntryOut, EntryUpdate

log_app = typer.Typer(
    help="Development records (entries): add, list, show, edit, delete.", no_args_is_help=True
)

TYPES_HELP = "Entry type: " + ", ".join(BUILTIN_ENTRY_TYPES) + "."
StatusOpt = Annotated[
    str | None,
    typer.Option("--status", "-s", help="open | resolved | obsolete (issues default to open)."),
]
ContentOpt = Annotated[str | None, typer.Option("--content", "-c", help="Markdown body.")]
FileOpt = Annotated[
    Path | None, typer.Option("--file", "-f", help="Read the Markdown body from a file ('-' = stdin).")
]
StdinOpt = Annotated[bool, typer.Option("--stdin", help="Read the Markdown body from standard input.")]
MetaOpt = Annotated[
    list[str] | None,
    typer.Option("--meta", "-m", help="Metadata key=value (JSON values allowed). Repeatable."),
]


def _scope(project: str | None, cwd: Path | None) -> dict:
    return {"project": project, "path": None if project else workspace(cwd)}


def entry_line(e: EntryOut, *, project_name: str | None = None) -> str:
    tag = e.type + (f"/{e.status}" if e.status else "")
    who = f"  ({e.author})" if e.author else ""
    prefix = f"{project_name}  " if project_name else ""
    return f"{prefix}#{e.sequence:<4} {local_time(e.created_at)}  [{tag}]  {e.title}{who}"


def print_entry(e: EntryOut) -> None:
    tag = e.type + (f" · {e.status}" if e.status else "")
    out(f"#{e.sequence} [{tag}] {e.title}")
    meta = [f"created {local_time(e.created_at)}"]
    if e.updated_at != e.created_at:
        meta.append(f"updated {local_time(e.updated_at)} (rev {e.revision})")
    if e.author:
        meta.append(f"by {e.author}")
    if e.source:
        meta.append(f"via {e.source}")
    out("  ".join(meta))
    out(f"id: {e.id}")
    if e.metadata:
        out("metadata: " + ", ".join(f"{k}={v}" for k, v in e.metadata.items()))
    out("")
    out(e.content or "")


@log_app.command("add")
def log_add(
    title: Annotated[str, typer.Option("--title", "-t", help="Short, specific title.")],
    type_: Annotated[str, typer.Option("--type", "-T", help=TYPES_HELP)] = "note",
    content: ContentOpt = None,
    file: FileOpt = None,
    stdin: StdinOpt = False,
    status: StatusOpt = None,
    author: AuthorOpt = None,
    meta: MetaOpt = None,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Add an entry to the current project.

    Examples:

      ohmypm log add --type milestone --title "Camera driver done" --content "V4L2 capture works."

      cat issue.md | ohmypm log add --type issue --title "OpenCV link error" --stdin
    """
    body = read_text_input(content, file, stdin) or ""
    data = EntryCreate(
        type=type_,
        title=title,
        content=body,
        status=status,
        author=author,
        source="cli",
        metadata=parse_meta(meta),
    )
    entry = get_service().add_entry(data, **_scope(project, cwd))
    if json_:
        emit_json(entry)
        return
    out(f"Added #{entry.sequence} [{entry.type}] {entry.title}  (id {entry.id})")


@log_app.command("list")
def log_list(
    type_: Annotated[
        list[str] | None, typer.Option("--type", "-T", help="Filter by type. Repeatable.")
    ] = None,
    status: Annotated[
        list[str] | None, typer.Option("--status", "-s", help="Filter by status (or 'none').")
    ] = None,
    query: Annotated[
        str | None, typer.Option("--query", "-q", help="Substring filter on title and body.")
    ] = None,
    since: Annotated[str | None, typer.Option("--since", help="e.g. 2026-11-01, today, 7d, 12h.")] = None,
    until: Annotated[str | None, typer.Option("--until", help="e.g. 2026-11-04 (inclusive).")] = None,
    author: Annotated[str | None, typer.Option("--by", help="Only entries by this author.")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum number of entries.")] = 30,
    offset: Annotated[int, typer.Option("--offset", help="Skip this many entries.")] = 0,
    reverse: Annotated[bool, typer.Option("--reverse", "-r", help="Newest first.")] = False,
    full: Annotated[
        bool, typer.Option("--full", help="Include the full Markdown body in JSON output.")
    ] = False,
    all_projects: Annotated[bool, typer.Option("--all-projects", help="List across all projects.")] = False,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """List entries in timeline order (oldest first; --reverse for newest first).

    Without --reverse and --offset, the most recent LIMIT entries are shown.
    """
    service = get_service()
    common = dict(
        types=type_,
        statuses=status,
        query=query,
        since=parse_when(since),
        until=parse_when(until, end_of_day=True),
        author=author,
        include_content=full,
        all_projects=all_projects,
        **({} if all_projects else _scope(project, cwd)),
    )
    if reverse or offset:
        page = service.list_entries(order="desc" if reverse else "asc", limit=limit, offset=offset, **common)
        items = page.items
    else:
        # Default: the latest `limit` entries, displayed chronologically.
        page = service.list_entries(order="desc", limit=limit, **common)
        items = list(reversed(page.items))
    if json_:
        emit_json({"items": items, "total": page.total, "limit": limit, "offset": offset})
        return
    if not items:
        out("No entries.")
        return
    names = {}
    if all_projects:
        names = {p.id: p.name for p in service.list_projects(include_archived=True)}
    for e in items:
        out(entry_line(e, project_name=names.get(e.project_id)))
    if page.total > len(items):
        out(f"({len(items)} of {page.total} shown; use --limit/--offset)")


@log_app.command("show")
def log_show(
    ref: Annotated[str, typer.Argument(help="Entry sequence (12 or #12) or id.")],
    raw: Annotated[bool, typer.Option("--raw", help="Print only the Markdown body.")] = False,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Show one entry."""
    entry = get_service().get_entry(ref, **_scope(project, cwd))
    if json_:
        emit_json(entry)
    elif raw:
        out(entry.content or "")
    else:
        print_entry(entry)


@log_app.command("edit")
def log_edit(
    ref: Annotated[str, typer.Argument(help="Entry sequence (12 or #12) or id.")],
    title: Annotated[str | None, typer.Option("--title", "-t", help="New title.")] = None,
    type_: Annotated[str | None, typer.Option("--type", "-T", help="New type.")] = None,
    content: ContentOpt = None,
    file: FileOpt = None,
    stdin: StdinOpt = False,
    append: Annotated[
        bool, typer.Option("--append", help="Append the given body instead of replacing it.")
    ] = False,
    status: StatusOpt = None,
    clear_status: Annotated[bool, typer.Option("--clear-status", help="Remove the status.")] = False,
    meta: MetaOpt = None,
    editor: Annotated[bool, typer.Option("--editor", "-e", help="Edit the body in $EDITOR.")] = False,
    author: AuthorOpt = None,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Edit an entry. The previous version is kept (see `ohmypm log history`)."""
    service = get_service()
    scope = _scope(project, cwd)
    body = read_text_input(content, file, stdin)
    current = service.get_entry(ref, **scope)
    if editor:
        if body is not None:
            raise ValidationError("--editor cannot be combined with --content/--file/--stdin")
        edited = typer.edit(current.content or "", extension=".md")
        body = edited if edited is not None else None
    if append and body is not None:
        body = (current.content or "").rstrip("\n") + "\n\n" + body
    metadata = None
    if meta:
        metadata = {**current.metadata, **parse_meta(meta)}
    changes = EntryUpdate(
        title=title, type=type_, content=body, status=status, clear_status=clear_status, metadata=metadata
    )
    entry, changed = service.update_entry(current.id, changes, changed_by=author)
    if json_:
        emit_json({"changed": changed, "entry": entry})
        return
    out(f"Updated #{entry.sequence} (revision {entry.revision})" if changed else "No changes.")


@log_app.command("delete")
def log_delete(
    ref: Annotated[str, typer.Argument(help="Entry sequence (12 or #12) or id.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    author: AuthorOpt = None,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Delete an entry (a recoverable copy is kept, see `ohmypm log deleted`)."""
    service = get_service()
    entry = service.get_entry(ref, **_scope(project, cwd))
    confirm_or_fail(f"Delete #{entry.sequence} '{entry.title}'?", yes)
    service.delete_entry(entry.id, changed_by=author)
    if json_:
        emit_json({"deleted": True, "entry": entry})
        return
    out(f"Deleted #{entry.sequence} '{entry.title}'")


@log_app.command("history")
def log_history(
    ref: Annotated[str, typer.Argument(help="Entry sequence or id.")],
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Show previous revisions of an entry."""
    revisions = get_service().entry_history(ref, **_scope(project, cwd))
    if json_:
        emit_json(revisions)
        return
    if not revisions:
        out("No previous revisions.")
    for r in revisions:
        out(
            f"rev {r.revision}  replaced {local_time(r.created_at)}  [{r.type}] {r.title}"
            + (f"  by {r.changed_by}" if r.changed_by else "")
        )


@log_app.command("restore")
def log_restore(
    ref: Annotated[str, typer.Argument(help="Entry sequence or id.")],
    revision: Annotated[int, typer.Option("--revision", "-r", help="Revision number to restore.")],
    author: AuthorOpt = None,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Restore an entry to a previous revision (creates a new revision)."""
    entry = get_service().restore_entry(ref, revision, changed_by=author, **_scope(project, cwd))
    if json_:
        emit_json(entry)
        return
    out(f"Restored #{entry.sequence} to the content of revision {revision} (now revision {entry.revision})")


@log_app.command("deleted")
def log_deleted(project: ProjectOpt = None, cwd: CwdOpt = None, json_: JsonOpt = False) -> None:
    """List deleted entries whose last version is still recoverable."""
    items = get_service().deleted_entries(**_scope(project, cwd))
    if json_:
        emit_json(items)
        return
    if not items:
        out("No deleted entries.")
    for r in items:
        out(
            f"#{r.sequence:<4} deleted {local_time(r.created_at)}  [{r.type}] {r.title}  (entry id {r.entry_id})"
        )
