from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ohmypm.api import app as app_module
from ohmypm.api.app import create_app
from ohmypm.core.service import MemoryService
from tests.conftest import tree_snapshot
from tests.test_assets import SAFE_SVG, make_png

TOKEN = "t" * 43
BASE = "http://127.0.0.1:8737"


@pytest.fixture
def client(service: MemoryService) -> TestClient:
    return TestClient(
        create_app(service, token=TOKEN), base_url=BASE, headers={"Authorization": f"Bearer {TOKEN}"}
    )


@pytest.fixture
def anon(service: MemoryService) -> TestClient:
    return TestClient(create_app(service, token=TOKEN), base_url=BASE)


@pytest.fixture
def project(client: TestClient, workspace: Path) -> dict:
    r = client.post("/api/projects", json={"path": str(workspace), "description": "ROS2"})
    assert r.status_code == 201, r.text
    return r.json()["project"]


# ------------------------------------------------------------------ security


def test_health_is_open_but_api_needs_token(anon: TestClient) -> None:
    assert anon.get("/api/health").json()["status"] == "ok"
    r = anon.get("/api/projects")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert anon.get("/api/projects", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert anon.get("/api/projects", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_token_link_sets_cookie(anon: TestClient) -> None:
    r = anon.get(f"/?token={TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert anon.get("/api/projects").status_code == 200  # cookie now stored in the client
    bad = TestClient(anon.app, base_url=BASE).get("/?token=nope", follow_redirects=False)
    assert bad.status_code != 303


def test_host_header_protects_against_dns_rebinding(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Host": "evil.example:8737"}).status_code == 421
    assert client.get("/api/health", headers={"Host": "localhost:8737"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "[::1]:8737"}).status_code == 200


def test_cross_origin_writes_are_rejected(client: TestClient, workspace: Path) -> None:
    body = {"path": str(workspace)}
    r = client.post("/api/projects", json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"
    r = client.post("/api/projects", json=body, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = client.post("/api/projects", json=body, headers={"Origin": BASE})
    assert r.status_code == 201
    # No CORS headers are granted to foreign origins.
    r = client.get("/api/projects", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_security_headers(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_body_size_limit(client: TestClient, project: dict, monkeypatch: pytest.MonkeyPatch, service) -> None:
    small = TestClient(create_app(service, token=None), base_url=BASE)
    monkeypatch.setattr(app_module, "MAX_JSON_BODY", 1000)
    tiny = TestClient(create_app(service, token=None), base_url=BASE)
    payload = {"project_id": project["id"], "title": "big", "content": "x" * 5000}
    r = tiny.post("/api/entries", json=payload)
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"
    assert small.post("/api/entries", json=payload).status_code == 201


def test_no_auth_mode(service: MemoryService) -> None:
    open_client = TestClient(create_app(service, token=None), base_url=BASE)
    assert open_client.get("/api/projects").status_code == 200


# ------------------------------------------------------------------ resources


def test_project_endpoints(client: TestClient, project: dict, workspace: Path, tmp_path: Path) -> None:
    assert project["name"] == "Robot_WS" and project["description"] == "ROS2"
    again = client.post("/api/projects", json={"path": str(workspace)})
    assert again.json()["outcome"] == "existing"
    assert [p["id"] for p in client.get("/api/projects").json()] == [project["id"]]
    assert client.get(f"/api/projects/{project['id']}").json()["entry_count"] == 0
    patched = client.patch(f"/api/projects/{project['id']}", json={"name": "Robot", "description": "机器人"})
    assert patched.json()["name"] == "Robot" and patched.json()["description"] == "机器人"
    moved = tmp_path / "moved"
    moved.mkdir()
    relinked = client.patch(f"/api/projects/{project['id']}", json={"root_path": str(moved)})
    assert relinked.json()["root_path"] == str(moved.resolve())

    missing = client.get("/api/projects/nope")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    bad = client.post("/api/projects", json={"path": str(tmp_path / "nope")})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    extra = client.post("/api/projects", json={"path": str(moved), "evil": 1})
    assert extra.status_code == 422

    archived = client.delete(f"/api/projects/{project['id']}")
    assert archived.json()["project"]["archived"] is True
    assert client.get("/api/projects").json() == []
    assert len(client.get("/api/projects", params={"include_archived": True}).json()) == 1


def test_entry_crud_pagination_and_filters(client: TestClient, project: dict) -> None:
    pid = project["id"]
    created = []
    for i, t in enumerate(["note", "issue", "milestone", "issue", "decision"]):
        r = client.post(
            "/api/entries",
            json={
                "project_id": pid,
                "type": t,
                "title": f"{t} {i}",
                "content": f"内容 {i}",
                "author": "web-user",
            },
        )
        assert r.status_code == 201, r.text
        created.append(r.json())
    assert created[1]["status"] == "open" and created[0]["source"] == "web"

    page = client.get("/api/entries", params={"project_id": pid, "limit": 2, "offset": 1}).json()
    assert page["total"] == 5 and [e["sequence"] for e in page["items"]] == [2, 3]
    desc = client.get(
        "/api/entries", params={"project_id": pid, "order": "desc", "sort": "created_at"}
    ).json()
    assert desc["items"][0]["sequence"] == 5
    issues = client.get(
        "/api/entries", params=[("project_id", pid), ("type", "issue"), ("type", "decision")]
    ).json()
    assert issues["total"] == 3
    assert client.get("/api/entries", params={"project_id": pid, "q": "内容 3"}).json()["total"] == 1
    assert (
        client.get(
            "/api/entries", params={"project_id": pid, "since": "2000-01-01", "until": "today"}
        ).json()["total"]
        == 5
    )
    assert client.get("/api/entries").json()["total"] == 5  # all projects
    assert client.get("/api/entries", params={"limit": 0}).status_code == 422
    assert client.get("/api/entries", params={"since": "garbage"}).status_code == 422

    eid = created[1]["id"]
    full = client.get(f"/api/entries/{eid}").json()
    assert full["content"] == "内容 1"
    patched = client.patch(
        f"/api/entries/{eid}",
        json={"status": "resolved", "content": "fixed", "expected_revision": 1, "author": "me"},
    )
    assert patched.json()["changed"] and patched.json()["entry"]["revision"] == 2
    conflict = client.patch(f"/api/entries/{eid}", json={"content": "x", "expected_revision": 1})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "conflict"
    revisions = client.get(f"/api/entries/{eid}/revisions").json()
    assert revisions[0]["content"] == "内容 1"
    restored = client.post(f"/api/entries/{eid}/restore", json={"revision": 1}).json()
    assert restored["content"] == "内容 1"
    bad_type = client.post("/api/entries", json={"project_id": pid, "title": "x", "type": "bogus"})
    assert bad_type.status_code == 422
    empty = client.post("/api/entries", json={"project_id": pid, "title": " "})
    assert empty.status_code == 422 and "title" in empty.json()["error"]["message"]

    assert client.delete(f"/api/entries/{eid}").json()["deleted"] is True
    assert client.get(f"/api/entries/{eid}").status_code == 404


def test_summary_and_context(client: TestClient, project: dict) -> None:
    pid = project["id"]
    assert client.get(f"/api/projects/{pid}/summary").json()["is_empty"] is True
    r = client.put(
        f"/api/projects/{pid}/summary", json={"overview": "机器人", "next_steps": "- 标定", "author": "web"}
    )
    assert r.json()["changed"] and r.json()["summary"]["revision"] == 1
    r = client.put(f"/api/projects/{pid}/summary", json={"known_issues": "- 丢帧", "expected_revision": 1})
    assert r.json()["summary"]["overview"] == "机器人"
    stale = client.put(f"/api/projects/{pid}/summary", json={"overview": "x", "expected_revision": 1})
    assert stale.status_code == 409
    assert len(client.get(f"/api/projects/{pid}/summary/history").json()) == 1

    client.post("/api/entries", json={"project_id": pid, "type": "issue", "title": "OpenCV 链接失败"})
    ctx = client.get(f"/api/projects/{pid}/context", params={"mode": "standard"}).json()
    assert ctx["mode"] == "standard" and "OpenCV 链接失败" in ctx["markdown"]
    assert client.get(f"/api/projects/{pid}/context", params={"mode": "bad"}).status_code == 422


def test_search_endpoint(client: TestClient, project: dict) -> None:
    pid = project["id"]
    client.post("/api/entries", json={"project_id": pid, "title": "完成相机驱动", "content": "V4L2 图像采集"})
    hits = client.get("/api/search", params={"q": "图像采集", "project_id": pid}).json()
    assert hits["total"] == 1 and hits["items"][0]["sequence"] == 1
    assert client.get("/api/search", params={"q": "相机"}).json()["total"] == 1
    assert client.get("/api/search").status_code == 422


def test_dashboard_and_meta(client: TestClient, project: dict) -> None:
    client.post("/api/entries", json={"project_id": project["id"], "type": "milestone", "title": "done"})
    dash = client.get("/api/dashboard").json()
    assert dash["projects"][0]["id"] == project["id"]
    assert dash["recent_entries"][0]["project_name"] == "Robot_WS"
    assert dash["type_counts"] == {"milestone": 1}
    meta = client.get("/api/meta").json()
    assert "milestone" in meta["entry_types"] and meta["statuses"] == ["open", "resolved", "obsolete"]


def test_asset_upload_and_serving(client: TestClient, project: dict) -> None:
    pid = project["id"]
    r = client.post(
        "/api/assets", data={"project_id": pid}, files={"file": ("截图.png", make_png(), "image/png")}
    )
    assert r.status_code == 201, r.text
    asset = r.json()
    assert asset["url"] == f"/api/assets/{asset['id']}" and asset["markdown"].startswith("![截图.png]")
    got = client.get(asset["url"])
    assert got.status_code == 200 and got.content == make_png()
    assert got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "UTF-8''%E6%88%AA%E5%9B%BE.png" in got.headers["content-disposition"]

    svg = client.post(
        "/api/assets", data={"project_id": pid}, files={"file": ("d.svg", SAFE_SVG, "image/svg+xml")}
    )
    served = client.get(svg.json()["url"])
    assert "sandbox" in served.headers["content-security-policy"]

    txt = client.post(
        "/api/assets",
        data={"project_id": pid},
        files={"file": ("x.html", b"<script>alert(1)</script>", "text/html")},
    )
    assert txt.status_code == 201 and txt.json()["mime_type"] == "text/plain"
    served = client.get(txt.json()["url"])
    assert served.headers["content-type"].startswith("text/plain")

    evil = client.post(
        "/api/assets",
        data={"project_id": pid},
        files={"file": ("x.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>', "image/svg+xml")},
    )
    assert evil.status_code == 422
    exe = client.post(
        "/api/assets", data={"project_id": pid}, files={"file": ("a.exe", b"MZ\x90\x00" * 10, "x")}
    )
    assert exe.status_code == 422
    listed = client.get("/api/assets", params={"project_id": pid}).json()
    assert len(listed) == 3
    assert client.get("/api/assets/00000000-0000-0000-0000-000000000000").status_code == 404


def test_upload_size_limit(service: MemoryService, workspace: Path, tmp_path: Path) -> None:
    from dataclasses import replace

    small_settings = replace(service.settings, max_upload_bytes=1024)
    small = MemoryService(small_settings, service.db)
    pid = small.register(workspace)[0].id
    client = TestClient(create_app(small, token=None), base_url=BASE)
    over_app_limit = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4096  # above 1 KiB, below the transport limit
    r = client.post(
        "/api/assets", data={"project_id": pid}, files={"file": ("a.png", over_app_limit, "image/png")}
    )
    assert r.status_code == 422 and r.json()["error"]["details"]["limit"] == 1024
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (3 * 1024 * 1024)
    r = client.post("/api/assets", data={"project_id": pid}, files={"file": ("b.png", big, "image/png")})
    assert r.status_code == 413


def test_no_source_file_access(client: TestClient, project: dict, workspace: Path) -> None:
    before = tree_snapshot(workspace)
    for path in (
        "/../../etc/passwd",
        "/..%2f..%2fetc%2fpasswd",
        f"/{workspace}/README.md",
        "/api/files?path=/etc/passwd",
        "/api/assets/..%2f..%2fetc%2fpasswd",
    ):
        r = client.get(path)
        assert b"root:" not in r.content and b"# Robot" not in r.content, path
    assert tree_snapshot(workspace) == before


def test_openapi_document(client: TestClient) -> None:
    spec = client.get("/api/openapi.json").json()
    for p in (
        "/api/projects",
        "/api/entries",
        "/api/entries/{entry_id}",
        "/api/projects/{project_id}/summary",
        "/api/projects/{project_id}/context",
        "/api/search",
        "/api/assets",
        "/api/assets/{asset_id}",
        "/api/health",
    ):
        assert p in spec["paths"], p


def test_spa_fallback_without_build(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, service, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>ohmypm</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: dist)
    web = TestClient(create_app(service, token=None), base_url=BASE)
    assert web.get("/").text == "<html>ohmypm</html>"
    assert web.get("/projects/abc/timeline").text == "<html>ohmypm</html>"
    js = web.get("/assets/app.js")
    assert js.text == "console.log(1)" and "immutable" in js.headers["cache-control"]
    assert web.get("/api/nope").status_code == 404
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: None)
    assert TestClient(create_app(service, token=None), base_url=BASE).get("/").status_code == 503
