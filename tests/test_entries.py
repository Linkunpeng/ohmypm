from __future__ import annotations

import multiprocessing as mp
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ohmypm.config import load_settings
from ohmypm.core.errors import ConflictError, NotFoundError, ValidationError
from ohmypm.core.schemas import EntryCreate, EntryUpdate
from ohmypm.core.service import MemoryService


@pytest.fixture
def project_id(service: MemoryService, workspace: Path) -> str:
    return service.register(workspace)[0].id


def test_create_entry(service: MemoryService, project_id: str) -> None:
    entry = service.add_entry(
        EntryCreate(
            type="milestone",
            title="完成相机驱动",
            content="已实现 V4L2 图像采集，编译测试通过。",
            author="codex",
            source="cli",
        ),
        project=project_id,
    )
    assert entry.sequence == 1
    assert entry.type == "milestone"
    assert entry.author == "codex" and entry.source == "cli"
    assert entry.status is None
    assert entry.revision == 1
    project = service.get_project(project=project_id)
    assert project.last_activity_at is not None


def test_issue_defaults_to_open(service: MemoryService, project_id: str) -> None:
    entry = service.add_entry(EntryCreate(type="issue", title="OpenCV 链接失败"), project=project_id)
    assert entry.status == "open"


def test_all_builtin_types_and_unknown_type(service: MemoryService, project_id: str) -> None:
    for t in ("note", "milestone", "issue", "decision", "knowledge", "artifact"):
        assert service.add_entry(EntryCreate(type=t, title=t), project=project_id).type == t
    with pytest.raises(ValidationError) as exc:
        service.add_entry(EntryCreate(type="milstone", title="typo"), project=project_id)
    assert "milestone" in exc.value.details["allowed"]


def test_extra_types_from_config(tmp_path: Path, workspace: Path) -> None:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "config.toml").write_text(
        'server_url = "foreign"\n[entries]\nextra_types = ["experiment", "BAD TYPE"]\n'
    )
    service = MemoryService(load_settings())
    pid = service.register(workspace)[0].id
    assert service.add_entry(EntryCreate(type="experiment", title="x"), project=pid).type == "experiment"
    assert "bad type" not in service.settings.entry_types


def test_input_validation() -> None:
    with pytest.raises(ValueError):
        EntryCreate(title="   ")
    with pytest.raises(ValueError):
        EntryCreate(title="x" * 501)
    with pytest.raises(ValueError):
        EntryCreate(title="x", type="Not Valid")
    with pytest.raises(ValueError):
        EntryCreate(title="x", status="done")
    with pytest.raises(ValueError):
        EntryCreate(title="x", metadata={"blob": "x" * 70_000})
    assert EntryCreate(title="  multi\nline   title ").title == "multi line title"


def test_chinese_markdown_and_long_text_roundtrip(service: MemoryService, project_id: str) -> None:
    content = (
        "# 问题描述\n\n链接 `libopencv_core.so` 时报错：\n\n```bash\nundefined reference to `cv::Mat::Mat()`\n```\n\n"
        "| 尝试 | 结果 |\n|---|---|\n| 重新安装 | 失败 |\n\n$$E=mc^2$$\n\n- [x] 已确认\n- [ ] 待验证 😀\n"
    )
    long_content = content + ("长文本测试 Long text. " * 60_000)
    entry = service.add_entry(
        EntryCreate(type="issue", title="OpenCV 链接失败", content=long_content), project=project_id
    )
    loaded = service.get_entry(str(entry.sequence), project=project_id)
    assert loaded.content == long_content
    assert len(loaded.content) > 1_000_000


def test_lookup_by_sequence_and_id(service: MemoryService, project_id: str) -> None:
    entry = service.add_entry(EntryCreate(title="a"), project=project_id)
    assert service.get_entry("#1", project=project_id).id == entry.id
    assert service.get_entry("1", project=project_id).id == entry.id
    assert service.get_entry(entry.id).id == entry.id
    assert service.get_entry(entry.id[:8]).id == entry.id
    with pytest.raises(NotFoundError):
        service.get_entry("#99", project=project_id)
    with pytest.raises(ValidationError):
        service.get_entry("#1")  # sequence needs a project


def test_update_keeps_revisions(service: MemoryService, project_id: str) -> None:
    entry = service.add_entry(EntryCreate(type="issue", title="bug", content="v1"), project=project_id)
    updated, changed = service.update_entry(
        entry.id, EntryUpdate(content="v2", status="resolved"), changed_by="me"
    )
    assert changed and updated.revision == 2 and updated.status == "resolved" and updated.content == "v2"
    same, changed = service.update_entry(entry.id, EntryUpdate(content="v2"))
    assert not changed and same.revision == 2
    history = service.entry_history(entry.id)
    assert [(h.revision, h.content, h.status) for h in history] == [(1, "v1", "open")]

    restored = service.restore_entry(entry.id, 1)
    assert restored.content == "v1" and restored.status == "open" and restored.revision == 3
    assert len(service.entry_history(entry.id)) == 2

    cleared, _ = service.update_entry(entry.id, EntryUpdate(clear_status=True))
    assert cleared.status is None


def test_optimistic_concurrency(service: MemoryService, project_id: str) -> None:
    entry = service.add_entry(EntryCreate(title="a"), project=project_id)
    service.update_entry(entry.id, EntryUpdate(content="x"), expected_revision=1)
    with pytest.raises(ConflictError):
        service.update_entry(entry.id, EntryUpdate(content="y"), expected_revision=1)


def test_delete_keeps_recoverable_copy(service: MemoryService, project_id: str) -> None:
    entry = service.add_entry(EntryCreate(title="to delete", content="important"), project=project_id)
    service.delete_entry(entry.id, changed_by="tester")
    with pytest.raises(NotFoundError):
        service.get_entry(entry.id)
    deleted = service.deleted_entries(project=project_id)
    assert len(deleted) == 1 and deleted[0].content == "important" and deleted[0].reason == "delete"


def test_sequences_are_monotonic_and_never_reused(service: MemoryService, project_id: str) -> None:
    seqs = [service.add_entry(EntryCreate(title=f"e{i}"), project=project_id).sequence for i in range(5)]
    assert seqs == [1, 2, 3, 4, 5]
    service.delete_entry(service.get_entry("#5", project=project_id).id)
    assert service.add_entry(EntryCreate(title="new"), project=project_id).sequence == 6


def test_sequences_are_per_project(service: MemoryService, project_id: str, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    other_id = service.register(other)[0].id
    service.add_entry(EntryCreate(title="a"), project=project_id)
    assert service.add_entry(EntryCreate(title="b"), project=other_id).sequence == 1


def test_timeline_order_and_filters(service: MemoryService, project_id: str) -> None:
    for i, t in enumerate(["note", "issue", "milestone", "note", "decision"]):
        service.add_entry(EntryCreate(type=t, title=f"{t} {i}", content=f"body {i} 相机"), project=project_id)
    page = service.list_entries(project=project_id)
    assert [e.sequence for e in page.items] == [1, 2, 3, 4, 5]
    assert page.items[0].content is None and page.items[0].excerpt
    desc = service.list_entries(project=project_id, order="desc", limit=2)
    assert [e.sequence for e in desc.items] == [5, 4] and desc.total == 5
    assert service.list_entries(project=project_id, types=["note"]).total == 2
    assert service.list_entries(project=project_id, statuses=["open"]).total == 1
    assert service.list_entries(project=project_id, query="相机 body").total == 5
    assert service.list_entries(project=project_id, query="decision").total == 1
    future = datetime.now(UTC) + timedelta(days=1)
    assert service.list_entries(project=project_id, since=future).total == 0
    assert service.list_entries(project=project_id, until=future).total == 5
    with pytest.raises(ValidationError):
        service.list_entries(project=project_id, limit=0)


def test_like_wildcards_are_literal(service: MemoryService, project_id: str) -> None:
    service.add_entry(EntryCreate(title="100% done"), project=project_id)
    service.add_entry(EntryCreate(title="1000 done"), project=project_id)
    assert service.list_entries(project=project_id, query="100%").total == 1


def _writer(data_dir: str, config_dir: str, project_id: str, count: int, tag: int) -> None:
    from ohmypm.config import load_settings as _load
    from ohmypm.core.schemas import EntryCreate as _EC
    from ohmypm.core.service import MemoryService as _MS

    svc = _MS(_load(Path(data_dir), Path(config_dir)))
    for i in range(count):
        svc.add_entry(_EC(title=f"proc {tag} entry {i}"), project=project_id)


def test_concurrent_writers_get_unique_sequences(service: MemoryService, project_id: str, settings) -> None:
    ctx = mp.get_context("spawn")
    procs = [
        ctx.Process(
            target=_writer, args=(str(settings.data_dir), str(settings.config_dir), project_id, 25, n)
        )
        for n in range(6)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(120)
        assert p.exitcode == 0
    page = service.list_entries(project=project_id, limit=500)
    assert page.total == 150
    assert sorted(e.sequence for e in page.items) == list(range(1, 151))


def test_all_digit_id_prefix(service: MemoryService, project_id: str, db) -> None:
    from ohmypm.storage.models import Entry

    entry = service.add_entry(EntryCreate(title="digits"), project=project_id)
    with db.write() as s:
        s.execute(
            Entry.__table__.update()
            .where(Entry.id == entry.id)
            .values(id="12345678-0000-4000-8000-000000000000")
        )
    assert service.get_entry("12345678").title == "digits"
    assert service.get_entry("12345678", project=project_id).title == "digits"
    assert service.get_entry("1", project=project_id).title == "digits"
