from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ohmypm.core.errors import ValidationError
from ohmypm.core.schemas import EntryCreate, EntryUpdate, SummaryUpdate
from ohmypm.core.service import MemoryService


@pytest.fixture
def two_projects(service: MemoryService, tmp_path: Path) -> tuple[str, str]:
    a = tmp_path / "robot"
    b = tmp_path / "webapp"
    a.mkdir()
    b.mkdir()
    pa = service.register(a, description="机器人 workspace")[0].id
    pb = service.register(b)[0].id
    service.add_entry(
        EntryCreate(type="issue", title="OpenCV 链接失败", content="undefined reference to cv::Mat"),
        project=pa,
    )
    service.add_entry(
        EntryCreate(type="milestone", title="完成相机驱动", content="已实现 V4L2 图像采集"), project=pa
    )
    service.add_entry(
        EntryCreate(type="note", title="React router upgrade", content="migrated to v7"), project=pb
    )
    service.set_summary(SummaryUpdate(overview="相机与规划模块", known_issues="偶发丢帧"), project=pa)
    return pa, pb


def test_english_search_ranks_title_first(service: MemoryService, two_projects) -> None:
    pa, _ = two_projects
    page = service.search("OpenCV", project=pa)
    assert page.total == 1
    hit = page.items[0]
    assert hit.kind == "entry" and hit.sequence == 1 and hit.entry_type == "issue"
    assert hit.project_name == "robot"


def test_chinese_search_three_chars_and_two_chars(service: MemoryService, two_projects) -> None:
    pa, _ = two_projects
    assert {h.title for h in service.search("图像采集", project=pa).items} == {"完成相机驱动"}
    # two-character CJK terms use the LIKE fallback
    titles = {h.title for h in service.search("相机", project=pa).items}
    assert titles == {"完成相机驱动", "Project summary"}
    assert service.search("丢帧", project=pa).items[0].kind == "summary"
    # mixed terms are ANDed
    assert {h.title for h in service.search("相机 V4L2", project=pa).items} == {"完成相机驱动"}


def test_identifier_and_special_characters(service: MemoryService, two_projects) -> None:
    pa, _ = two_projects
    assert service.search("cv::Mat", project=pa).total == 1
    assert service.search('"undefined reference"', project=pa).total == 1
    assert service.search('weird"quote', project=pa).total == 0
    assert service.search("100%", project=pa).total == 0


def test_project_scope_and_all_projects(service: MemoryService, two_projects) -> None:
    pa, pb = two_projects
    assert service.search("router", project=pa).total == 0
    assert service.search("router", project=pb).total == 1
    assert service.search("router", all_projects=True).total == 1
    kinds = {h.kind for h in service.search("robot", all_projects=True).items}
    assert "project" in kinds


def test_filters(service: MemoryService, two_projects) -> None:
    pa, _ = two_projects
    assert service.search("相机", project=pa, kinds=["entry"]).total == 1
    assert service.search("OpenCV", project=pa, types=["milestone"]).total == 0
    future = datetime.now(UTC) + timedelta(hours=1)
    assert service.search("OpenCV", project=pa, since=future).total == 0
    assert service.search("OpenCV", project=pa, until=future).total == 1
    with pytest.raises(ValidationError):
        service.search("x", project=pa, kinds=["bogus"])
    with pytest.raises(ValidationError):
        service.search("   ", project=pa)


def test_index_follows_updates_and_deletes(service: MemoryService, two_projects) -> None:
    pa, _ = two_projects
    service.update_entry("#1", EntryUpdate(title="Linker error fixed", content="relinked"), project=pa)
    assert service.search("OpenCV", project=pa).total == 0
    assert service.search("Linker", project=pa).total == 1
    service.delete_entry("#1", project=pa)
    assert service.search("Linker", project=pa).total == 0


def test_archived_projects_hidden_from_global_search(service: MemoryService, two_projects) -> None:
    pa, _ = two_projects
    service.unregister(project=pa)
    assert service.search("OpenCV", all_projects=True).total == 0
    assert service.search("OpenCV", all_projects=True, include_archived=True).total == 1
    assert service.search("OpenCV", project=pa).total == 1  # explicit project still searchable


def test_purge_cleans_index(service: MemoryService, two_projects, db) -> None:
    from sqlalchemy import text

    pa, _ = two_projects
    service.unregister(project=pa, purge=True)
    with db.read() as s:
        assert (
            s.execute(text("SELECT count(*) FROM search_index WHERE project_id = :p"), {"p": pa}).scalar()
            == 0
        )
        assert (
            s.execute(text("SELECT count(*) FROM search_map")).scalar()
            == s.execute(text("SELECT count(*) FROM search_index")).scalar()
        )
