"""Project registry commands: register, unregister, status, list, project ..."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from ohmypm.cli.common import (
    CwdOpt,
    JsonOpt,
    ProjectOpt,
    confirm_or_fail,
    emit_json,
    err,
    get_service,
    local_time,
    out,
    read_text_input,
    workspace,
)
from ohmypm.core.errors import ValidationError
from ohmypm.core.schemas import ProjectOut

project_app = typer.Typer(help="Inspect and manage a registered project.", no_args_is_help=True)


def print_project(p: ProjectOut) -> None:
    out(f"Project:     {p.name}{'  (unregistered)' if p.archived else ''}")
    out(f"ID:          {p.id}")
    out(f"Root:        {p.root_path}{'' if p.root_exists else '  (missing!)'}")
    if p.description:
        out(f"Description: {p.description}")
    if p.entry_count is not None:
        out(f"Records:     {p.entry_count}")
    out(f"Created:     {local_time(p.created_at)}")
    out(f"Activity:    {local_time(p.last_activity_at)}")


def register(
    path: Annotated[Path | None, typer.Argument(help="Project root (default: current directory).")] = None,
    name: Annotated[
        str | None, typer.Option("--name", "-n", help="Display name (default: directory name).")
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", "-d", help="Short project description.")
    ] = None,
    json_: JsonOpt = False,
) -> None:
    """Register a project directory. Only the ohmypm database is written - never the directory."""
    target = str(path) if path is not None else os.getcwd()
    project, outcome = get_service().register(target, name=name, description=description)
    if json_:
        emit_json({"outcome": outcome, "project": project})
        return
    messages = {
        "created": "Registered project",
        "existing": "Already registered",
        "reactivated": "Re-registered project (history restored)",
    }
    out(f"{messages[outcome]}: {project.name}")
    print_project(project)
    if os.path.realpath(target) == os.path.realpath(Path.home()):
        err("Warning: you registered your home directory; every directory below it now matches this project.")


def unregister(
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    purge: Annotated[
        bool,
        typer.Option("--purge", help="Permanently delete all records, summary and assets of the project."),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    json_: JsonOpt = False,
) -> None:
    """Stop associating a directory with ohmypm. History is kept unless --purge is given."""
    service = get_service()
    if purge:
        target = service.get_project(project=project, path=None if project else workspace(cwd))
        confirm_or_fail(
            f"Permanently delete project '{target.name}' and its {target.entry_count} record(s)?", yes
        )
        result = service.unregister(project=target.id, purge=True)
    else:
        result = service.unregister(project=project, path=None if project else workspace(cwd))
    if json_:
        emit_json({"purged": purge, "project": result})
        return
    if purge:
        out(f"Deleted project '{result.name}' and all of its records.")
    else:
        out(f"Unregistered '{result.name}' ({result.root_path}). Records are kept;")
        out("run `ohmypm register` in the directory again to restore them.")


def status(cwd: CwdOpt = None, json_: JsonOpt = False) -> None:
    """Show whether the current directory belongs to a registered project."""
    info = get_service().status(workspace(cwd))
    if json_:
        emit_json(info)
        return
    if not info["registered"]:
        out(f"Not registered: {info['path']}")
        out(info["hint"])
        return
    p = info["project"]
    out(f"Project:   {p['name']}  ({p['id']})")
    out(f"Root:      {p['root_path']}")
    if info["relative_path"] != ".":
        out(f"Subpath:   {info['relative_path']}")
    out(f"Records:   {p['entry_count']}  (open issues: {info['open_issues']})")
    out(
        f"Summary:   {'yes, updated ' + local_time(info['summary_updated_at']) if info['summary_exists'] else 'none'}"
    )
    out(f"Activity:  {local_time(p['last_activity_at'])}")


def list_projects(
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Include unregistered (archived) projects.")
    ] = False,
    json_: JsonOpt = False,
) -> None:
    """List registered projects (most recently active first)."""
    projects = get_service().list_projects(include_archived=all_)
    if json_:
        emit_json(projects)
        return
    if not projects:
        out("No projects registered. Run `ohmypm register` inside a project directory.")
        return
    width = max(len(p.name) for p in projects)
    for p in projects:
        flag = " (unregistered)" if p.archived else ("" if p.root_exists else " (missing dir)")
        out(
            f"{p.name:<{width}}  {p.id[:8]}  {p.entry_count:>5} rec  {local_time(p.last_activity_at):<16}  "
            f"{p.root_path}{flag}"
        )


@project_app.command("info")
def project_info(project: ProjectOpt = None, cwd: CwdOpt = None, json_: JsonOpt = False) -> None:
    """Show project details."""
    p = get_service().get_project(project=project, path=None if project else workspace(cwd))
    if json_:
        emit_json(p)
        return
    print_project(p)


@project_app.command("relink")
def project_relink(
    new_path: Annotated[Path, typer.Argument(help="New project root directory.")],
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Point a project at a new directory (after moving or re-cloning it).

    Without --project the project is detected from the working directory.
    """
    p = get_service().relink(new_path, project=project, path=None if project else workspace(cwd))
    if json_:
        emit_json(p)
        return
    out(f"Project '{p.name}' now lives at {p.root_path}")


@project_app.command("rename")
def project_rename(
    name: Annotated[str, typer.Argument(help="New display name.")],
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Rename a project (display name only)."""
    p = get_service().update_project(project=project, path=None if project else workspace(cwd), name=name)
    if json_:
        emit_json(p)
        return
    out(f"Renamed to '{p.name}'")


@project_app.command("describe")
def project_describe(
    text: Annotated[str | None, typer.Argument(help="New description (or use --file/--stdin).")] = None,
    file: Annotated[
        Path | None, typer.Option("--file", "-f", help="Read the description from a file.")
    ] = None,
    stdin: Annotated[bool, typer.Option("--stdin", help="Read the description from standard input.")] = False,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Set the project description. An empty string clears it."""
    value = read_text_input(text, file, stdin, what="text")
    if value is None:
        raise ValidationError("Provide a description, --file or --stdin")
    p = get_service().update_project(
        project=project, path=None if project else workspace(cwd), description=value
    )
    if json_:
        emit_json(p)
        return
    out(f"Description updated for '{p.name}'")
