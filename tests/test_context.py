from __future__ import annotations

from pathlib import Path

import pytest

from ohmypm.config import load_settings
from ohmypm.core.errors import ValidationError
from ohmypm.core.schemas import EntryCreate, EntryUpdate, SummaryUpdate
from ohmypm.core.service import MemoryService
from ohmypm.core.text import estimate_tokens, truncate_markdown


@pytest.fixture
def project_id(service: MemoryService, workspace: Path) -> str:
    return service.register(workspace, description="ROS2 robot workspace")[0].id


def _seed(service: MemoryService, pid: str) -> None:
    service.set_summary(
        SummaryUpdate(
            overview="Robot_WS 是一个 ROS2 机器人工作空间。",
            architecture="camera_node → perception → planner",
            current_state="相机驱动完成，正在做标定。",
            important_decisions="使用 V4L2 而不是 GStreamer。",
            known_issues="- 偶发丢帧",
            next_steps="- 完成相机标定\n- 接入 planner",
        ),
        project=pid,
    )
    service.add_entry(
        EntryCreate(type="milestone", title="完成相机驱动", content="已实现 V4L2 图像采集。"), project=pid
    )
    service.add_entry(
        EntryCreate(
            type="issue", title="OpenCV 链接失败", content="## 错误\nundefined reference\n## 已尝试\n- 重装"
        ),
        project=pid,
    )
    service.add_entry(EntryCreate(type="note", title="随手记录", content="普通记录"), project=pid)
    service.add_entry(
        EntryCreate(
            type="knowledge",
            title="猜测：USB 带宽不足",
            content="可能是带宽问题",
            metadata={"confidence": "hypothesis"},
        ),
        project=pid,
    )


def test_empty_project_context(service: MemoryService, project_id: str) -> None:
    ctx = service.context(project=project_id)
    assert ctx.stats["entry_count"] == 0
    assert "No project summary yet" in ctx.markdown
    assert "No records yet" in ctx.markdown
    assert ctx.budget.used_tokens <= ctx.budget.max_tokens


def test_brief_context_contents(service: MemoryService, project_id: str) -> None:
    _seed(service, project_id)
    ctx = service.context(project=project_id, mode="brief")
    md = ctx.markdown
    assert md.startswith("# Project context: Robot_WS")
    assert "ROS2 robot workspace" in md
    for needle in ("Robot_WS 是一个 ROS2", "相机驱动完成", "完成相机标定", "OpenCV 链接失败", "完成相机驱动"):
        assert needle in md
    assert "[issue · open]" in md
    assert "[knowledge · unverified]" in md
    # Section order: overview before open issues before next steps.
    assert md.index("## Overview") < md.index("## Open Issue Records") < md.index("## Next Steps")
    keys = [s.key for s in ctx.sections]
    assert "open_issues" in keys and "recent_important" in keys
    assert ctx.stats["open_issues"] == 1
    # An entry is not repeated in several sections.
    seqs = [e.sequence for s in ctx.sections for e in s.entries]
    assert len(seqs) == len(set(seqs))


def test_resolved_and_obsolete_entries(service: MemoryService, project_id: str) -> None:
    _seed(service, project_id)
    service.update_entry("#2", EntryUpdate(status="resolved"), project=project_id)
    service.update_entry("#4", EntryUpdate(status="obsolete"), project=project_id)
    ctx = service.context(project=project_id)
    assert ctx.stats["open_issues"] == 0
    assert not any(s.key == "open_issues" for s in ctx.sections)
    important = next(s for s in ctx.sections if s.key == "recent_important")
    assert 4 not in [e.sequence for e in important.entries]


def test_standard_includes_more_sections(service: MemoryService, project_id: str) -> None:
    _seed(service, project_id)
    for i in range(3):
        service.add_entry(
            EntryCreate(type="decision", title=f"决策 {i}", content="原因" * 10), project=project_id
        )
        service.add_entry(
            EntryCreate(type="artifact", title=f"工具 {i}", content="用法: run.sh"), project=project_id
        )
    brief = service.context(project=project_id, mode="brief")
    standard = service.context(project=project_id, mode="standard")
    brief_seqs = {e.sequence for s in brief.sections for e in s.entries}
    standard_seqs = {e.sequence for s in standard.sections for e in s.entries}
    assert brief_seqs < standard_seqs
    assert standard.budget.max_tokens == 8000


@pytest.mark.parametrize("mode", ["brief", "standard", "full"])
def test_budget_is_respected_with_many_records(service: MemoryService, project_id: str, mode: str) -> None:
    big = "这是一段很长的记录内容。Long content line.\n" * 400
    service.set_summary(SummaryUpdate(overview=big, current_state=big, next_steps=big), project=project_id)
    for i in range(300):
        service.add_entry(
            EntryCreate(
                type=["note", "issue", "milestone", "decision", "knowledge"][i % 5],
                title=f"记录 {i}",
                content=big if i % 7 == 0 else f"内容 {i}",
            ),
            project=project_id,
        )
    for max_tokens in (500, 3000):
        ctx = service.context(project=project_id, mode=mode, max_tokens=max_tokens)
        assert ctx.budget.used_tokens <= max_tokens, (mode, max_tokens, ctx.budget.used_tokens)
        assert ctx.budget.truncated
        assert "truncated" in ctx.markdown or "omitted" in ctx.markdown


def test_full_mode_pagination(service: MemoryService, project_id: str) -> None:
    for i in range(45):
        service.add_entry(EntryCreate(title=f"entry {i}", content=f"content {i}"), project=project_id)
    p1 = service.context(project=project_id, mode="full", page_size=20)
    assert p1.pagination.has_more and p1.pagination.next_page == 2
    records = next(s for s in p1.sections if s.key == "records")
    assert [e.sequence for e in records.entries][:2] == [45, 44]
    p3 = service.context(project=project_id, mode="full", page=3, page_size=20)
    records3 = next(s for s in p3.sections if s.key == "records")
    assert [e.sequence for e in records3.entries] == [5, 4, 3, 2, 1]
    assert not p3.pagination.has_more


def test_context_validation(service: MemoryService, project_id: str) -> None:
    with pytest.raises(ValidationError):
        service.context(project=project_id, mode="huge")
    with pytest.raises(ValidationError):
        service.context(project=project_id, max_tokens=10)


def test_truncate_markdown_closes_fences() -> None:
    text = "intro\n```python\n" + "\n".join(f"line_{i} = {i}" for i in range(500)) + "\n```\nafter"
    out, cut = truncate_markdown(text, 100)
    assert cut
    assert out.count("```") % 2 == 0
    assert "truncated" in out
    assert estimate_tokens(out) <= 130


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("你好世界") == 4
    assert estimate_tokens("abcd" * 10) == 10


def test_demote_headings_skips_fences() -> None:
    from ohmypm.core.text import demote_headings

    md = "# A\n## B\n```\n# not heading\n```\n###### F\n#hashtag"
    assert demote_headings(md, 3) == "#### A\n##### B\n```\n# not heading\n```\n###### F\n#hashtag"


def test_excerpt_strips_markdown_noise() -> None:
    from ohmypm.core.text import excerpt

    md = "## 完成内容\n\n相机 **V4L2**。\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```mermaid\nflowchart LR\n```\n\n```cpp\nx\n```\n\n![shot](ohmypm-asset://x) [link](http://a)"
    assert excerpt(md) == "完成内容 相机 V4L2。 [table] [diagram] [code] [image: shot] link"


def _age_entry(service: MemoryService, project_id: str, sequence: int, days: int) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from ohmypm.storage.models import Entry

    with service.db.write() as s:
        s.execute(
            update(Entry)
            .where(Entry.project_id == project_id, Entry.sequence == sequence)
            .values(updated_at=datetime.now(UTC) - timedelta(days=days))
        )


def test_stale_open_issues_are_listed_compactly(service: MemoryService, project_id: str) -> None:
    _seed(service, project_id)
    service.add_entry(
        EntryCreate(type="issue", title="旧问题：偶发重启", content="很长的排查过程\n" * 50),
        project=project_id,
    )
    _age_entry(service, project_id, 5, days=10)
    ctx = service.context(project=project_id)
    md = ctx.markdown
    assert ctx.stats["open_issues"] == 2 and ctx.stats["stale_open_issues"] == 1
    stale = next(s for s in ctx.sections if s.key == "stale_issues")
    assert [e.sequence for e in stale.entries] == [5] and stale.entries[0].content is None
    assert "- #5 旧问题：偶发重启 — opened " in md and "last updated 10d ago" in md
    assert "很长的排查过程" not in md
    # Shown once: not repeated as a full record in other sections.
    assert "### #5" not in md
    open_section = next(s for s in ctx.sections if s.key == "open_issues")
    assert [e.sequence for e in open_section.entries] == [2]
    assert md.index("## Open Issue Records") < md.index("## Stale Open Issues") < md.index("## Next Steps")
    assert service.status(service.get_project(project=project_id).root_path)["stale_open_issues"] == 1

    # Updating the issue makes it current again; 0 disables the check.
    service.update_entry("#5", EntryUpdate(content="仍在复现"), project=project_id)
    assert service.context(project=project_id).stats["stale_open_issues"] == 0
    _age_entry(service, project_id, 5, days=10)
    service.update_context_settings({"stale_issue_days": 0}, project=project_id)
    ctx = service.context(project=project_id)
    assert ctx.stats["stale_open_issues"] == 0
    assert not any(s.key == "stale_issues" for s in ctx.sections)


def test_context_settings_precedence(
    service: MemoryService, project_id: str, settings, tmp_path: Path
) -> None:
    opts = service.context_settings(project=project_id)
    assert opts.max_tokens == {"brief": 3000, "standard": 8000, "full": 20000}
    assert opts.stale_issue_days == 7 and opts.project_overrides == {}

    settings.config_dir.mkdir(parents=True, exist_ok=True)
    settings.config_file.write_text("[context]\nbrief_tokens = 4000\nstale_issue_days = 30\n")
    configured = MemoryService(load_settings(), service.db)
    opts = configured.context_settings(project=project_id)
    assert opts.max_tokens["brief"] == 4000 and opts.stale_issue_days == 30

    opts = configured.update_context_settings({"brief_tokens": 6000}, project=project_id)
    assert opts.max_tokens["brief"] == 6000 and opts.project_overrides == {"brief_tokens": 6000}
    assert configured.context(project=project_id).budget.max_tokens == 6000
    assert configured.context(project=project_id, max_tokens=1000).budget.max_tokens == 1000
    # Other project metadata is preserved.
    assert configured.get_project(project=project_id).metadata == {"context": {"brief_tokens": 6000}}

    opts = configured.update_context_settings({"brief_tokens": None}, project=project_id)
    assert opts.max_tokens["brief"] == 4000 and opts.project_overrides == {}
    assert "context" not in configured.get_project(project=project_id).metadata

    configured.update_context_settings({"standard_tokens": 9000}, project=project_id)
    assert configured.update_context_settings({}, reset=True, project=project_id).project_overrides == {}

    for bad in ({"brief_tokens": 100}, {"stale_issue_days": -1}, {"bogus": 1}):
        with pytest.raises(ValidationError):
            configured.update_context_settings(bad, project=project_id)


def test_summary_sections_cut_by_the_brief_budget(service: MemoryService, project_id: str) -> None:
    service.set_summary(SummaryUpdate(overview="短概述", current_state="- 状态\n" * 2000), project=project_id)
    ctx = service.context(project=project_id)
    cut = ctx.stats["summary_sections_cut"]
    assert [c["section"] for c in cut] == ["current_state"]
    assert cut[0]["tokens"] > cut[0]["shown_tokens"] > 0
    assert "- Summary sections cut off by the brief budget: Current State (~" in ctx.markdown
    assert ctx.budget.used_tokens <= ctx.budget.max_tokens
    # A larger budget shows it in full; full mode never reports cuts.
    assert service.context(project=project_id, max_tokens=20000).stats["summary_sections_cut"] == []
    assert service.context(project=project_id, mode="full").stats["summary_sections_cut"] == []
    assert service.summary_cut(project=project_id) == cut

    service.set_summary(SummaryUpdate(current_state="- 状态"), project=project_id)
    ctx = service.context(project=project_id)
    assert ctx.stats["summary_sections_cut"] == [] and "cut off" not in ctx.markdown


def test_summary_writers_report_cut_sections(
    service: MemoryService, project_id: str, workspace: Path
) -> None:
    from typer.testing import CliRunner

    from ohmypm.cli.common import reset_service
    from ohmypm.cli.main import app
    from tests.test_mcp import ok

    long_state = "- 状态\n" * 2000
    reset_service()
    result = CliRunner().invoke(
        app,
        ["summary", "set", "--cwd", str(workspace), "--section", "Current State", "--content", long_state],
    )
    assert result.exit_code == 0, result.output
    assert "Note: `ohmypm context` cuts off Current State" in result.output

    got = ok(service, "pm_update_summary", project=project_id, next_steps="- 下一步")
    assert got["summary_sections_cut"][0]["section"] == "current_state" and "Condense" in got["hint"]
    got = ok(service, "pm_update_summary", project=project_id, current_state="- 简短状态")
    assert "summary_sections_cut" not in got


def test_old_record_commits_setting(service: MemoryService, project_id: str, settings) -> None:
    assert service.context_settings(project=project_id).old_record_commits == 20
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    settings.config_file.write_text("[context]\nold_record_commits = 50\n")
    configured = MemoryService(load_settings(), service.db)
    assert configured.context_settings(project=project_id).old_record_commits == 50
    opts = configured.update_context_settings({"old_record_commits": 5}, project=project_id)
    assert opts.old_record_commits == 5 and opts.project_overrides == {"old_record_commits": 5}
    with pytest.raises(ValidationError):
        configured.update_context_settings({"old_record_commits": -1}, project=project_id)
