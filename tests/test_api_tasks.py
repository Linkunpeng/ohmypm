"""Phase 1: projects, workspaces, tasks, status machine, dependencies, events, concurrency."""

import asyncio
import uuid

import httpx

from tests.conftest import Clients, create_project, create_task, create_workspace


async def test_health_is_public(clients: Clients) -> None:
    r = await clients.anon.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == "ok"
    assert body["schema_revision"] == "0002"


async def test_auth_required(clients: Clients) -> None:
    r = await clients.anon.get("/api/tasks")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    bad = clients.with_token("wrong-token")
    assert (await bad.get("/api/tasks")).status_code == 401


async def test_runner_token_cannot_use_admin_endpoints(clients: Clients) -> None:
    r = await clients.runner.post("/api/tasks", json={"raw_request": "x"})
    assert r.status_code == 403
    r = await clients.agent.post("/api/projects", json={"name": "nope"})
    assert r.status_code == 403


async def test_project_and_task_lifecycle(client: httpx.AsyncClient) -> None:
    project = await create_project(client, "Robot", description="ROS2 robot")
    pid = project["id"]
    ws = await create_workspace(client, "/home/u/Robot_WS", pid)
    task = await create_task(
        client,
        "Make the arm move\nmore details",
        workspace_id=ws["id"],
        acceptance_criteria=["arm moves"],
        priority="high",
    )
    assert task["title"] == "Make the arm move"
    assert task["project_id"] == pid, "project inherited from workspace"
    assert task["status"] == "todo"
    assert task["key"].startswith("T-")

    detail = (await client.get(f"/api/projects/{pid}")).json()
    assert detail["stats"]["tasks_total"] == 1
    assert detail["workspaces"][0]["root_path"] == "/home/u/Robot_WS"

    r = await client.get(f"/api/tasks/{task['key']}")
    assert r.status_code == 200 and r.json()["id"] == task["id"]
    assert r.headers["etag"] == f'W/"{task["version"]}"'

    r = await client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress", "description": "Structured"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"
    events = (await client.get(f"/api/tasks/{task['id']}/events")).json()
    types = [e["event_type"] for e in events]
    assert types == ["task.created", "task.updated", "task.status_changed"]
    assert events[1]["payload"]["changes"]["description"]["old"] == ""

    listed = (await client.get("/api/tasks", params={"project_id": pid, "status": "in_progress"})).json()
    assert listed["total"] == 1


async def test_raw_request_is_immutable(client: httpx.AsyncClient) -> None:
    task = await create_task(client, "original words")
    r = await client.patch(f"/api/tasks/{task['id']}", json={"raw_request": "changed"})
    assert r.status_code == 200
    assert r.json()["raw_request"] == "original words"


async def test_invalid_transitions(client: httpx.AsyncClient) -> None:
    task = await create_task(client)
    r = await client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "use_complete"
    await client.post(f"/api/tasks/{task['id']}/cancel")
    r = await client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    r = await client.patch(f"/api/tasks/{task['id']}", json={"status": "todo"})
    assert r.status_code == 200, "cancelled tasks can be reopened"


async def test_completion_requires_acceptance(client: httpx.AsyncClient) -> None:
    task = await create_task(client, acceptance_criteria=["tests pass", "docs updated"])
    tid = task["id"]
    r = await client.post(f"/api/tasks/{tid}/complete", json={"summary": "done"})
    assert r.status_code == 422
    assert r.json()["error"]["details"]["missing"] == ["tests pass", "docs updated"]
    r = await client.post(
        f"/api/tasks/{tid}/complete",
        json={
            "summary": "done",
            "results": [
                {"criterion": "tests pass", "passed": True, "evidence": "pytest: 10 passed"},
                {"criterion": "docs updated", "passed": False},
            ],
        },
    )
    assert r.status_code == 422 and r.json()["error"]["details"]["failed"] == ["docs updated"]
    r = await client.post(
        f"/api/tasks/{tid}/complete",
        json={
            "summary": "done",
            "results": [
                {"criterion": "tests pass", "passed": True, "evidence": "pytest: 10 passed"},
                {"criterion": "docs updated", "passed": True, "evidence": "README diff"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed" and body["completed_at"]
    assert body["acceptance_result"]["verified_by"] == "admin"


async def test_dependencies_ready_and_cycles(client: httpx.AsyncClient) -> None:
    a = await create_task(client, "A")
    b = await create_task(client, "B", depends_on=[a["id"]])
    c = await create_task(client, "C")
    r = await client.post(f"/api/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "dependency_cycle"
    r = await client.post(f"/api/tasks/{c['id']}/dependencies", json={"depends_on_id": b["id"]})
    assert r.status_code == 204
    r = await client.post(f"/api/tasks/{a['id']}/dependencies", json={"depends_on_id": c["id"]})
    assert r.status_code == 409, "transitive cycle a→c→b→a"

    ready = (await client.get("/api/tasks", params={"ready": True})).json()
    assert [t["title"] for t in ready["items"]] == ["A"]
    detail = (await client.get(f"/api/tasks/{b['id']}")).json()
    assert detail["unmet_dependencies"] == [a["id"]]

    r = await client.post(f"/api/tasks/{b['id']}/complete", json={"summary": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "dependencies_unmet"
    await client.post(f"/api/tasks/{a['id']}/complete", json={"summary": "done"})
    ready = (await client.get("/api/tasks", params={"ready": True})).json()
    assert [t["title"] for t in ready["items"]] == ["B"]


async def test_optimistic_concurrency(client: httpx.AsyncClient) -> None:
    task = await create_task(client)
    r1 = await client.patch(
        f"/api/tasks/{task['id']}", json={"title": "one"}, headers={"If-Match": f'W/"{task["version"]}"'}
    )
    assert r1.status_code == 200
    r2 = await client.patch(f"/api/tasks/{task['id']}", json={"title": "two", "expected_version": task["version"]})
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "version_conflict"


async def test_idempotent_create(client: httpx.AsyncClient) -> None:
    key = {"Idempotency-Key": "abc-123"}
    r1 = await client.post("/api/tasks", json={"raw_request": "once"}, headers=key)
    r2 = await client.post("/api/tasks", json={"raw_request": "once"}, headers=key)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert (await client.get("/api/tasks")).json()["total"] == 1
    r3 = await client.post("/api/tasks", json={"raw_request": "different"}, headers=key)
    assert r3.status_code == 409 and r3.json()["error"]["code"] == "idempotency_key_reused"


async def test_concurrent_idempotent_requests(client: httpx.AsyncClient) -> None:
    key = {"Idempotency-Key": "race"}
    results = await asyncio.gather(
        *[client.post("/api/tasks", json={"raw_request": "race"}, headers=key) for _ in range(5)]
    )
    ok = [r for r in results if r.status_code == 201]
    assert ok, [r.text for r in results]
    assert len({r.json()["id"] for r in ok}) == 1
    assert all(r.status_code in (201, 409) for r in results)
    assert (await client.get("/api/tasks")).json()["total"] == 1


async def test_anonymous_tasks_and_workspaces(client: httpx.AsyncClient) -> None:
    ws = await create_workspace(client, "/tmp/scratch")
    await create_task(client, "anon in ws", workspace_id=ws["id"])
    await create_task(client, "standalone")
    project = await create_project(client)
    await create_task(client, "in project", project_id=project["id"])
    anon = (await client.get("/api/tasks", params={"anonymous": True})).json()
    assert {t["title"] for t in anon["items"]} == {"anon in ws", "standalone"}
    wss = (await client.get("/api/workspaces", params={"anonymous": True})).json()
    assert [w["root_path"] for w in wss["items"]] == ["/tmp/scratch"]

    # Initialising a PROJECT_ID in the directory later links the workspace (task migration path).
    linked = await create_workspace(client, "/tmp/scratch", project["id"])
    assert linked["id"] == ws["id"] and linked["project_id"] == project["id"]
    assert linked["metadata"]["project_history"][0]["to"] == project["id"]


async def test_register_existing_project_id(client: httpx.AsyncClient) -> None:
    pid = str(uuid.uuid4())
    r = await client.post("/api/projects", json={"id": pid, "name": "From file"})
    assert r.status_code == 201 and r.json()["id"] == pid
    r = await client.post("/api/projects", json={"id": pid, "name": "Again"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "project_exists"


async def test_workspace_path_validation(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/workspaces/resolve", json={"host_id": "h", "root_path": "relative/path"})
    assert r.status_code == 422
    r = await client.post(
        "/api/workspaces/resolve", json={"host_id": "h", "root_path": "/x", "project_id": str(uuid.uuid4())}
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "project_not_registered"


async def test_search_and_pagination(client: httpx.AsyncClient) -> None:
    for i in range(7):
        await create_task(client, f"Calibrate camera {i}")
    await create_task(client, "实现机械臂抓取功能")
    page = (await client.get("/api/tasks", params={"limit": 3, "offset": 3, "sort": "number"})).json()
    assert page["total"] == 8 and len(page["items"]) == 3
    assert page["items"][0]["title"] == "Calibrate camera 3"
    hits = (await client.get("/api/search", params={"q": "camera"})).json()["hits"]
    assert len(hits) == 7 and all(h["kind"] == "task" for h in hits)
    hits = (await client.get("/api/search", params={"q": "机械臂"})).json()["hits"]
    assert [h["title"].split(" ", 1)[1] for h in hits] == ["实现机械臂抓取功能"]


async def test_unknown_api_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
