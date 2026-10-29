import uuid
from pathlib import Path

import pytest

from ohmypm_common.project_id import (
    PROJECT_ID_FILENAME,
    ProjectIdError,
    find_project,
    init_project_id,
    locate_workspace,
)


def test_find_project_in_ancestor(tmp_path: Path) -> None:
    pid = uuid.uuid4()
    (tmp_path / PROJECT_ID_FILENAME).write_text(f"{pid}\n")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    found = find_project(nested, stop_at=tmp_path)
    assert found is not None
    assert found.project_id == pid
    assert found.root == tmp_path.resolve()


def test_nearest_project_wins(tmp_path: Path) -> None:
    outer, inner = uuid.uuid4(), uuid.uuid4()
    (tmp_path / PROJECT_ID_FILENAME).write_text(str(outer))
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / PROJECT_ID_FILENAME).write_text(str(inner))
    assert find_project(sub / ".", stop_at=tmp_path).project_id == inner  # type: ignore[union-attr]


def test_anonymous_workspace(tmp_path: Path) -> None:
    location = locate_workspace(tmp_path, stop_at=tmp_path)
    assert location.is_anonymous
    assert location.root == tmp_path.resolve()


def test_invalid_project_id_is_an_error_not_anonymous(tmp_path: Path) -> None:
    (tmp_path / PROJECT_ID_FILENAME).write_text("not-a-uuid")
    with pytest.raises(ProjectIdError):
        find_project(tmp_path, stop_at=tmp_path)


def test_non_canonical_uuid_rejected(tmp_path: Path) -> None:
    (tmp_path / PROJECT_ID_FILENAME).write_text(uuid.uuid4().hex)  # no dashes
    with pytest.raises(ProjectIdError):
        find_project(tmp_path, stop_at=tmp_path)


def test_init_never_overwrites(tmp_path: Path) -> None:
    created = init_project_id(tmp_path)
    again = init_project_id(tmp_path)
    assert again.project_id == created.project_id
    with pytest.raises(ProjectIdError):
        init_project_id(tmp_path, uuid.uuid4())
    assert (tmp_path / PROJECT_ID_FILENAME).read_text().strip() == str(created.project_id)


def test_project_id_survives_directory_move(tmp_path: Path) -> None:
    src = tmp_path / "old-name"
    src.mkdir()
    ident = init_project_id(src)
    moved = src.rename(tmp_path / "renamed")
    assert find_project(moved, stop_at=tmp_path).project_id == ident.project_id  # type: ignore[union-attr]
