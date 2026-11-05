"""Markdown export, consistent backups and restore.

Defaults always write into ohmypm's own data directory - never into the
current working directory, which may be a registered source project.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ohmypm import __version__
from ohmypm.config import Settings, ensure_private_dir
from ohmypm.core import assets as assets_core
from ohmypm.core import projects as projects_core
from ohmypm.core import summaries as summaries_core
from ohmypm.core.errors import ValidationError
from ohmypm.core.text import ASSET_REF_RE
from ohmypm.storage.database import SCHEMA_HEAD, Database
from ohmypm.storage.models import Asset, Entry, Project

BACKUP_MANIFEST = "manifest.json"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def slugify(text: str, limit: int = 60) -> str:
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = re.sub(r"[^\w-]+", "-", text)  # \w covers CJK and other scripts
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    return text[:limit].rstrip("-") or "untitled"


def _front_matter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False, default=str)}")
    lines.append("---")
    return "\n".join(lines)


# ------------------------------------------------------------------ export


def export_markdown(
    db: Database,
    settings: Settings,
    *,
    project_ids: list[str] | None = None,
    output: Path | None = None,
    include_archived: bool = True,
) -> dict[str, Any]:
    """Export projects as plain Markdown folders with copied assets."""
    root = output or (settings.data_dir / "exports" / f"export-{_timestamp()}")
    root = Path(root).expanduser().absolute()
    if root.exists() and any(root.iterdir()):
        raise ValidationError(f"Export directory is not empty: {root}")
    ensure_private_dir(root)

    exported = []
    with db.read() as s:
        projects = [p for p, _ in projects_core.list_projects(s, include_archived=include_archived)]
        if project_ids is not None:
            projects = [p for p in projects if p.id in project_ids]
        for project in projects:
            exported.append(_export_project(s, settings, project, root))
    index = ["# ohmypm export", "", f"Exported {datetime.now().astimezone():%Y-%m-%d %H:%M %Z}", ""]
    for item in exported:
        index.append(f"- [{item['name']}]({item['dir']}/README.md) — {item['entries']} record(s)")
    (root / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return {"path": str(root), "projects": exported}


def _export_project(session, settings: Settings, project: Project, root: Path) -> dict[str, Any]:
    folder = f"{slugify(project.name)}-{project.id[:8]}"
    base = root / folder
    (base / "entries").mkdir(parents=True)

    asset_files: dict[str, str] = {}
    assets = session.scalars(select(Asset).where(Asset.project_id == project.id)).all()
    if assets:
        (base / "assets").mkdir()
    for asset in assets:
        source = assets_core.asset_path(settings, asset)
        name = f"{asset.id[:8]}-{assets_core.sanitize_filename(asset.filename)}"
        if source.is_file():
            shutil.copy2(source, base / "assets" / name)
            asset_files[asset.id] = name

    def rewrite(markdown: str, prefix: str) -> str:
        return ASSET_REF_RE.sub(
            lambda m: (
                f"{prefix}{asset_files[m.group(1).lower()]}"
                if m.group(1).lower() in asset_files
                else m.group(0)
            ),
            markdown,
        )

    summary = summaries_core.get_summary(session, project)
    summary_md = summaries_core.render_summary_markdown(summary, title=f"{project.name} — Project Summary")
    (base / "summary.md").write_text(rewrite(summary_md, "assets/"), encoding="utf-8")

    entries = session.scalars(
        select(Entry).where(Entry.project_id == project.id).order_by(Entry.sequence)
    ).all()
    timeline = []
    for entry in entries:
        filename = f"{entry.sequence:04d}-{slugify(entry.title)}.md"
        fm = _front_matter(
            {
                "id": entry.id,
                "sequence": entry.sequence,
                "type": entry.type,
                "title": entry.title,
                "status": entry.status,
                "author": entry.author,
                "source": entry.source,
                "created_at": entry.created_at.isoformat(),
                "updated_at": entry.updated_at.isoformat(),
                "revision": entry.revision,
                "metadata": entry.meta or None,
            }
        )
        body = rewrite(entry.content, "../assets/")
        (base / "entries" / filename).write_text(f"{fm}\n\n# {entry.title}\n\n{body}\n", encoding="utf-8")
        status = f" ({entry.status})" if entry.status else ""
        timeline.append(
            f"| {entry.sequence} | {entry.created_at:%Y-%m-%d %H:%M} | {entry.type}{status} | "
            f"[{entry.title.replace('|', '/')}](entries/{filename}) | {entry.author or ''} |"
        )

    readme = [
        f"# {project.name}",
        "",
        f"- Root: `{project.root_path}`",
        f"- Project ID: `{project.id}`",
        f"- Registered: {project.created_at:%Y-%m-%d}",
    ]
    if project.archived_at:
        readme.append(f"- Unregistered: {project.archived_at:%Y-%m-%d}")
    if project.description:
        readme += ["", project.description]
    readme += ["", "See [summary.md](summary.md).", "", "## Timeline", ""]
    if timeline:
        readme += ["| # | Created (UTC) | Type | Title | Author |", "|---|---|---|---|---|", *timeline]
    else:
        readme.append("_No records._")
    (base / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    return {
        "id": project.id,
        "name": project.name,
        "dir": folder,
        "entries": len(entries),
        "assets": len(asset_files),
    }


# ------------------------------------------------------------------ backup


def backup(db: Database, settings: Settings, *, output: Path | None = None) -> dict[str, Any]:
    """Write a consistent ``.tar.gz`` of the database and all assets."""
    ensure_private_dir(settings.backups_dir)
    target = (
        Path(output).expanduser().absolute()
        if output
        else settings.backups_dir / f"ohmypm-backup-{_timestamp()}.tar.gz"
    )
    if target.exists():
        raise ValidationError(f"Backup file already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=settings.data_dir, prefix=".backup-") as tmp:
        snapshot = Path(tmp) / "ohmypm.db"
        # SQLite's online backup API gives a consistent copy even while other
        # processes are writing.
        src = sqlite3.connect(settings.db_path)
        dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        counts = _counts(snapshot)
        manifest = {
            "format": "ohmypm-backup",
            "format_version": 1,
            "ohmypm_version": __version__,
            "schema_revision": SCHEMA_HEAD,
            "created_at": datetime.now(UTC).isoformat(),
            "counts": counts,
        }
        (Path(tmp) / BACKUP_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        old_umask = os.umask(0o077)
        try:
            with tarfile.open(target, "w:gz") as tar:
                tar.add(Path(tmp) / BACKUP_MANIFEST, arcname=BACKUP_MANIFEST)
                tar.add(snapshot, arcname="ohmypm.db")
                if settings.assets_dir.is_dir():
                    tar.add(settings.assets_dir, arcname="assets")
        finally:
            os.umask(old_umask)
    os.chmod(target, 0o600)
    return {"path": str(target), "size": target.stat().st_size, **manifest}


def _counts(db_file: Path) -> dict[str, int]:
    con = sqlite3.connect(db_file)
    try:
        return {
            table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608 - fixed names
            for table in ("projects", "entries", "project_summaries", "assets")
        }
    finally:
        con.close()


def inspect_backup(archive: Path) -> dict[str, Any]:
    archive = Path(archive).expanduser()
    if not archive.is_file():
        raise ValidationError(f"Backup not found: {archive}")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            if BACKUP_MANIFEST not in names or "ohmypm.db" not in names:
                raise ValidationError("Not an ohmypm backup (manifest.json / ohmypm.db missing)")
            member = tar.extractfile(BACKUP_MANIFEST)
            manifest = json.loads(member.read().decode("utf-8")) if member else {}
    except (tarfile.TarError, OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot read backup: {exc}") from exc
    if manifest.get("format") != "ohmypm-backup":
        raise ValidationError("Not an ohmypm backup (bad manifest)")
    return manifest


def restore(settings: Settings, archive: Path) -> dict[str, Any]:
    """Replace the current data with a backup.

    The current database and assets are first moved to
    ``<data>/pre-restore-<timestamp>/`` so a restore is itself reversible.
    Callers must close their own database connections first.
    """
    manifest = inspect_backup(archive)
    ensure_private_dir(settings.data_dir)
    stash = settings.data_dir / f"pre-restore-{_timestamp()}"
    with tempfile.TemporaryDirectory(dir=settings.data_dir, prefix=".restore-") as tmp:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(tmp, filter="data")
        extracted_db = Path(tmp) / "ohmypm.db"
        con = sqlite3.connect(extracted_db)
        try:
            con.execute("SELECT count(*) FROM projects").fetchone()
        except sqlite3.DatabaseError as exc:
            raise ValidationError(f"Backup database is unreadable: {exc}") from exc
        finally:
            con.close()

        stash.mkdir(mode=0o700)
        for name in ("ohmypm.db", "ohmypm.db-wal", "ohmypm.db-shm"):
            current = settings.data_dir / name
            if current.exists():
                shutil.move(current, stash / name)
        if settings.assets_dir.exists():
            shutil.move(settings.assets_dir, stash / "assets")
        shutil.move(extracted_db, settings.db_path)
        os.chmod(settings.db_path, 0o600)
        extracted_assets = Path(tmp) / "assets"
        if extracted_assets.is_dir():
            shutil.move(extracted_assets, settings.assets_dir)
        else:
            ensure_private_dir(settings.assets_dir)
    # Bring an older backup up to the current schema.
    Database(settings).dispose()
    return {"restored_from": str(archive), "previous_data": str(stash), "manifest": manifest}
