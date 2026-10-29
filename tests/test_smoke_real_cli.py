"""Optional smoke tests against REAL agent CLIs. They cost money / quota, so they only run when
explicitly enabled:

    OHMYPM_SMOKE=1 uv run pytest tests/test_smoke_real_cli.py -s
    OHMYPM_SMOKE=1 OHMYPM_SMOKE_AGENTS=claude uv run pytest tests/test_smoke_real_cli.py -s

Each test dispatches one tiny task ("create hello.txt") through the full stack (API → runner → CLI)
and checks the run completed and the file exists. Claude runs are capped with --max-budget-usd.
"""

import asyncio
import os
import shutil
from pathlib import Path

import httpx
import pytest

from ohmypm_runner.config import RunnerConfig
from ohmypm_runner.service import RunnerService
from tests.conftest import ADMIN_TOKEN, RUNNER_TOKEN, LiveServer
from tests.test_runner_e2e import running, wait_status

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(os.environ.get("OHMYPM_SMOKE") != "1", reason="set OHMYPM_SMOKE=1 to run real CLI smoke tests"),
]

AGENTS = {
    "claude": {"model": "haiku", "max_budget_usd": 0.5},
    "codex": {},
    "pi": {},
    "dsh": {},
}
SELECTED = [a for a in os.environ.get("OHMYPM_SMOKE_AGENTS", "claude,codex,pi,dsh").split(",") if a]


@pytest.mark.parametrize("agent", SELECTED)
async def test_real_cli_creates_file(agent: str, live_server: LiveServer, tmp_path: Path) -> None:
    if shutil.which(agent) is None:
        pytest.skip(f"{agent} is not installed")
    root = tmp_path / "ws" / agent
    root.mkdir(parents=True)
    async with httpx.AsyncClient(
        base_url=live_server.url, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}, timeout=30
    ) as admin:
        ws = (await admin.post("/api/workspaces/resolve", json={"host_id": "smoke", "root_path": str(root)})).json()
        task = (
            await admin.post(
                "/api/tasks",
                json={
                    "raw_request": "Create a file named hello.txt containing exactly the word hi. Do nothing else.",
                    "workspace_id": ws["id"],
                },
            )
        ).json()
        await admin.post(
            "/api/agent-profiles", json={"name": f"smoke-{agent}", "agent_type": agent, "options": AGENTS[agent]}
        )
        run = (
            await admin.post(
                "/api/runs",
                json={
                    "task_id": task["id"],
                    "profile_name": f"smoke-{agent}",
                    "context_mode": "brief",
                    "timeout_seconds": 300,
                },
            )
        ).json()
        config = RunnerConfig(
            server_url=live_server.url,
            token=RUNNER_TOKEN,
            host_id="smoke",
            allowed_roots=[str(tmp_path / "ws")],
            state_dir=str(tmp_path / "state"),
            heartbeat_interval_seconds=1,
            poll_interval_seconds=0.5,
        )
        async with running(RunnerService(config)):
            done = await wait_status(admin, run["id"], {"completed", "failed", "cancelled", "lost"}, timeout=320)
        events = (await admin.get(f"/api/runs/{run['id']}/events", params={"limit": 2000})).json()
        print(f"\n{agent}: {done['status']} {done['error'] or ''} usage={done['usage']}")
        for e in events[-8:]:
            print("  ", e["event_type"], str(e["payload"])[:160])
    assert done["status"] == "completed", done["error"]
    assert (root / "hello.txt").read_text().strip() == "hi"
    await asyncio.sleep(0)
