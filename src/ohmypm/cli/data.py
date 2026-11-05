"""Assets, export, backup, restore and doctor commands."""

from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from ohmypm.cli.common import (
    CwdOpt,
    JsonOpt,
    ProjectOpt,
    confirm_or_fail,
    emit_json,
    get_service,
    local_time,
    out,
    reset_service,
    workspace,
)

assets_app = typer.Typer(
    help="Images and attachments stored in ohmypm's data directory.", no_args_is_help=True
)


def _scope(project: str | None, cwd: Path | None) -> dict:
    return {"project": project, "path": None if project else workspace(cwd)}


def _size(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


@assets_app.command("add")
def assets_add(
    file: Annotated[Path, typer.Argument(help="Image (PNG/JPEG/WebP/GIF/SVG) or UTF-8 text file.")],
    entry: Annotated[
        str | None, typer.Option("--entry", "-e", help="Attach to this entry (sequence or id).")
    ] = None,
    name: Annotated[str | None, typer.Option("--name", help="Stored file name (default: original).")] = None,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Store a file privately and print the Markdown reference to paste into an entry."""
    asset = get_service().add_asset_file(file, entry=entry, filename=name, **_scope(project, cwd))
    if json_:
        emit_json(asset)
        return
    out(asset.markdown)


@assets_app.command("list")
def assets_list(
    entry: Annotated[str | None, typer.Option("--entry", "-e", help="Only assets of this entry.")] = None,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """List assets of the project."""
    items = get_service().list_assets(entry=entry, **_scope(project, cwd))
    if json_:
        emit_json(items)
        return
    if not items:
        out("No assets.")
    for a in items:
        out(f"{a.id}  {a.mime_type:<14} {_size(a.size):>9}  {local_time(a.created_at)}  {a.filename}")


@assets_app.command("path")
def assets_path(
    asset_id: Annotated[str, typer.Argument(help="Asset id.")],
    json_: JsonOpt = False,
) -> None:
    """Print the local file path of an asset."""
    asset, path = get_service().get_asset(asset_id)
    if json_:
        emit_json({"asset": asset, "path": str(path), "exists": path.is_file()})
        return
    out(str(path))


@assets_app.command("gc")
def assets_gc(
    apply: Annotated[bool, typer.Option("--apply", help="Actually delete (default: dry run).")] = False,
    all_projects: Annotated[bool, typer.Option("--all-projects", help="Check every project.")] = False,
    grace_hours: Annotated[
        float, typer.Option("--grace-hours", help="Keep uploads younger than this.")
    ] = 1.0,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Find (and with --apply delete) assets no entry, summary or revision refers to."""
    scope = {} if all_projects else _scope(project, cwd)
    items = get_service().gc_assets(apply=apply, grace=timedelta(hours=grace_hours), **scope)
    if json_:
        emit_json({"applied": apply, "assets": items})
        return
    if not items:
        out("No unreferenced assets.")
        return
    for a in items:
        out(f"{'deleted' if apply else 'unreferenced'}  {a.id}  {a.filename}  {_size(a.size)}")
    if not apply:
        out(f"{len(items)} unreferenced asset(s). Re-run with --apply to delete them.")


def export(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Target directory (default: <data>/exports/export-<time>)."),
    ] = None,
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Export every project (including unregistered).")
    ] = False,
    project: ProjectOpt = None,
    cwd: CwdOpt = None,
    json_: JsonOpt = False,
) -> None:
    """Export records, summaries and assets as plain Markdown files."""
    from ohmypm.core.export import export_markdown

    service = get_service()
    ids = None if all_ else [service.get_project(**_scope(project, cwd)).id]
    result = export_markdown(service.db, service.settings, project_ids=ids, output=output)
    if json_:
        emit_json(result)
        return
    out(f"Exported {len(result['projects'])} project(s) to {result['path']}")


def backup(
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Archive path (default: <data>/backups/...tar.gz).")
    ] = None,
    json_: JsonOpt = False,
) -> None:
    """Create a consistent .tar.gz backup of the database and all assets."""
    from ohmypm.core.export import backup as do_backup

    service = get_service()
    result = do_backup(service.db, service.settings, output=output)
    if json_:
        emit_json(result)
        return
    counts = result["counts"]
    out(f"Backup written: {result['path']} ({_size(result['size'])})")
    out(f"  {counts['projects']} project(s), {counts['entries']} entr(y/ies), {counts['assets']} asset(s)")


def restore(
    archive: Annotated[Path, typer.Argument(help="Backup archive created by `ohmypm backup`.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    json_: JsonOpt = False,
) -> None:
    """Replace all local ohmypm data with a backup (current data is stashed, not deleted)."""
    from ohmypm.config import load_settings
    from ohmypm.core.export import inspect_backup
    from ohmypm.core.export import restore as do_restore

    manifest = inspect_backup(archive)
    counts = manifest.get("counts", {})
    confirm_or_fail(
        f"Replace ALL current ohmypm data with this backup ({counts.get('projects', '?')} projects, "
        f"{counts.get('entries', '?')} entries from {manifest.get('created_at')})?",
        yes,
    )
    reset_service()
    result = do_restore(load_settings(), archive)
    if json_:
        emit_json(result)
        return
    out(f"Restored from {archive}. Previous data moved to {result['previous_data']}")


def doctor(json_: JsonOpt = False) -> None:
    """Check the installation: paths, database, search, Web UI and agents."""
    from ohmypm import __version__
    from ohmypm.agents.manager import AgentManager
    from ohmypm.api.static import web_dist_dir

    service = get_service()
    settings = service.settings
    checks: dict = {
        "version": __version__,
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "data_dir": str(settings.data_dir),
        "config_dir": str(settings.config_dir),
        "database": str(settings.db_path),
        "schema_revision": service.db.schema_revision(),
        "fts5_trigram": _has_trigram(),
        "web_ui_built": web_dist_dir() is not None,
        "projects": len(service.list_projects()),
        "agents": [s.model_dump(mode="json") for s in AgentManager(settings).status()],
    }
    if json_:
        emit_json(checks)
        return
    for key in (
        "version",
        "python",
        "sqlite",
        "data_dir",
        "config_dir",
        "database",
        "schema_revision",
        "fts5_trigram",
        "web_ui_built",
        "projects",
    ):
        out(f"{key + ':':<17} {checks[key]}")
    out("agents:")
    for a in checks["agents"]:
        out(f"  {a['agent']:<12} {a['state']:<14} {a['target'] or '-'}")


def _has_trigram() -> bool:
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()
