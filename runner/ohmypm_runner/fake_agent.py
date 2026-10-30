"""A deterministic stand-in for an agent CLI, used by tests and demos.

Reads the prompt from stdin, then executes the steps in ``$OHMYPM_FAKE_SCRIPT`` (JSON list) and
prints events in ohmypm's normalized JSONL format. It talks to the ohmypm REST API exactly like a
real agent would via MCP/CLI: with ``$OHMYPM_URL`` and the run-scoped ``$OHMYPM_AGENT_TOKEN``.

Steps: ``{"message": str}``, ``{"tool": str, "input": any, "output": any}``,
``{"write_file": rel_path, "content": str}``, ``{"sleep": seconds}``, ``{"checkpoint": {...}}``,
``{"complete": {...}}``, ``{"stderr": str}``, ``{"env_check": [VAR, ...]}``, ``{"fail": str}``,
``{"raw": str}``, ``{"approval": str}``.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any


def emit(event_type: str, **payload: Any) -> None:
    print(json.dumps({"type": event_type, **payload}), flush=True)


def api(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - URL comes from the runner-provided env
        os.environ["OHMYPM_URL"].rstrip("/") + path,
        data=json.dumps(body).encode(),
        method=method,
        headers={"Authorization": f"Bearer {os.environ['OHMYPM_AGENT_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read() or b"{}")  # type: ignore[no-any-return]


def main() -> int:
    prompt = sys.stdin.read()
    script = json.loads(os.environ.get("OHMYPM_FAKE_SCRIPT") or "[]")
    task_id = os.environ.get("OHMYPM_TASK_ID", "")
    emit("session", id=os.environ.get("OHMYPM_FAKE_SESSION_ID") or f"fake-{uuid.uuid4()}", cwd=os.getcwd())
    first_line = next((line for line in prompt.splitlines() if line.strip()), "")
    if not script:
        script = [{"message": f"Received prompt ({len(prompt)} chars): {first_line[:120]}"}]
    for step in script:
        if "message" in step:
            emit("agent.message", text=str(step["message"]))
        elif "tool" in step:
            call_id = str(uuid.uuid4())[:8]
            emit("tool.started", tool=step["tool"], tool_use_id=call_id, input=step.get("input"))
            emit("tool.completed", tool=step["tool"], tool_use_id=call_id, output=step.get("output"), is_error=False)
        elif "write_file" in step:
            target = Path(os.getcwd(), step["write_file"]).resolve()
            if Path(os.getcwd()).resolve() not in target.parents:
                emit("agent.error", message="refusing to write outside the workspace")
                return 2
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(step.get("content", "")), encoding="utf-8")
            emit("file.changed", path=str(target))
        elif "sleep" in step:
            time.sleep(float(step["sleep"]))
        elif "checkpoint" in step:
            cp = api("POST", f"/api/tasks/{task_id}/checkpoints", step["checkpoint"])
            emit("agent.message", text=f"checkpoint saved: {cp.get('id')}")
        elif "complete" in step:
            api("POST", f"/api/tasks/{task_id}/complete", step["complete"])
            emit("agent.message", text="task completed")
        elif "stderr" in step:
            print(step["stderr"], file=sys.stderr, flush=True)
        elif "env_check" in step:
            present = {name: name in os.environ for name in step["env_check"]}
            emit("agent.message", text=f"env: {json.dumps(present, sort_keys=True)}")
        elif "approval" in step:
            emit("approval.requested", tool=step["approval"])
        elif "raw" in step:
            print(step["raw"], flush=True)
        elif "raw_on_resume" in step and os.environ.get("OHMYPM_FAKE_SESSION_ID"):
            print(step["raw_on_resume"], flush=True)
        elif "fail" in step:
            emit("agent.error", message=str(step["fail"]))
            return 1
    emit("result", text=f"fake agent finished: {first_line[:80]}")
    return int(os.environ.get("OHMYPM_FAKE_EXIT_CODE", "0"))


if __name__ == "__main__":
    sys.exit(main())
