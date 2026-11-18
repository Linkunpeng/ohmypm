"""Similar records: tokenisation, scoring, filters and the CLI / MCP / HTTP entry points."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ohmypm.core.errors import ValidationError
from ohmypm.core.schemas import EntryCreate, EntryUpdate, LinkIn
from ohmypm.core.service import MemoryService
from ohmypm.core.similar import terms


@pytest.fixture
def pid(service: MemoryService, workspace: Path) -> str:
    pid = service.register(workspace)[0].id
    records = [
        (
            "issue",
            "A0AC1 ADB 无法连接：USB 枚举失败后主机端口放弃",
            "dmesg: device descriptor read/64, error -71",
            ["device:a0ac1"],
        ),
        (
            "issue",
            "A0AC1 手机热点连接短暂断开及板端重启",
            "热点断开 30 秒后板端重启。",
            ["device:a0ac1", "wifi"],
        ),
        ("issue", "TTS 遇到英文字母 Q 时整段合成失败", "回答里带字母 Q，整段没有播报。", []),
        ("milestone", "A0AC1 部署 ai-assistant v3.5.0", "部署完成，真机验证通过。", ["device:a0ac1"]),
        ("milestone", "LVGL 相册缩略图与后台预加载", "相册打开时预加载缩略图。", ["lvgl"]),
    ]
    for type_, title, content, tags in records:
        service.add_entry(EntryCreate(type=type_, title=title, content=content, tags=tags), project=pid)
    return pid


def test_terms_split_words_versions_and_cjk_bigrams() -> None:
    got = terms("A0AC1SN14 部署 ai-assistant v3.5.0：USB 枚举失败（重启）")
    assert {"a0ac1sn14", "ai-assistant", "v3.5.0", "usb", "部署", "枚举", "举失", "失败", "重启"} <= set(got)
    assert "：" not in "".join(got) and "（" not in "".join(got)
    assert terms("单") == {"单": 1}
    assert terms("a I") == {}  # one-letter Latin words are noise


def test_draft_finds_the_matching_issue_first(service: MemoryService, pid: str) -> None:
    hits = service.similar_entries(title="USB 枚举失败，ADB 连不上", project=pid)
    assert hits[0].sequence == 1
    assert hits[0].body_score is None and hits[0].title_score == hits[0].score

    hits = service.similar_entries(
        title="手机热点断开后板子自动重启", content="热点断开后板端重启", tags=["wifi"], project=pid
    )
    assert hits[0].sequence == 2
    assert hits[0].shared_tags == ["wifi"] and hits[0].body_score is not None

    # A new topic matches nothing above the default threshold.
    assert service.similar_entries(title="LVGL 界面增加录像按钮的快捷键", project=pid, types=["issue"]) == []


def test_similar_to_existing_entry(service: MemoryService, pid: str) -> None:
    service.add_entry(
        EntryCreate(type="issue", title="USB 枚举失败，ADB 再次连不上", links=[LinkIn(target="#1")]),
        project=pid,
    )
    hits = service.similar_entries("#6", project=pid, min_score=0)
    assert hits[0].sequence == 1 and hits[0].linked is True
    assert all(h.sequence != 6 for h in hits)
    # The source's own values can be overridden.
    hits = service.similar_entries("#6", title="TTS 字母 Q 合成失败", project=pid)
    assert hits[0].sequence == 3


def test_filters_and_obsolete(service: MemoryService, pid: str) -> None:
    hits = service.similar_entries(title="A0AC1 部署 USB", project=pid, types=["milestone"], min_score=0)
    assert {h.type for h in hits} == {"milestone"}
    service.update_entry("#1", EntryUpdate(status="obsolete"), project=pid)
    title = "ADB 无法连接 USB 枚举失败"
    assert all(h.sequence != 1 for h in service.similar_entries(title=title, project=pid))
    assert service.similar_entries(title=title, project=pid, include_obsolete=True)[0].sequence == 1
    assert service.similar_entries(title=title, project=pid, statuses=["obsolete"])[0].sequence == 1


def test_validation(service: MemoryService, pid: str) -> None:
    with pytest.raises(ValidationError):
        service.similar_entries(project=pid)
    with pytest.raises(ValidationError):
        service.similar_entries(title="x", project=pid, limit=0)
    with pytest.raises(ValidationError):
        service.similar_entries(title="x")


def test_cli_similar(pid: str, workspace: Path) -> None:
    from typer.testing import CliRunner

    from ohmypm.cli.common import reset_service
    from ohmypm.cli.main import app

    reset_service()
    runner = CliRunner()
    result = runner.invoke(
        app, ["log", "similar", "--cwd", str(workspace), "-t", "USB 枚举失败 ADB", "-T", "issue"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0].split()[1] == "#1"
    result = runner.invoke(
        app, ["log", "similar", "1", "--cwd", str(workspace), "--min-score", "0", "--json"]
    )
    items = json.loads(result.output)["items"]
    assert items and all(i["sequence"] != 1 for i in items)
    result = runner.invoke(app, ["log", "similar", "--cwd", str(workspace), "-t", "完全无关的标题 zzz"])
    assert "No similar records." in result.output


def test_mcp_and_http_similar(service: MemoryService, pid: str, workspace: Path) -> None:
    from tests.test_mcp import ok

    got = ok(service, "pm_find_similar", workspace_path=str(workspace), title="热点断开 板端重启")
    assert got["items"][0]["sequence"] == 2
    got = ok(service, "pm_find_similar", project=pid, entry="#4", min_score=0)
    assert all(i["sequence"] != 4 for i in got["items"])

    from fastapi.testclient import TestClient

    from ohmypm.api.app import create_app

    client = TestClient(create_app(service, token=None), base_url="http://127.0.0.1:8737")
    entry_id = service.get_entry("#1", project=pid).id
    res = client.get(f"/api/entries/{entry_id}/similar", params={"min_score": 0, "type": "issue"})
    assert res.status_code == 200, res.text
    assert {h["type"] for h in res.json()} == {"issue"}
    res = client.post(f"/api/projects/{pid}/similar", json={"title": "TTS 字母 Q 合成失败"})
    assert res.status_code == 200 and res.json()[0]["sequence"] == 3
