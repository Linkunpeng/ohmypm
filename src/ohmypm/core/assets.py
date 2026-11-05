"""Images and attachments stored in ohmypm's private data directory.

Markdown references assets through the stable ``ohmypm-asset://<id>`` URI,
so moving a project directory never breaks them.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import timedelta
from pathlib import Path, PurePath

from sqlalchemy import select
from sqlalchemy.orm import Session

from ohmypm.config import Settings
from ohmypm.core.errors import NotFoundError, ValidationError
from ohmypm.core.schemas import AssetOut
from ohmypm.core.text import ASSET_SCHEME, asset_refs
from ohmypm.storage.files import after_commit, atomic_write_bytes, remove_file, safe_child
from ohmypm.storage.models import SUMMARY_FIELDS, Asset, Entry, EntryRevision, Project, ProjectSummary, utcnow

IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".log",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".csv",
    ".tsv",
    ".xml",
    ".diff",
    ".patch",
    ".py",
    ".sh",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".rs",
    ".go",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".sql",
    ".cmake",
    ".html",
    ".css",
    ".proto",
    ".launch",
    ".urdf",
    ".srt",
}
TEXT_MIME = "text/plain"
GC_GRACE = timedelta(hours=1)

_SVG_FORBIDDEN_TAGS = {
    "script",
    "foreignobject",
    "iframe",
    "embed",
    "object",
    "handler",
    "listener",
    "audio",
    "video",
}
_UNSAFE_URL = re.compile(r"^\s*(javascript|vbscript|data:(?!image/(png|jpeg|gif|webp);))", re.I)


def is_image(mime_type: str) -> bool:
    return mime_type in IMAGE_TYPES


def to_out(asset: Asset) -> AssetOut:
    uri = f"{ASSET_SCHEME}{asset.id}"
    label = asset.filename.replace("[", "(").replace("]", ")")
    markdown = f"![{label}]({uri})" if is_image(asset.mime_type) else f"[{label}]({uri})"
    return AssetOut(
        id=asset.id,
        project_id=asset.project_id,
        entry_id=asset.entry_id,
        filename=asset.filename,
        mime_type=asset.mime_type,
        size=asset.size,
        sha256=asset.sha256,
        created_at=asset.created_at,
        uri=uri,
        markdown=markdown,
    )


def sanitize_filename(name: str) -> str:
    name = PurePath(name.replace("\\", "/")).name
    name = unicodedata.normalize("NFC", name)
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '/\\:*?"<>|')
    name = name.strip(" .")
    if not name:
        name = "attachment"
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:190] + dot + ext[:9]) if dot else name[:200]
    return name


def _sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def _decode_text(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def validate_svg(text: str) -> None:
    """Reject SVGs that could execute script or load external content."""
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValidationError("SVG files with DOCTYPE/ENTITY declarations are not allowed")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValidationError(f"Invalid SVG: {exc}") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise ValidationError("Not an SVG document")
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower() if isinstance(element.tag, str) else ""
        if tag in _SVG_FORBIDDEN_TAGS:
            raise ValidationError(f"SVG element <{tag}> is not allowed")
        if (
            tag == "style"
            and element.text
            and ("@import" in element.text or "javascript:" in element.text.lower())
        ):
            raise ValidationError("SVG <style> with @import or script URLs is not allowed")
        for attr, value in element.attrib.items():
            name = attr.rsplit("}", 1)[-1].lower()
            if name.startswith("on"):
                raise ValidationError(f"SVG event handler attribute '{name}' is not allowed")
            if name in {"href", "src"} and (
                _UNSAFE_URL.match(value) or value.strip().lower().startswith(("http:", "https:", "//"))
            ):
                raise ValidationError("SVG references to scripts or external resources are not allowed")


def classify(filename: str, data: bytes) -> tuple[str, str]:
    """Return ``(mime_type, extension)`` or raise ``ValidationError``."""
    ext = PurePath(filename).suffix.lower()
    image = _sniff_image(data)
    if image:
        return image, IMAGE_TYPES[image]
    text = _decode_text(data)
    if text is not None:
        head = text.lstrip()[:1024].lower()
        if ext == ".svg" or head.startswith("<svg") or (head.startswith("<?xml") and "<svg" in head):
            validate_svg(text)
            return "image/svg+xml", ".svg"
        if ext in TEXT_EXTENSIONS or not ext:
            return TEXT_MIME, ext or ".txt"
    raise ValidationError(
        f"Unsupported file type for '{filename}'",
        details={"allowed": "PNG, JPEG, WebP, GIF, SVG images and UTF-8 text files"},
    )


def add_asset(
    session: Session,
    settings: Settings,
    project: Project,
    filename: str,
    data: bytes,
    *,
    entry: Entry | None = None,
) -> Asset:
    if not data:
        raise ValidationError("Empty file")
    if len(data) > settings.max_upload_bytes:
        raise ValidationError(
            f"File is too large ({len(data)} bytes; limit {settings.max_upload_bytes})",
            details={"limit": settings.max_upload_bytes},
        )
    if entry is not None and entry.project_id != project.id:
        raise ValidationError("Entry belongs to another project")
    filename = sanitize_filename(filename)
    mime_type, ext = classify(filename, data)
    if not PurePath(filename).suffix:
        filename += ext
    digest = hashlib.sha256(data).hexdigest()

    existing = session.scalars(
        select(Asset).where(Asset.project_id == project.id, Asset.sha256 == digest)
    ).first()
    if existing is not None and asset_path(settings, existing).is_file():
        if entry is not None and existing.entry_id is None:
            existing.entry_id = entry.id
        return existing

    asset = Asset(
        project_id=project.id,
        entry_id=entry.id if entry else None,
        filename=filename,
        mime_type=mime_type,
        size=len(data),
        sha256=digest,
        storage_path="",
        created_at=utcnow(),
    )
    session.add(asset)
    session.flush()
    asset.storage_path = f"{project.id}/{asset.id}{ext}"
    target = safe_child(settings.assets_dir, asset.storage_path)
    atomic_write_bytes(target, data)
    # Remove the file again if the transaction does not commit.
    session.info.setdefault("ohmypm_new_files", []).append(target)
    session.flush()
    return asset


def asset_path(settings: Settings, asset: Asset) -> Path:
    try:
        return safe_child(settings.assets_dir, asset.storage_path)
    except ValueError as exc:
        raise NotFoundError(f"Asset {asset.id} has an invalid storage path") from exc


def get_asset(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id.strip().lower())
    if asset is None:
        raise NotFoundError(f"Asset not found: {asset_id}")
    return asset


def list_assets(
    session: Session, *, project_id: str | None = None, entry_id: str | None = None
) -> list[Asset]:
    stmt = select(Asset).order_by(Asset.created_at.desc())
    if project_id:
        stmt = stmt.where(Asset.project_id == project_id)
    if entry_id:
        stmt = stmt.where(Asset.entry_id == entry_id)
    return list(session.scalars(stmt).all())


def referenced_asset_ids(session: Session, project_id: str | None = None) -> set[str]:
    """Asset ids referenced from entries, summaries or kept entry revisions."""
    refs: set[str] = set()
    queries = [
        select(Entry.content).where(Entry.content.contains(ASSET_SCHEME)),
        select(EntryRevision.content).where(EntryRevision.content.contains(ASSET_SCHEME)),
    ]
    if project_id:
        queries = [
            queries[0].where(Entry.project_id == project_id),
            queries[1].where(EntryRevision.project_id == project_id),
        ]
    for query in queries:
        for content in session.scalars(query):
            refs |= asset_refs(content)
    summaries = select(ProjectSummary)
    if project_id:
        summaries = summaries.where(ProjectSummary.project_id == project_id)
    for summary in session.scalars(summaries):
        for field in SUMMARY_FIELDS:
            refs |= asset_refs(getattr(summary, field) or "")
    return refs


def find_unreferenced(
    session: Session, *, project_id: str | None = None, grace: timedelta = GC_GRACE
) -> list[Asset]:
    """Assets nothing refers to, older than ``grace`` (fresh uploads may still be in an editor)."""
    refs = referenced_asset_ids(session, project_id)
    cutoff = utcnow() - grace
    return [
        a for a in list_assets(session, project_id=project_id) if a.id not in refs and a.created_at <= cutoff
    ]


def delete_asset(session: Session, settings: Settings, asset: Asset) -> None:
    path = asset_path(settings, asset)
    session.delete(asset)
    session.flush()
    after_commit(session, lambda: remove_file(path))


def missing_files(session: Session, settings: Settings) -> list[Asset]:
    return [a for a in list_assets(session) if not asset_path(settings, a).is_file()]
