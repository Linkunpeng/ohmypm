from __future__ import annotations

import os
from pathlib import Path

import pytest

from ohmypm.core.errors import (
    AmbiguousReferenceError,
    ConflictError,
    NotFoundError,
    ProjectNotRegisteredError,
    ValidationError,
)
from ohmypm.core.schemas import EntryCreate
from ohmypm.core.service import MemoryService
from tests.conftest import tree_snapshot


def test_register_creates_project_without_touching_directory(service: MemoryService, workspace: Path) -> None:
    before = tree_snapshot(workspace)
    project, outcome = service.register(workspace)
    assert outcome == "created"
    assert project.name == "Robot_WS"
    assert project.root_path == str(workspace.resolve())
    assert project.root_exists
    assert tree_snapshot(workspace) == before


def test_register_twice_returns_existing(service: MemoryService, workspace: Path) -> None:
    first, _ = service.register(workspace)
    second, outcome = service.register(str(workspace) + "/")
    assert outcome == "existing"
    assert second.id == first.id
    assert len(service.list_projects()) == 1


def test_register_normalises_path(service: MemoryService, workspace: Path) -> None:
    messy = workspace / "src" / ".." / "src" / "camera" / ".." / ".."
    project, _ = service.register(messy)
    assert project.root_path == str(workspace.resolve())


def test_register_rejects_missing_dir_and_root(service: MemoryService, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        service.register(tmp_path / "does-not-exist")
    with pytest.raises(ValidationError):
        service.register("/")


def test_subdirectory_detection(service: MemoryService, workspace: Path) -> None:
    project, _ = service.register(workspace)
    status = service.status(workspace / "src" / "camera")
    assert status["registered"] is True
    assert status["project"]["id"] == project.id
    assert status["relative_path"] == os.path.join("src", "camera")


def test_similar_prefix_is_not_matched(service: MemoryService, tmp_path: Path) -> None:
    a = tmp_path / "work" / "robot"
    b = tmp_path / "work" / "robot2"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    service.register(a)
    assert service.status(b)["registered"] is False
    assert service.status(a / "x")["registered"] is True  # nonexistent subpath still matches


def test_nested_projects_use_longest_match(service: MemoryService, workspace: Path) -> None:
    outer, _ = service.register(workspace)
    inner_dir = workspace / "src" / "camera"
    inner, _ = service.register(inner_dir, name="camera")
    assert service.status(inner_dir)["project"]["id"] == inner.id
    assert service.status(workspace / "src")["project"]["id"] == outer.id


def test_symlinked_paths_resolve(service: MemoryService, workspace: Path, tmp_path: Path) -> None:
    link = tmp_path / "link-to-robot"
    link.symlink_to(workspace, target_is_directory=True)
    project, outcome = service.register(link)
    assert project.root_path == str(workspace.resolve())
    # Registering the real path afterwards finds the same project.
    again, outcome = service.register(workspace)
    assert outcome == "existing" and again.id == project.id
    assert service.status(link / "src")["project"]["id"] == project.id


def test_unregistered_directory(service: MemoryService, tmp_path: Path) -> None:
    status = service.status(tmp_path)
    assert status == {
        "registered": False,
        "path": str(tmp_path.resolve()),
        "project": None,
        "hint": status["hint"],
    }
    with pytest.raises(ProjectNotRegisteredError):
        service.list_entries(path=tmp_path)


def test_relink_moves_project(service: MemoryService, workspace: Path, tmp_path: Path) -> None:
    project, _ = service.register(workspace)
    service.add_entry(EntryCreate(title="before move"), project=project.id)
    new_root = tmp_path / "moved" / "Robot_WS"
    new_root.parent.mkdir()
    workspace.rename(new_root)
    relinked = service.relink(new_root, project=project.id)
    assert relinked.root_path == str(new_root.resolve())
    assert str(workspace) in relinked.metadata["previous_roots"]
    assert service.status(new_root / "src")["project"]["id"] == project.id
    assert service.list_entries(path=new_root).total == 1


def test_relink_conflict(service: MemoryService, workspace: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    a, _ = service.register(workspace)
    service.register(other)
    with pytest.raises(ConflictError):
        service.relink(other, project=a.id)


def test_unregister_keeps_history_and_reactivates(service: MemoryService, workspace: Path) -> None:
    project, _ = service.register(workspace)
    service.add_entry(EntryCreate(type="milestone", title="done"), project=project.id)
    archived = service.unregister(project=project.id)
    assert archived.archived
    assert service.status(workspace)["registered"] is False
    assert service.list_projects() == []
    assert len(service.list_projects(include_archived=True)) == 1

    again, outcome = service.register(workspace)
    assert outcome == "reactivated"
    assert again.id == project.id
    assert service.list_entries(path=workspace).total == 1


def test_purge_deletes_everything(service: MemoryService, workspace: Path, settings) -> None:
    project, _ = service.register(workspace)
    service.add_entry(EntryCreate(title="x"), project=project.id)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    service.add_asset("a.png", png, project=project.id)
    assert (settings.assets_dir / project.id).is_dir()
    service.unregister(project=project.id, purge=True)
    assert service.list_projects(include_archived=True) == []
    assert not (settings.assets_dir / project.id).exists()
    assert workspace.is_dir()  # the source project itself is never deleted


def test_project_lookup_by_name_and_prefix(service: MemoryService, workspace: Path, tmp_path: Path) -> None:
    project, _ = service.register(workspace)
    assert service.get_project(project="robot_ws").id == project.id
    assert service.get_project(project=project.id[:8]).id == project.id
    with pytest.raises(NotFoundError):
        service.get_project(project="nope")
    other = tmp_path / "x" / "Robot_WS"
    other.mkdir(parents=True)
    service.register(other)
    with pytest.raises(AmbiguousReferenceError):
        service.get_project(project="Robot_WS")


def test_update_project(service: MemoryService, workspace: Path) -> None:
    project, _ = service.register(workspace)
    updated = service.update_project(project=project.id, name="Robot", description="ROS2 workspace")
    assert updated.name == "Robot" and updated.description == "ROS2 workspace"
    with pytest.raises(ValidationError):
        service.update_project(project=project.id, name="   ")


def test_service_requires_explicit_project(service: MemoryService) -> None:
    with pytest.raises(ValidationError):
        service.get_summary()
