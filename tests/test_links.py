"""Tags, links between entries and author normalisation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from pydantic import ValidationError as PydanticValidationError

from ohmypm.config import load_settings, normalize_author
from ohmypm.core.errors import NotFoundError, ValidationError
from ohmypm.core.schemas import EntryCreate, EntryUpdate, LinkIn
from ohmypm.core.service import MemoryService
from ohmypm.core.text import entry_mentions
from ohmypm.storage.database import Database, alembic_config


@pytest.fixture
def pid(service: MemoryService, workspace: Path) -> str:
    return service.register(workspace)[0].id


def add(service: MemoryService, pid: str, title: str, **kwargs) -> int:
    return service.add_entry(EntryCreate(title=title, **kwargs), project=pid).sequence


# ------------------------------------------------------------------- tags


def test_tags_are_normalised_and_validated(service: MemoryService, pid: str) -> None:
    entry = service.add_entry(
        EntryCreate(title="t", tags=["LVGL", " device:A0AC1 ", "相册", "lvgl"]), project=pid
    )
    assert entry.tags == ["device:a0ac1", "lvgl", "相册"]
    for bad in (["two words"], ["#x"], ["-x"], [""], ["x" * 65], [f"t{i}" for i in range(21)]):
        with pytest.raises(PydanticValidationError):
            EntryCreate(title="t", tags=bad)


def test_tag_edits_are_revisioned(service: MemoryService, pid: str) -> None:
    add(service, pid, "t", tags=["a", "b"])
    entry, changed = service.update_entry("#1", EntryUpdate(add_tags=["C"], remove_tags=["a"]), project=pid)
    assert changed and entry.tags == ["b", "c"] and entry.revision == 2
    _, changed = service.update_entry("#1", EntryUpdate(add_tags=["b"]), project=pid)
    assert not changed
    entry, _ = service.update_entry("#1", EntryUpdate(tags=["z"]), project=pid)
    assert entry.tags == ["z"]
    history = service.entry_history("#1", project=pid)
    assert [r.tags for r in history] == [["a", "b"], ["b", "c"]]
    assert service.restore_entry("#1", 1, project=pid).tags == ["a", "b"]


def test_filter_and_count_by_tag(service: MemoryService, pid: str) -> None:
    add(service, pid, "相册缩略图慢", tags=["lvgl", "gallery"], content="缩略图加载需要 3 秒")
    add(service, pid, "按钮布局", tags=["lvgl"], content="缩略图按钮")
    add(service, pid, "无标签", content="缩略图")
    assert [e.sequence for e in service.list_entries(project=pid, tags=["lvgl"]).items] == [1, 2]
    assert [e.sequence for e in service.list_entries(project=pid, tags=["LVGL", "gallery"]).items] == [1]
    assert service.list_entries(project=pid, tags=["none"]).total == 0
    hits = service.search("缩略图", project=pid, tags=["lvgl"]).items
    assert sorted(h.sequence for h in hits) == [1, 2]
    assert service.tags(project=pid) == [{"tag": "lvgl", "count": 2}, {"tag": "gallery", "count": 1}]


# ------------------------------------------------------------------ links


def test_entry_mentions_parsing() -> None:
    text = (
        "见#12的结论，修复 #9 和 (#53)。\n`#7` http://x/#8 &#123; ##4 a#5 #6abc\n```\n#99\n```\n# 标题\n#10"
    )
    assert entry_mentions(text) == {9, 10, 12, 53}


def test_mentions_follow_the_body(service: MemoryService, pid: str) -> None:
    add(service, pid, "one")
    add(service, pid, "two")
    third = service.add_entry(EntryCreate(title="three", content="see #1, #3 (self) and #99"), project=pid)
    assert [(link.kind, link.sequence) for link in third.links] == [("mentions", 1)]
    assert [link.sequence for link in service.get_entry("#1", project=pid).backlinks] == [3]

    updated, _ = service.update_entry("#3", EntryUpdate(content="now #2 instead"), project=pid)
    assert [link.sequence for link in updated.links] == [2]
    assert service.get_entry("#1", project=pid).backlinks == []
    # Restoring a revision restores its mentions.
    restored = service.restore_entry("#3", 1, project=pid)
    assert [link.sequence for link in restored.links] == [1]


def test_explicit_links_and_status_effects(service: MemoryService, pid: str) -> None:
    add(service, pid, "bug", type="issue")
    add(service, pid, "old howto", type="knowledge")
    add(service, pid, "background", type="decision")
    fix = service.add_entry(
        EntryCreate(
            title="fix",
            type="milestone",
            author="Codex",
            links=[
                LinkIn(target="#1", kind="fixes"),
                LinkIn(target="2", kind="supersedes"),
                LinkIn(target="#3"),
            ],
        ),
        project=pid,
    )
    assert [(link.kind, link.sequence) for link in fix.links] == [
        ("fixes", 1),
        ("supersedes", 2),
        ("relates", 3),
    ]
    bug = service.get_entry("#1", project=pid)
    assert bug.status == "resolved" and bug.revision == 2
    assert [(link.kind, link.sequence) for link in bug.backlinks] == [("fixes", 4)]
    assert service.entry_history("#1", project=pid)[0].status == "open"
    assert service.get_entry("#2", project=pid).status == "obsolete"

    # Re-adding is a no-op; removing keeps the statuses.
    _, changed = service.update_entry("#4", EntryUpdate(add_links=[LinkIn(target="#3")]), project=pid)
    assert not changed
    entry, changed = service.update_entry("#4", EntryUpdate(remove_links=["#1", "#3"]), project=pid)
    assert changed and [link.sequence for link in entry.links] == [2]
    assert service.get_entry("#1", project=pid).status == "resolved"

    with pytest.raises(ValidationError, match="needs an issue"):
        service.update_entry("#4", EntryUpdate(add_links=[LinkIn(target="#3", kind="fixes")]), project=pid)
    with pytest.raises(ValidationError, match="itself"):
        service.update_entry("#4", EntryUpdate(add_links=[LinkIn(target="#4")]), project=pid)
    with pytest.raises(NotFoundError):
        service.update_entry("#4", EntryUpdate(add_links=[LinkIn(target="#40")]), project=pid)


def test_links_stay_within_a_project_and_die_with_entries(
    service: MemoryService, pid: str, tmp_path: Path
) -> None:
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = service.register(other_root)[0].id
    add(service, other, "elsewhere")
    add(service, pid, "here", content="mentions #1 of this project only")
    with pytest.raises(NotFoundError):
        service.update_entry("#1", EntryUpdate(add_links=[LinkIn(target="#2")]), project=pid)
    assert service.get_entry("#1", project=other).backlinks == []

    add(service, pid, "target")
    service.update_entry("#1", EntryUpdate(add_links=[LinkIn(target="#2")]), project=pid)
    service.delete_entry("#2", project=pid)
    assert service.get_entry("#1", project=pid).links == []


def test_context_shows_tags_links_and_filters_by_tag(service: MemoryService, pid: str) -> None:
    add(service, pid, "缩略图慢", type="issue", tags=["lvgl"])
    add(service, pid, "预加载", type="milestone", tags=["lvgl"], links=[LinkIn(target="#1", kind="fixes")])
    add(service, pid, "部署脚本", type="artifact", tags=["deploy"], content="基于 #2")
    md = service.context(project=pid).markdown
    assert "- Tags in use: `lvgl` (2), `deploy` (1)" in md
    assert "_Links: fixes #1 · mentioned in #3_" in md
    assert "_Links: fixed by #2_" in md
    assert "tags: lvgl_" in md

    ctx = service.context(project=pid, tag="LVGL")
    assert "Filtered by tag `lvgl`: 2 record(s)" in ctx.markdown
    assert {e.sequence for s in ctx.sections for e in s.entries} == {1, 2}
    full = service.context(project=pid, mode="full", tag="deploy")
    assert full.pagination.total_entries == 1
    assert "No records tagged `nothing`" in service.context(project=pid, tag="nothing").markdown


# ---------------------------------------------------------------- authors


def test_author_normalisation(service: MemoryService, pid: str, settings) -> None:
    assert normalize_author("  Claude  Code ") == "claude-code"
    assert normalize_author("Codex") == "codex" and normalize_author("  ") is None
    entry = service.add_entry(EntryCreate(title="t", author="Claude"), project=pid)
    assert entry.author == "claude-code"
    _, _ = service.update_entry("#1", EntryUpdate(title="t2"), project=pid, changed_by="Antigravity")
    assert service.entry_history("#1", project=pid)[0].changed_by == "agy"
    assert service.list_entries(project=pid, author="CLAUDE").total == 1

    settings.config_dir.mkdir(parents=True, exist_ok=True)
    settings.config_file.write_text('[ohmypm]\nauthor = "LKP"\nauthor_aliases = { "Mr. Robot" = "robot" }\n')
    configured = MemoryService(load_settings(), service.db)
    assert configured.add_entry(EntryCreate(title="x"), project=pid).author == "lkp"
    assert configured.add_entry(EntryCreate(title="y", author="mr.  robot"), project=pid).author == "robot"


def test_authors_rewrite_keeps_update_times(service: MemoryService, pid: str) -> None:
    from sqlalchemy import update

    from ohmypm.storage.models import Entry

    add(service, pid, "a")
    add(service, pid, "b")
    with service.db.write() as s:  # Names written before normalisation existed.
        s.execute(update(Entry).values(author="Codex"))
    before = service.get_entry("#1", project=pid)
    rows = service.authors(project=pid)
    assert rows == [{"author": "Codex", "count": 2, "normalized": "codex"}]
    assert service.get_entry("#1", project=pid).author == "Codex"
    service.authors(project=pid, apply=True)
    after = service.get_entry("#1", project=pid)
    assert after.author == "codex"
    assert (after.updated_at, after.revision) == (before.updated_at, before.revision)


# -------------------------------------------------------------- migration


def test_migration_backfills_mentions(settings, tmp_path: Path) -> None:
    from ohmypm.core.service import MemoryService as Service

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(settings.db_path), "0001_initial")
    con = sqlite3.connect(settings.db_path)
    con.execute(
        "INSERT INTO projects (id, name, root_path, created_at, updated_at, next_sequence, metadata) "
        "VALUES ('p1', 'P', ?, '2026-01-01', '2026-01-01', 4, '{}')",
        (str(tmp_path),),
    )
    for seq, content in ((1, "first"), (2, "after #1, see `#3`"), (3, "#2 and #1 and #77")):
        con.execute(
            "INSERT INTO entries (id, project_id, sequence, type, title, content, revision, created_at, "
            "updated_at, metadata) VALUES (?, 'p1', ?, 'note', ?, ?, 1, '2026-01-01', '2026-01-01', '{}')",
            (f"e{seq}", seq, f"t{seq}", content),
        )
    con.commit()
    con.close()

    db = Database(settings)  # Upgrades to head.
    service = Service(settings, db)
    assert [link.sequence for link in service.get_entry("#1", project="p1").backlinks] == [2, 3]
    assert [link.sequence for link in service.get_entry("#3", project="p1").links] == [1, 2]
    assert service.get_entry("#1", project="p1").tags == []
    db.dispose()


def test_mcp_tags_and_links(service: MemoryService, workspace: Path) -> None:
    from tests.test_mcp import ok

    service.register(workspace)
    ws = str(workspace)
    ok(service, "pm_add_entry", workspace_path=ws, type="issue", title="bug", tags=["LVGL"])
    fix = ok(
        service,
        "pm_add_entry",
        workspace_path=ws,
        title="fix",
        links=[{"target": "#1", "kind": "fixes"}],
        author="Claude",
    )
    assert fix["links"][0]["sequence"] == 1 and fix["author"] == "claude-code"
    assert ok(service, "pm_get_entry", entry="#1", workspace_path=ws)["status"] == "resolved"
    updated = ok(
        service, "pm_update_entry", entry="#2", workspace_path=ws, add_tags=["ui"], remove_links=["#1"]
    )
    assert updated["changed"] and updated["entry"]["tags"] == ["ui"] and updated["entry"]["links"] == []
    listed = ok(service, "pm_list_entries", workspace_path=ws, tags=["lvgl"])
    assert [e["sequence"] for e in listed["items"]] == [1]
    ctx = ok(service, "pm_get_context", workspace_path=ws, tag="ui")
    assert "Filtered by tag `ui`" in ctx["markdown"]


def test_export_includes_tags_and_links(service: MemoryService, pid: str, tmp_path: Path) -> None:
    add(service, pid, "bug", type="issue", tags=["lvgl"])
    add(service, pid, "fix", links=[LinkIn(target="#1", kind="fixes")])
    from ohmypm.core.export import export_markdown

    result = export_markdown(service.db, service.settings, project_ids=[pid], output=tmp_path / "out")
    files = sorted(Path(result["path"]).rglob("entries/*.md"))
    first, second = (f.read_text() for f in files)
    assert 'tags: ["lvgl"]' in first
    assert json.dumps([{"kind": "fixes", "sequence": 1}]) in second
