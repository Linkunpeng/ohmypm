from __future__ import annotations

from pathlib import Path

import pytest

from ohmypm.core.errors import ConflictError, ValidationError
from ohmypm.core.schemas import SummaryUpdate
from ohmypm.core.service import MemoryService
from ohmypm.core.summaries import parse_summary_markdown, render_summary_markdown, section_key


@pytest.fixture
def project_id(service: MemoryService, workspace: Path) -> str:
    return service.register(workspace)[0].id


def test_empty_summary(service: MemoryService, project_id: str) -> None:
    summary = service.get_summary(project=project_id)
    assert summary.is_empty and summary.revision == 0 and summary.updated_at is None


def test_set_and_merge_summary(service: MemoryService, project_id: str) -> None:
    s1, changed = service.set_summary(
        SummaryUpdate(overview="Robot workspace", next_steps="- calibrate"),
        project=project_id,
        changed_by="codex",
    )
    assert changed and s1.revision == 1 and not s1.is_empty and s1.updated_by == "codex"
    s2, _ = service.set_summary(SummaryUpdate(known_issues="- OpenCV link error"), project=project_id)
    assert s2.overview == "Robot workspace" and s2.known_issues == "- OpenCV link error" and s2.revision == 2
    s3, changed = service.set_summary(SummaryUpdate(known_issues="- OpenCV link error"), project=project_id)
    assert not changed and s3.revision == 2
    s4, _ = service.set_summary(SummaryUpdate(overview="New"), project=project_id, replace=True)
    assert s4.overview == "New" and s4.known_issues == "" and s4.next_steps == ""

    history = service.summary_history(project=project_id)
    assert [h["revision"] for h in history] == [1, 2]  # snapshots of replaced versions
    restored = service.restore_summary(2, project=project_id)
    assert restored.known_issues == "- OpenCV link error" and restored.overview == "Robot workspace"


def test_summary_conflict(service: MemoryService, project_id: str) -> None:
    service.set_summary(SummaryUpdate(overview="a"), project=project_id)
    with pytest.raises(ConflictError):
        service.set_summary(SummaryUpdate(overview="b"), project=project_id, expected_revision=0)


def test_parse_markdown_sections_with_aliases() -> None:
    md = """# Robot_WS summary

## 项目简介
ROS2 机器人工作空间。

## 2. Architecture
- camera node
- planner

## 当前状态
相机驱动完成。

## Key Decisions
Use V4L2.

## 已知问题
- OpenCV 链接失败

## 下一步建议
- 标定相机
"""
    parsed = parse_summary_markdown(md)
    assert parsed == {
        "overview": "ROS2 机器人工作空间。",
        "architecture": "- camera node\n- planner",
        "current_state": "相机驱动完成。",
        "important_decisions": "Use V4L2.",
        "known_issues": "- OpenCV 链接失败",
        "next_steps": "- 标定相机",
    }


def test_parse_keeps_unknown_headings_and_code_fences() -> None:
    md = """Preamble text.

## Overview
Intro.

## Random Extra
kept here

## Next Steps
```markdown
## Overview
not a heading inside a fence
```
"""
    parsed = parse_summary_markdown(md)
    assert parsed["overview"] == "Preamble text.\n\nIntro.\n\n## Random Extra\nkept here"
    assert "## Overview" in parsed["next_steps"] and "not a heading" in parsed["next_steps"]
    assert set(parsed) == {"overview", "next_steps"}


def test_parse_requires_sections() -> None:
    with pytest.raises(ValidationError):
        parse_summary_markdown("just text without headings")


def test_render_roundtrip(service: MemoryService, project_id: str) -> None:
    service.set_summary(
        SummaryUpdate(
            overview="O",
            architecture="A\n\n```py\n## not heading\n```",
            current_state="C",
            important_decisions="D",
            known_issues="K",
            next_steps="N",
        ),
        project=project_id,
    )
    summary = service.get_summary(project=project_id)
    md = render_summary_markdown(summary, title="Robot")
    assert parse_summary_markdown(md) == {
        "overview": "O",
        "architecture": "A\n\n```py\n## not heading\n```",
        "current_state": "C",
        "important_decisions": "D",
        "known_issues": "K",
        "next_steps": "N",
    }


def test_set_summary_markdown_partial(service: MemoryService, project_id: str) -> None:
    service.set_summary(SummaryUpdate(overview="keep me"), project=project_id)
    summary, _ = service.set_summary_markdown("## Next Steps\n- ship it\n", project=project_id)
    assert summary.overview == "keep me" and summary.next_steps == "- ship it"


@pytest.mark.parametrize(
    ("heading", "key"),
    [
        ("Overview", "overview"),
        ("1. Known Issues", "known_issues"),
        ("下一步：", "next_steps"),
        ("current_state", "current_state"),
        ("Nonsense", None),
    ],
)
def test_section_key(heading: str, key: str | None) -> None:
    assert section_key(heading) == key
