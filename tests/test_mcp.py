from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from ohmypm.core.service import MemoryService
from ohmypm.mcp.server import build_server
from tests.conftest import tree_snapshot
from tests.test_assets import make_png

EXPECTED_TOOLS = {
    "pm_get_status",
    "pm_list_projects",
    "pm_get_project",
    "pm_get_context",
    "pm_get_summary",
    "pm_update_summary",
    "pm_add_entry",
    "pm_list_entries",
    "pm_get_entry",
    "pm_update_entry",
    "pm_search",
    "pm_register_asset",
}


def call(service: MemoryService, tool: str, args: dict) -> tuple[bool, object]:
    async def go():
        async with Client(build_server(service)) as client:
            result = await client.call_tool(tool, args)
            if result.is_error:
                return True, json.loads(result.content[0].text)
            return False, result.structured_content

    return asyncio.run(go())


def ok(service: MemoryService, tool: str, **args) -> dict:
    is_error, data = call(service, tool, args)
    assert not is_error, data
    return data  # type: ignore[return-value]


def error(service: MemoryService, tool: str, **args) -> dict:
    is_error, data = call(service, tool, args)
    assert is_error, data
    return data["error"]  # type: ignore[index]


def test_tool_list_and_schemas(service: MemoryService) -> None:
    async def go():
        async with Client(build_server(service)) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(go())}
    assert set(tools) == EXPECTED_TOOLS
    for tool in tools.values():
        assert tool.description
        assert tool.input_schema["type"] == "object"
    add = tools["pm_add_entry"].input_schema
    assert add["required"] == ["title"]
    assert "workspace_path" in add["properties"] and "project" in add["properties"]
    assert tools["pm_get_status"].input_schema["required"] == ["workspace_path"]


def test_read_write_flow(service: MemoryService, workspace: Path) -> None:
    before = tree_snapshot(workspace)
    service.register(workspace)
    ws = str(workspace / "src" / "camera")
    status = ok(service, "pm_get_status", workspace_path=ws)
    assert status["registered"] is True

    entry = ok(
        service,
        "pm_add_entry",
        workspace_path=ws,
        type="issue",
        title="OpenCV 链接失败",
        content="## 错误\nundefined reference",
        author="claude",
        metadata={"confidence": "hypothesis"},
    )
    assert entry["sequence"] == 1 and entry["source"] == "mcp" and entry["status"] == "open"

    listed = ok(service, "pm_list_entries", workspace_path=ws)
    assert listed["total"] == 1 and listed["items"][0]["content"] is None
    full = ok(service, "pm_get_entry", entry="#1", workspace_path=ws)
    assert full["content"].startswith("## 错误")

    updated = ok(
        service,
        "pm_update_entry",
        entry="1",
        workspace_path=ws,
        status="resolved",
        append_content="Fix: 链接顺序",
        metadata={"files": ["CMakeLists.txt"]},
    )
    assert updated["changed"] and updated["entry"]["status"] == "resolved"
    assert updated["entry"]["content"].endswith("Fix: 链接顺序")
    assert updated["entry"]["metadata"] == {"confidence": "hypothesis", "files": ["CMakeLists.txt"]}

    summary = ok(
        service,
        "pm_update_summary",
        workspace_path=ws,
        markdown="## Overview\nROS2 机器人\n## Next Steps\n- 标定",
        author="claude",
    )
    assert summary["changed"] and summary["summary"]["overview"] == "ROS2 机器人"
    partial = ok(service, "pm_update_summary", workspace_path=ws, known_issues="- 丢帧")
    assert partial["summary"]["overview"] == "ROS2 机器人" and partial["summary"]["known_issues"] == "- 丢帧"
    got = ok(service, "pm_get_summary", workspace_path=ws)
    assert "## Known Issues" in got["markdown"]

    ctx = ok(service, "pm_get_context", workspace_path=ws)
    assert "ROS2 机器人" in ctx["markdown"] and "OpenCV" in ctx["markdown"]
    structured = ok(service, "pm_get_context", workspace_path=ws, mode="standard", output="json")
    assert structured["mode"] == "standard" and structured["sections"]

    hits = ok(service, "pm_search", workspace_path=ws, query="链接失败")
    assert hits["total"] == 1
    assert ok(service, "pm_search", query="链接失败", all_projects=True)["total"] == 1

    projects = ok(service, "pm_list_projects")
    assert projects["projects"][0]["name"] == "Robot_WS"
    assert ok(service, "pm_get_project", project="Robot_WS")["entry_count"] == 1
    assert tree_snapshot(workspace) == before


def test_assets_via_mcp(service: MemoryService, workspace: Path, tmp_path: Path) -> None:
    service.register(workspace)
    ws = str(workspace)
    b64 = base64.b64encode(make_png()).decode()
    asset = ok(service, "pm_register_asset", workspace_path=ws, content_base64=b64, filename="shot.png")
    assert asset["markdown"].startswith("![shot.png](ohmypm-asset://")
    file = tmp_path / "log.txt"
    file.write_text("编译日志", encoding="utf-8")
    text_asset = ok(service, "pm_register_asset", workspace_path=ws, file_path=str(file))
    assert text_asset["mime_type"] == "text/plain"
    assert (
        error(service, "pm_register_asset", workspace_path=ws, file_path="relative.png")["code"]
        == "validation_error"
    )
    assert error(service, "pm_register_asset", workspace_path=ws, content_base64="!!", filename="x.png")[
        "code"
    ] == ("validation_error")
    assert error(service, "pm_register_asset", workspace_path=ws)["code"] == "validation_error"


def test_errors_and_validation(service: MemoryService, workspace: Path, tmp_path: Path) -> None:
    service.register(workspace)
    assert error(service, "pm_add_entry", title="x")["code"] == "validation_error"  # no scope
    assert error(service, "pm_add_entry", title="x", workspace_path="rel/path")["code"] == "validation_error"
    err = error(service, "pm_add_entry", title="x", workspace_path=str(tmp_path / "unregistered"))
    assert err["code"] == "project_not_registered"
    assert error(service, "pm_add_entry", title="x", project="nope")["code"] == "not_found"
    assert error(service, "pm_add_entry", title="", project="Robot_WS")["code"] == "validation_error"
    bad_type = error(service, "pm_add_entry", title="x", type="bogus", project="Robot_WS")
    assert bad_type["code"] == "validation_error" and "milestone" in bad_type["details"]["allowed"]
    assert error(service, "pm_get_entry", entry="#5", project="Robot_WS")["code"] == "not_found"
    assert error(service, "pm_update_summary", project="Robot_WS")["code"] == "validation_error"
    # Schema-level validation happens before the tool runs.
    schema_err = error(service, "pm_get_context", project="Robot_WS", mode="huge")
    assert schema_err["code"] == "validation_error" and "mode" in schema_err["message"]
    status = ok(service, "pm_get_status", workspace_path=str(tmp_path))
    assert status["registered"] is False


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_stdio_server_subprocess(workspace: Path, settings, mode: str) -> None:
    """`ohmypm mcp` speaks MCP over stdio and ignores its own working directory."""
    exe = Path(sys.executable).with_name("ohmypm")
    MemoryService(settings).register(workspace)
    env = {k: v for k, v in os.environ.items()}

    async def go():
        transport = StdioServerParameters(command=str(exe), args=["mcp"], env=env, cwd="/")
        async with Client(transport, mode=mode) as client:
            tools = (await client.list_tools()).tools
            status = await client.call_tool("pm_get_status", {"workspace_path": str(workspace / "src")})
            added = await client.call_tool(
                "pm_add_entry", {"workspace_path": str(workspace), "title": "via stdio", "type": "milestone"}
            )
            return {t.name for t in tools}, status.structured_content, added.structured_content

    names, status, added = asyncio.run(go())
    assert names == EXPECTED_TOOLS
    assert status["registered"] is True
    assert added["sequence"] == 1


@pytest.mark.parametrize("tool", sorted(EXPECTED_TOOLS))
def test_every_tool_has_documented_parameters(service: MemoryService, tool: str) -> None:
    async def go():
        async with Client(build_server(service)) as client:
            return {t.name: t for t in (await client.list_tools()).tools}[tool]

    schema = asyncio.run(go()).input_schema
    for name, prop in schema["properties"].items():
        assert prop.get("description") or name in ("limit", "offset"), (tool, name)
