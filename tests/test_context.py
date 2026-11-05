from __future__ import annotations

from pathlib import Path

import pytest

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
