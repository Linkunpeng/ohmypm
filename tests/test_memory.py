"""Phase 2: sessions, checkpoints, context builder, decisions, knowledge, artifacts."""

import httpx
import pytest
from sqlalchemy import text

from ohmypm.db import Database
from ohmypm.services.context import estimate_tokens
from tests.conftest import create_project, create_task, create_workspace


async def _checkpoint(client: httpx.AsyncClient, task_id: str, **body: object) -> dict:
    r = await client.post(f"/api/tasks/{task_id}/checkpoints", json={"summary": "progress", **body})
    assert r.status_code == 201, r.text
    return r.json()


async def test_checkpoint_updates_task_state(client: httpx.AsyncClient) -> None:
    task = await create_task(client, "Port driver")
    cp = await _checkpoint(
        client,
        task["id"],
        summary="Driver compiles; IMU readings drift",
        completed=["build passes"],
        remaining=["fix drift", "write tests"],
        current_issue={"description": "IMU drift", "error": "yaw +3deg/min", "root_cause": ""},
        attempts=[{"action": "recalibrate gyro", "result": "no change", "conclusion": "not a calibration issue"}],
        findings=[{"statement": "drift is temperature dependent", "kind": "hypothesis"}],
        relevant_files=["src/imu.cpp"],
        next_steps=["log temperature vs drift"],
        verification=[{"command": "colcon test", "result": "3 passed", "passed": True}],
    )
    assert cp["findings"][0]["kind"] == "hypothesis"
    t = (await client.get(f"/api/tasks/{task['id']}")).json()
    assert t["completed_items"] == ["build passes"]
    assert t["remaining_items"] == ["fix drift", "write tests"]
    assert t["next_action"] == "log temperature vs drift"
    assert t["blockers"] == ["IMU drift"]

    # A later checkpoint without `remaining` keeps the remaining list; completed items accumulate.
    await _checkpoint(client, task["id"], completed=["drift fixed"])
    t = (await client.get(f"/api/tasks/{task['id']}")).json()
    assert t["completed_items"] == ["build passes", "drift fixed"]
    assert t["remaining_items"] == ["fix drift", "write tests"]
    page = (await client.get(f"/api/tasks/{task['id']}/checkpoints")).json()
    assert page["total"] == 2


async def test_checkpoints_are_append_only_in_db(client: httpx.AsyncClient, db: Database) -> None:
    task = await create_task(client)
    cp = await _checkpoint(client, task["id"])
    with pytest.raises(Exception, match="append-only"):
        async with db.session() as s:
            await s.execute(text("UPDATE checkpoints SET summary = 'rewritten' WHERE id = :id"), {"id": cp["id"]})


async def test_context_builder_modes_and_budget(client: httpx.AsyncClient) -> None:
    project = await create_project(client, "Robot", description="Mobile manipulator on ROS2")
    ws = await create_workspace(client, "/w/robot", project["id"])
    task = await create_task(
        client, "Implement grasp planner", workspace_id=ws["id"], acceptance_criteria=["grasp success > 90%"]
    )
    await _checkpoint(
        client,
        task["id"],
        summary="Planner skeleton done",
        completed=["skeleton"],
        remaining=["tune"],
        next_steps=["tune approach angle"],
        relevant_files=["planner.py"],
    )
    await client.post(
        "/api/knowledge",
        json={
            "title": "Gripper limits",
            "content": "Max opening 85mm",
            "project_id": project["id"],
            "verified": True,
            "category": "constraint",
        },
    )
    await client.post(
        "/api/decisions",
        json={
            "task_id": task["id"],
            "question": "Use MoveIt?",
            "options": [{"key": "yes", "label": "Yes"}, {"key": "no", "label": "No"}],
        },
    )

    brief = (await client.get(f"/api/tasks/{task['id']}/context", params={"mode": "brief"})).json()
    assert brief["sections"][:2] == ["task", "state"]
    assert "latest_checkpoint" in brief["sections"]
    assert "knowledge" not in brief["sections"]
    md = brief["markdown"]
    assert "Implement grasp planner" in md and "tune approach angle" in md
    assert "Use MoveIt?" in md, "pending decisions are blockers"

    standard = (await client.get(f"/api/tasks/{task['id']}/context", params={"mode": "standard"})).json()
    assert {"knowledge", "key_files"} <= set(standard["sections"])
    assert "Max opening 85mm" in standard["markdown"]

    tiny = (await client.get(f"/api/tasks/{task['id']}/context", params={"mode": "full", "max_tokens": 200})).json()
    assert tiny["truncated"] is True
    assert tiny["sections"][0] == "task"
    assert tiny["estimated_tokens"] <= 200 + 80

    again = (await client.get(f"/api/tasks/{task['id']}/context", params={"mode": "standard"})).json()
    assert again["markdown"] == standard["markdown"], "context is deterministic"


def test_token_estimate_handles_cjk() -> None:
    assert estimate_tokens("abcd" * 10) == 10
    assert estimate_tokens("机械臂抓取") == 5


async def test_blocking_decision_round_trip(client: httpx.AsyncClient) -> None:
    task = await create_task(client)
    await client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"})
    r = await client.post(
        "/api/decisions",
        json={
            "task_id": task["id"],
            "question": "Which DB?",
            "recommendation": "postgres",
            "options": [{"key": "pg", "label": "PostgreSQL"}, {"key": "sqlite", "label": "SQLite"}],
        },
    )
    decision = r.json()
    assert (await client.get(f"/api/tasks/{task['id']}")).json()["status"] == "awaiting_user"
    pending = (await client.get("/api/decisions", params={"status": "pending"})).json()
    assert pending["total"] == 1

    r = await client.post(f"/api/decisions/{decision['id']}/resolve", json={"selected_option": "mysql"})
    assert r.status_code == 422
    r = await client.post(
        f"/api/decisions/{decision['id']}/resolve", json={"selected_option": "pg", "response": "go with pg"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["status"] == "resolved"
    assert (await client.get(f"/api/tasks/{task['id']}")).json()["status"] == "in_progress", "status restored"
    r = await client.post(f"/api/decisions/{decision['id']}/resolve", json={"selected_option": "pg"})
    assert r.status_code == 409


async def test_agents_cannot_resolve_decisions_via_rest_only_admin_can_force(clients) -> None:  # type: ignore[no-untyped-def]
    task = await create_task(clients.admin, acceptance_criteria=["x"])
    r = await clients.agent.post(f"/api/tasks/{task['id']}/complete", json={"summary": "s", "force": True})
    assert r.status_code == 403


async def test_knowledge_supersede_and_search(client: httpx.AsyncClient) -> None:
    project = await create_project(client)
    old = (
        await client.post(
            "/api/knowledge", json={"title": "Build with make", "content": "run make all", "project_id": project["id"]}
        )
    ).json()
    new = (
        await client.post(
            "/api/knowledge",
            json={
                "title": "Build with cmake",
                "content": "cmake --build",
                "project_id": project["id"],
                "verified": True,
            },
        )
    ).json()
    r = await client.patch(f"/api/knowledge/{old['id']}", json={"superseded_by": new["id"]})
    assert r.status_code == 200
    listed = (await client.get("/api/knowledge", params={"project_id": project["id"], "q": "build"})).json()
    assert [k["title"] for k in listed["items"]] == ["Build with cmake"]
    with_old = (
        await client.get("/api/knowledge", params={"project_id": project["id"], "include_superseded": True})
    ).json()
    assert with_old["total"] == 2


async def test_artifact_registry_and_versions(client: httpx.AsyncClient) -> None:
    task = await create_task(client, "Build CLI")
    r = await client.post(
        "/api/artifacts",
        json={
            "name": "robotctl",
            "type": "executable",
            "task_id": task["id"],
            "storage_uri": "/w/robot/build/robotctl",
            "version_label": "0.1.0",
            "usage": {"command": "robotctl --help", "expected_result": "prints usage", "prerequisites": ["ROS2"]},
            "build": {"command": "colcon build", "source_path": "src/robotctl"},
        },
    )
    assert r.status_code == 201, r.text
    art = r.json()
    r = await client.patch(
        f"/api/artifacts/{art['id']}",
        json={
            "version_label": "0.2.0",
            "verification": {"status": "passed", "command": "robotctl --version", "result": "0.2.0"},
            "version_notes": "bugfix",
        },
    )
    assert r.status_code == 200
    detail = (await client.get(f"/api/artifacts/{art['id']}")).json()
    assert [v["version_label"] for v in detail["versions"]] == ["0.2.0", "0.1.0"]
    assert detail["verification"]["status"] == "passed"
    r = await client.post("/api/artifacts", json={"name": "x", "storage_uri": "/x", "storage_mode": "managed"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_implemented"
    events = [e["event_type"] for e in (await client.get(f"/api/tasks/{task['id']}/events")).json()]
    assert "artifact.registered" in events


async def test_resolving_with_resume_dispatches_the_last_agent(client: httpx.AsyncClient) -> None:
    ws = await create_workspace(client, "/w/resume")
    task = await create_task(client, "needs a decision", workspace_id=ws["id"])
    await client.post("/api/agent-profiles", json={"name": "fk", "agent_type": "fake", "is_default": True})
    first = (await client.post("/api/runs", json={"task_id": task["id"], "agent_type": "fake"})).json()
    await client.post(f"/api/runs/{first['id']}/cancel", json={})
    decision = (
        await client.post(
            "/api/decisions",
            json={"task_id": task["id"], "question": "A or B?", "options": [{"key": "a", "label": "A"}]},
        )
    ).json()
    r = await client.post(f"/api/decisions/{decision['id']}/resolve", json={"selected_option": "a", "resume": True})
    resumed = r.json()["resumed_run"]
    assert resumed["agent_type"] == "fake" and resumed["status"] == "queued"
    assert resumed["session_id"] == first["session_id"], "continues the same agent session"
    assert "Answer: a" in resumed["instructions"]
