from __future__ import annotations

import struct
import zlib
from datetime import timedelta
from pathlib import Path

import pytest

from ohmypm.core.errors import NotFoundError, ValidationError
from ohmypm.core.schemas import EntryCreate, EntryUpdate
from ohmypm.core.service import MemoryService
from ohmypm.storage.files import safe_child


def make_png(width: int = 2, height: int = 2) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


SAFE_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'


@pytest.fixture
def project_id(service: MemoryService, workspace: Path) -> str:
    return service.register(workspace)[0].id


def test_upload_png_and_reference(service: MemoryService, project_id: str, settings) -> None:
    asset = service.add_asset("截图 error.png", make_png(), project=project_id)
    assert asset.mime_type == "image/png"
    assert asset.markdown == f"![截图 error.png](ohmypm-asset://{asset.id})"
    meta, path = service.get_asset(asset.id)
    assert path.is_file() and path.read_bytes() == make_png()
    assert settings.assets_dir in path.parents
    assert oct(path.stat().st_mode & 0o777) == "0o600"

    entry = service.add_entry(
        EntryCreate(title="with image", content=f"see {asset.markdown}"), project=project_id
    )
    assert entry.asset_ids == [asset.id]
    assert service.get_asset(asset.id)[0].entry_id == entry.id
    assert [a.id for a in service.list_assets(project=project_id, entry=entry.id)] == [asset.id]


def test_duplicate_upload_is_deduplicated(service: MemoryService, project_id: str) -> None:
    a = service.add_asset("a.png", make_png(), project=project_id)
    b = service.add_asset("b.png", make_png(), project=project_id)
    assert a.id == b.id


def test_type_detection_overrides_extension(service: MemoryService, project_id: str) -> None:
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    asset = service.add_asset("photo.png", jpeg, project=project_id)
    assert asset.mime_type == "image/jpeg"
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16
    assert service.add_asset("x.webp", webp, project=project_id).mime_type == "image/webp"
    text = service.add_asset("build.log", "编译日志\nerror: x\n".encode(), project=project_id)
    assert text.mime_type == "text/plain" and text.markdown.startswith("[build.log](")


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("evil.exe", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64),
        ("archive.zip", b"PK\x03\x04" + b"\x00" * 30),
        ("binary.txt", b"abc\x00def"),
        ("empty.png", b""),
    ],
)
def test_rejects_unsupported_files(service: MemoryService, project_id: str, name: str, data: bytes) -> None:
    with pytest.raises(ValidationError):
        service.add_asset(name, data, project=project_id)


def test_size_limit(service: MemoryService, project_id: str, settings) -> None:
    too_big = make_png() + b"\x00" * (settings.max_upload_bytes + 1)
    with pytest.raises(ValidationError):
        service.add_asset("big.png", too_big, project=project_id)


def test_svg_validation(service: MemoryService, project_id: str) -> None:
    assert service.add_asset("ok.svg", SAFE_SVG, project=project_id).mime_type == "image/svg+xml"
    bad = [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink">'
        b'<a x:href="javascript:alert(1)"><text>x</text></a></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div/></foreignObject></svg>',
        b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/x.png"/></svg>',
        b"<svg><unclosed></svg>",
    ]
    for payload in bad:
        with pytest.raises(ValidationError):
            service.add_asset("bad.svg", payload, project=project_id)


def test_filename_sanitising(service: MemoryService, project_id: str, settings) -> None:
    asset = service.add_asset("../../etc/passwd.png", make_png(3, 3), project=project_id)
    assert asset.filename == "passwd.png"
    _, path = service.get_asset(asset.id)
    assert settings.assets_dir.resolve() in path.parents


def test_safe_child_blocks_traversal(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    assert safe_child(root, "p/a.png") == (root / "p" / "a.png").resolve()
    for bad in ("../x", "/etc/passwd", "p/../../x", "", "a\x00b"):
        with pytest.raises(ValueError):
            safe_child(root, bad)


def test_tampered_storage_path_is_not_served(service: MemoryService, project_id: str, db) -> None:
    from ohmypm.storage.models import Asset

    asset = service.add_asset("a.png", make_png(), project=project_id)
    with db.write() as s:
        s.get(Asset, asset.id).storage_path = "../../../etc/passwd"
    with pytest.raises(NotFoundError):
        service.get_asset(asset.id)


def test_missing_asset(service: MemoryService) -> None:
    with pytest.raises(NotFoundError):
        service.get_asset("00000000-0000-0000-0000-000000000000")


def test_garbage_collection(service: MemoryService, project_id: str) -> None:
    used = service.add_asset("used.png", make_png(1, 1), project=project_id)
    orphan = service.add_asset("orphan.png", make_png(4, 4), project=project_id)
    edited_away = service.add_asset("old.png", make_png(5, 5), project=project_id)
    service.add_entry(EntryCreate(title="uses", content=used.markdown), project=project_id)
    e2 = service.add_entry(EntryCreate(title="edit", content=edited_away.markdown), project=project_id)
    service.update_entry(e2.id, EntryUpdate(content="no image anymore"))

    # Fresh uploads are protected by the grace period.
    assert service.gc_assets(project=project_id) == []
    candidates = service.gc_assets(project=project_id, grace=timedelta(0))
    # The edited-away image is still referenced by the kept revision.
    assert [a.id for a in candidates] == [orphan.id]
    _, orphan_path = service.get_asset(orphan.id)
    service.gc_assets(project=project_id, grace=timedelta(0), apply=True)
    assert not orphan_path.exists()
    with pytest.raises(NotFoundError):
        service.get_asset(orphan.id)
    assert service.get_asset(used.id)[1].exists()


def test_failed_transaction_removes_written_file(service: MemoryService, project_id: str, settings) -> None:
    from ohmypm.core import assets as assets_core
    from ohmypm.core import projects as projects_core

    with pytest.raises(RuntimeError), service.db.write() as s:
        project = projects_core.get_project(s, project_id)
        assets_core.add_asset(s, settings, project, "x.png", make_png(6, 6))
        raise RuntimeError("boom")
    files = (
        list((settings.assets_dir / project_id).glob("*"))
        if (settings.assets_dir / project_id).exists()
        else []
    )
    assert files == []
