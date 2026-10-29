"""Phase 2 acceptance: agent A records progress over MCP; agent B resumes from structured context."""

import uuid
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tests.conftest import ADMIN_TOKEN, AGENT_TOKEN, RUNNER_TOKEN, LiveServer

EXPECTED_TOOLS = {
    "pm_bootstrap",
    "pm_list_projects",
    "pm_get_project",
    "pm_list_tasks",
    "pm_get_task",
    "pm_create_task",
    "pm_update_task",
    "pm_complete_task",
    "pm_checkpoint",
    "pm_get_context",
    "pm_manage_decision",
    "pm_knowledge",
    "pm_register_artifact",
    "pm_list_artifacts",
    "pm_search",
    "pm_list_runs",
    "pm_get_run",
    "pm_dispatch_task",
    "pm_cancel_run",
    "pm_resume_task",
}


def mcp_client(server: LiveServer, token: str) -> Client:  # type: ignore[type-arg]
    return Client(f"{server.url}/mcp", auth=token)


async def call(client: Client, tool: str, args: dict[str, Any] | None = None) -> Any:  # type: ignore[type-arg]
    result = await client.call_tool(tool, args or {})
    return (
        result.structured_content.get("result", result.structured_content) if result.structured_content else result.data
    )


async def test_mcp_requires_auth(live_server: LiveServer) -> None:
    async with httpx.AsyncClient() as http:
        r = await http.post(
            f"{live_server.url}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert r.status_code == 401
    with pytest.raises(Exception):  # noqa: B017 - transport-level auth failure
        async with mcp_client(live_server, RUNNER_TOKEN) as c:
            await c.list_tools()


async def test_agent_handoff_over_mcp(live_server: LiveServer) -> None:
    project_id = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=live_server.url, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}) as admin:
        r = await admin.post("/api/projects", json={"id": project_id, "name": "Handoff demo"})
        assert r.status_code == 201

    # ---- Agent A
    async with mcp_client(live_server, AGENT_TOKEN) as a:
        names = {t.name for t in await a.list_tools()}
        assert EXPECTED_TOOLS <= names
        boot = await call(a, "pm_bootstrap", {"project_id": project_id, "cwd": "/w/demo", "host_id": "h1"})
        assert boot["project"]["id"] == project_id
        workspace_id = boot["workspace"]["id"]
        task = await call(
            a,
            "pm_create_task",
            {
                "raw_request": "Make the parser handle unicode",
                "workspace_id": workspace_id,
                "acceptance_criteria": ["unicode tests pass"],
                "idempotency_key": "agent-a-1",
            },
        )
        again = await call(
            a,
            "pm_create_task",
            {
                "raw_request": "Make the parser handle unicode",
                "workspace_id": workspace_id,
                "acceptance_criteria": ["unicode tests pass"],
                "idempotency_key": "agent-a-1",
            },
        )
        assert again["id"] == task["id"], "idempotent MCP create"
        await call(a, "pm_update_task", {"task_id": task["id"], "status": "in_progress"})
        await call(
            a,
            "pm_checkpoint",
            {
                "task_id": task["id"],
                "summary": "Tokenizer fixed; normalizer still breaks on combining marks",
                "completed": ["tokenizer handles UTF-8"],
                "remaining": ["NFC normalization"],
                "attempts": [{"action": "use str.casefold", "result": "breaks Turkish i", "conclusion": "revert"}],
                "findings": [{"statement": "NFKC changes ligatures", "kind": "verified", "evidence": "test_ligature"}],
                "relevant_files": ["parser/normalize.py"],
                "next_steps": ["apply NFC before tokenizing"],
                "verification": [{"command": "pytest tests/unicode", "result": "2 failed", "passed": False}],
            },
        )
        decision = await call(
            a,
            "pm_manage_decision",
            {
                "action": "create",
                "task_id": task["id"],
                "question": "Drop Python 3.11 support?",
                "options": [{"key": "yes", "label": "Yes"}, {"key": "no", "label": "No"}],
                "blocking": False,
            },
        )
        with pytest.raises(ToolError, match="only the user"):
            await call(
                a, "pm_manage_decision", {"action": "resolve", "decision_id": decision["id"], "selected_option": "yes"}
            )
        with pytest.raises(ToolError, match="acceptance_not_met"):
            await call(a, "pm_complete_task", {"task_id": task["id"], "summary": "not yet"})

    # ---- Agent B (fresh session, different client) resumes
    async with mcp_client(live_server, AGENT_TOKEN) as b:
        boot = await call(b, "pm_bootstrap", {"project_id": project_id})
        assert [t["id"] for t in boot["open_tasks"]] == [task["id"]]
        ctx = await call(b, "pm_get_context", {"task_id": task["id"], "mode": "standard"})
        md = ctx["markdown"]
        assert "Make the parser handle unicode" in md
        assert "apply NFC before tokenizing" in md
        assert "breaks Turkish i" in md, "failed attempts are carried over"
        assert "[verified] NFKC changes ligatures" in md
        assert ctx["data"]["latest_checkpoint"]["remaining"] == ["NFC normalization"]
        hits = await call(b, "pm_search", {"query": "unicode"})
        assert any(h["id"] == task["id"] for h in hits)
        art = await call(
            b,
            "pm_register_artifact",
            {"name": "parser-wheel", "storage_uri": "dist/parser.whl", "type": "library", "task_id": task["id"]},
        )
        assert art["task_id"] == task["id"]
        done = await call(
            b,
            "pm_complete_task",
            {
                "task_id": task["id"],
                "summary": "NFC applied, all tests green",
                "results": [{"criterion": "unicode tests pass", "passed": True, "evidence": "pytest: 14 passed"}],
            },
        )
        assert done["status"] == "completed"
        with pytest.raises(ToolError, match="dispatch_depth_exceeded"):
            await call(b, "pm_dispatch_task", {"task_id": task["id"], "agent_type": "claude"})
