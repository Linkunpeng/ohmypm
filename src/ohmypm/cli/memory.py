"""Summary, context and search commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ohmypm.cli.common import (
    AuthorOpt,
    CwdOpt,
    JsonOpt,
    ProjectOpt,
    emit_json,
    err,
    get_service,
    local_time,
    out,
    parse_when,
    read_text_input,
    workspace,
)
from ohmypm.core.errors import ProjectNotRegisteredError, ValidationError
from ohmypm.core.schemas import SummaryUpdate
from ohmypm.core.summaries import SECTION_TITLES, render_summary_markdown, section_key

summary_app = typer.Typer(help="Project summary: the current state of the project.", no_args_is_help=True)

SECTIONS_HELP = "Section: " + ", ".join(SECTION_TITLES) + " (or headings such as 'Next Steps', '下一步')."


def _scope(project: str | None, cwd: Path | None) -> dict:
    return {"project": project, "path": None if project else workspace(cwd)}


def _section(name: str) -> str:
    key = section_key(name)
    if key is None:
        raise ValidationError(f"Unknown summary section '{name}'", details={"allowed": list(SECTION_TITLES)})
    return key


@summary_app.command("show")
def summary_show(
    section: Annotated[str | None, typer.Option("--section", "-s", help=SECTIONS_HELP)] = None,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Print the project summary as Markdown (round-trips with `summary set`)."""
    service = get_service()
    scope = _scope(project, cwd)
    summary = service.get_summary(**scope)
    if json_:
        emit_json(summary)
        return
    if section:
        out(getattr(summary, _section(section)) or "")
        return
    if summary.is_empty:
        out("No summary yet. Create one with `ohmypm summary set --file summary.md`.")
        out("Template:\n")
        out(render_summary_markdown(summary).rstrip())
        return
    name = service.get_project(**scope).name
    out(render_summary_markdown(summary, title=f"{name} — Project Summary").rstrip())
    # Metadata goes to stderr so stdout round-trips through `summary set --stdin`.
    err(
        f"(revision {summary.revision}, updated {local_time(summary.updated_at)}"
        + (f" by {summary.updated_by}" if summary.updated_by else "")
        + ")"
    )


@summary_app.command("set")
def summary_set(
    file: Annotated[
        Path | None, typer.Option("--file", "-f", help="Markdown file with '## Section' headings.")
    ] = None,
    stdin: Annotated[bool, typer.Option("--stdin", help="Read Markdown from standard input.")] = False,
    content: Annotated[str | None, typer.Option("--content", "-c", help="Markdown text.")] = None,
    section: Annotated[
        str | None,
        typer.Option(
            "--section", "-s", help="Set only this section; the input is its body. " + SECTIONS_HELP
        ),
    ] = None,
    replace: Annotated[
        bool, typer.Option("--replace", help="Clear sections missing from the input (default: keep them).")
    ] = False,
    author: AuthorOpt = None,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Update the project summary.

    The input is a Markdown document whose '## ' headings name sections
    (Overview, Architecture, Current State, Important Decisions, Known Issues,
    Next Steps). Only sections present in the input change unless --replace is
    given. Previous versions are kept (`ohmypm summary history`).
    """
    text = read_text_input(content, file, stdin)
    if text is None:
        raise ValidationError("Provide the summary with --file, --stdin or --content")
    service = get_service()
    scope = _scope(project, cwd)
    if section:
        summary, changed = service.set_summary(
            SummaryUpdate(**{_section(section): text}), replace=replace, changed_by=author, **scope
        )
    else:
        summary, changed = service.set_summary_markdown(text, replace=replace, changed_by=author, **scope)
    if json_:
        emit_json({"changed": changed, "summary": summary})
        return
    out(f"Summary updated (revision {summary.revision})." if changed else "Summary unchanged.")


@summary_app.command("history")
def summary_history(project: ProjectOpt = None, cwd: CwdOpt = None, json_: JsonOpt = False) -> None:
    """List previous summary revisions."""
    items = get_service().summary_history(**_scope(project, cwd))
    if json_:
        emit_json(items)
        return
    if not items:
        out("No previous revisions.")
    for item in items:
        out(
            f"rev {item['revision']}  replaced {local_time(item['replaced_at'])}"
            + (f"  by {item['changed_by']}" if item["changed_by"] else "")
        )


@summary_app.command("restore")
def summary_restore(
    revision: Annotated[int, typer.Argument(help="Revision number to restore.")],
    author: AuthorOpt = None,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Restore a previous summary revision."""
    summary = get_service().restore_summary(revision, changed_by=author, **_scope(project, cwd))
    if json_:
        emit_json(summary)
        return
    out(f"Restored summary revision {revision} (now revision {summary.revision}).")


def context(
    mode: Annotated[str, typer.Option("--mode", "-m", help="brief | standard | full")] = "brief",
    max_tokens: Annotated[
        int | None, typer.Option("--max-tokens", help="Token budget (default: 3000 / 8000 / 20000 by mode).")
    ] = None,
    page: Annotated[int, typer.Option("--page", help="Page of records (full mode).")] = 1,
    page_size: Annotated[int, typer.Option("--page-size", help="Records per page (full mode).")] = 20,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Print project context for an agent: summary, open issues, recent records.

    Deterministic (no AI); respects a token budget and marks truncated text.
    """
    result = get_service().context(
        mode=mode, max_tokens=max_tokens, page=page, page_size=page_size, **_scope(project, cwd)
    )
    if json_:
        emit_json(result)
        return
    out(result.markdown.rstrip())


def search(
    query: Annotated[str, typer.Argument(help='Words or "quoted phrases"; all must match.')],
    all_projects: Annotated[bool, typer.Option("--all", "-a", help="Search every project.")] = False,
    kind: Annotated[
        list[str] | None, typer.Option("--kind", "-k", help="entry | summary | project. Repeatable.")
    ] = None,
    type_: Annotated[
        list[str] | None, typer.Option("--type", "-T", help="Entry type filter. Repeatable.")
    ] = None,
    since: Annotated[str | None, typer.Option("--since", help="e.g. 2026-11-01, 7d.")] = None,
    until: Annotated[str | None, typer.Option("--until", help="e.g. 2026-11-04.")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
    offset: Annotated[int, typer.Option("--offset")] = 0,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Full-text search (Chinese supported). Defaults to the current project.

    Outside a registered project, or with --all, every project is searched.
    """
    service = get_service()
    scope: dict = {}
    scope_note = None
    if not all_projects:
        if project:
            scope = {"project": project}
        else:
            try:
                scope = {"project": service.get_project(path=workspace(cwd)).id}
            except ProjectNotRegisteredError:
                all_projects = True
                scope_note = "(not inside a registered project: searching all projects)"
    page = service.search(
        query,
        all_projects=all_projects,
        kinds=kind,
        types=type_,
        since=parse_when(since),
        until=parse_when(until, end_of_day=True),
        limit=limit,
        offset=offset,
        **scope,
    )
    if json_:
        emit_json({**page.model_dump(mode="json"), "scope": "all" if all_projects else scope.get("project")})
        return
    if scope_note:
        out(scope_note)
    if not page.items:
        out("No matches.")
        return
    for hit in page.items:
        where = f"{hit.project_name}  " if all_projects else ""
        if hit.kind == "entry":
            label = f"#{hit.sequence} [{hit.entry_type}] {hit.title}"
        elif hit.kind == "summary":
            label = "[summary]"
        else:
            label = f"[project] {hit.title}"
        out(f"{where}{label}  {local_time(hit.created_at)}")
        if hit.snippet:
            out(f"    {hit.snippet}")
    if page.total > len(page.items) + offset:
        out(f"({len(page.items)} of {page.total} shown; use --limit/--offset)")
