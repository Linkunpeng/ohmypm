"""``ohmypm`` command line. Talks to the same REST API as the Web UI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from ohmypm_common.client import ApiClient, ApiError
from ohmypm_common.config import ClientConfig, config_dir
from ohmypm_common.project_id import ProjectIdError, find_project, init_project_id, locate_workspace

app = typer.Typer(help="ohmypm — project memory, tasks and agent execution.", no_args_is_help=True)
project_app = typer.Typer(help="Projects (PROJECT_ID directories).", no_args_is_help=True)
task_app = typer.Typer(help="Tasks.", no_args_is_help=True)
run_app = typer.Typer(help="Agent runs.", no_args_is_help=True)
agent_app = typer.Typer(help="Agent CLIs and profiles.", no_args_is_help=True)
runner_app = typer.Typer(help="The local Agent Runner.", no_args_is_help=True)
decision_app = typer.Typer(help="Decisions waiting for the user.", no_args_is_help=True)
artifact_app = typer.Typer(help="Artifact registry.", no_args_is_help=True)
checkpoint_app = typer.Typer(help="Checkpoints (resumable progress).", no_args_is_help=True)
mcp_app = typer.Typer(help="MCP client configuration helpers.", no_args_is_help=True)
for sub, name in [
    (project_app, "project"),
    (task_app, "task"),
    (run_app, "run"),
    (agent_app, "agent"),
    (runner_app, "runner"),
    (decision_app, "decision"),
    (artifact_app, "artifact"),
    (checkpoint_app, "checkpoint"),
    (mcp_app, "mcp"),
]:
    app.add_typer(sub, name=name)

console = Console()
err = Console(stderr=True)


class State:
    url: str | None = None
    token: str | None = None
    json: bool = False


state = State()


@app.callback()
def main(
    url: Annotated[str | None, typer.Option("--url", envvar="OHMYPM_URL", help="Server URL")] = None,
    token: Annotated[str | None, typer.Option("--token", help="API token (default: OHMYPM_TOKEN / config)")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print raw JSON")] = False,
) -> None:
    state.url, state.token, state.json = url, token, as_json


def cfg() -> ClientConfig:
    return ClientConfig.load(state.url, state.token)


def client() -> ApiClient:
    c = cfg()
    if not c.token:
        err.print(
            "[red]No API token.[/] Set OHMYPM_TOKEN or `token` in "
            f"{config_dir() / 'config.toml'} (see `ohmypm config init`)."
        )
        raise typer.Exit(2)
    return ApiClient(c.server_url, c.token)


def call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except ApiError as exc:
        err.print(f"[red]error {exc.status_code} {exc.code}:[/] {exc.message}")
        if exc.details:
            err.print(json.dumps(exc.details, indent=2, default=str))
        raise typer.Exit(1) from exc
    except Exception as exc:  # network errors
        import httpx

        if isinstance(exc, httpx.HTTPError):
            err.print(f"[red]cannot reach {cfg().server_url}:[/] {exc}")
            raise typer.Exit(1) from exc
        raise


def out(data: Any) -> bool:
    """Print JSON when --json was given; returns True if handled."""
    if state.json:
        console.print_json(json.dumps(data, default=str))
        return True
    return False


def table(rows: list[dict[str, Any]], columns: list[tuple[str, str]], title: str | None = None) -> None:
    t = Table(title=title, show_lines=False, header_style="bold")
    for _, header in columns:
        t.add_column(header, overflow="fold")
    for row in rows:
        t.add_row(*[str(row.get(key) if row.get(key) is not None else "") for key, _ in columns])
    console.print(t)


def _resolve_here(api: ApiClient, path: Path | None = None, register: bool = True) -> dict[str, Any]:
    """Find PROJECT_ID / anonymous workspace for ``path`` and make sure the server knows it."""
    try:
        location = locate_workspace(path or Path.cwd())
    except ProjectIdError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    project_id = str(location.project.project_id) if location.project else None
    if project_id and register:
        try:
            api.get(f"/api/projects/{project_id}")
        except ApiError as exc:
            if exc.status_code != 404:
                raise
            api.post("/api/projects", {"id": project_id, "name": location.root.name})
    ws = api.post(
        "/api/workspaces/resolve", {"host_id": cfg().host_id, "root_path": str(location.root), "project_id": project_id}
    )
    return {"location": location, "project_id": project_id, "workspace": ws}


# ---------------------------------------------------------------- config


@app.command("config")
def config_cmd(
    init: Annotated[bool, typer.Option("--init", help="Write ~/.config/ohmypm/config.toml")] = False,
    server_url: Annotated[str | None, typer.Option(help="Server URL to store")] = None,
    token: Annotated[str | None, typer.Option("--set-token", help="Admin token to store")] = None,
) -> None:
    """Show (or initialise) the client configuration."""
    path = Path(os.environ.get("OHMYPM_CONFIG", str(config_dir() / "config.toml")))
    if init:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f'server_url = "{server_url or cfg().server_url}"']
        if token:
            lines.append(f'token = "{token}"')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        console.print(f"wrote {path}")
    c = cfg()
    console.print(
        {
            "config_file": str(path),
            "server_url": c.server_url,
            "host_id": c.host_id,
            "token": "set" if c.token else "missing",
        }
    )


# ---------------------------------------------------------------- project


@project_app.command("init")
def project_init(
    path: Annotated[Path, typer.Argument(help="Project root")] = Path("."),
    name: Annotated[str | None, typer.Option(help="Project name (default: directory name)")] = None,
    description: Annotated[str, typer.Option()] = "",
    offline: Annotated[bool, typer.Option(help="Only write PROJECT_ID, do not register")] = False,
) -> None:
    """Create PROJECT_ID (never overwrites an existing one) and register the project."""
    root = path.resolve()
    existed = (root / "PROJECT_ID").exists()
    try:
        ident = init_project_id(root)
    except ProjectIdError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"{'found existing' if existed else 'created'} PROJECT_ID {ident.project_id} in {root}")
    if offline:
        return
    with client() as api:
        try:
            project = api.post(
                "/api/projects", {"id": str(ident.project_id), "name": name or root.name, "description": description}
            )
            console.print(f"registered project [bold]{project['name']}[/]")
        except ApiError as exc:
            if exc.code != "project_exists":
                err.print(f"[red]registration failed: {exc.code}:[/] {exc.message}")
                raise typer.Exit(1) from exc
            console.print("project already registered")
        except Exception as exc:
            err.print(f"[yellow]PROJECT_ID written but registration failed:[/] {exc}")
            raise typer.Exit(1) from exc
        call(_resolve_here, api, root, False)


@project_app.command("info")
def project_info(path: Annotated[Path, typer.Argument()] = Path(".")) -> None:
    """Show the project (or anonymous workspace) for a directory."""
    try:
        ident = find_project(path)
    except ProjectIdError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if ident is None:
        console.print(f"[yellow]{path.resolve()} is an anonymous workspace (no PROJECT_ID found)[/]")
        return
    with client() as api:
        try:
            project = api.get(f"/api/projects/{ident.project_id}")
        except ApiError as exc:
            if exc.status_code == 404:
                console.print(
                    f"PROJECT_ID {ident.project_id} at {ident.root} is not registered; run `ohmypm project init`"
                )
                return
            raise
    if out(project):
        return
    console.print(f"[bold]{project['name']}[/]  {project['id']}\nroot: {ident.root}")
    if project["description"]:
        console.print(project["description"])
    console.print(
        f"tasks: {project['stats']['tasks_by_status']}  active runs: {project['stats']['active_runs']}  "
        f"pending decisions: {project['stats']['pending_decisions']}"
    )
    table(
        project["workspaces"], [("host_id", "host"), ("root_path", "path"), ("last_seen_at", "last seen")], "Workspaces"
    )


@project_app.command("list")
def project_list(query: Annotated[str | None, typer.Option("-q")] = None) -> None:
    """List projects."""
    with client() as api:
        page = call(api.get, "/api/projects", params={"q": query} if query else None)
    if out(page):
        return
    table(page["items"], [("id", "id"), ("name", "name"), ("updated_at", "updated")])


# ---------------------------------------------------------------- tasks


def _task_params(
    project: str | None,
    all_: bool,
    anonymous: bool,
    status: list[str] | None,
    ready: bool,
    query: str | None,
    api: ApiClient,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": 100}
    if status:
        params["status"] = status
    if ready:
        params["ready"] = True
    if query:
        params["q"] = query
    if anonymous:
        params["anonymous"] = True
    elif project:
        params["project_id"] = project
    elif not all_:
        ident = find_project(Path.cwd())
        if ident:
            params["project_id"] = str(ident.project_id)
    return params


@task_app.command("list")
def task_list(
    project: Annotated[str | None, typer.Option(help="Project id (default: current directory's project)")] = None,
    all_: Annotated[bool, typer.Option("--all", help="All projects")] = False,
    anonymous: Annotated[bool, typer.Option(help="Only tasks without a project")] = False,
    status: Annotated[list[str] | None, typer.Option("--status", "-s")] = None,
    ready: Annotated[bool, typer.Option(help="Only tasks whose dependencies are done")] = False,
    query: Annotated[str | None, typer.Option("-q")] = None,
) -> None:
    """List tasks (defaults to the project of the current directory)."""
    with client() as api:
        page = call(api.get, "/api/tasks", params=_task_params(project, all_, anonymous, status, ready, query, api))
    if out(page):
        return
    table(
        page["items"],
        [("key", "key"), ("status", "status"), ("priority", "prio"), ("title", "title"), ("next_action", "next")],
    )


@task_app.command("show")
def task_show(task: Annotated[str, typer.Argument(help="Task id or key (T-12)")]) -> None:
    """Show one task."""
    with client() as api:
        t = call(api.get, f"/api/tasks/{task}")
    if out(t):
        return
    console.print(f"[bold]{t['key']} {t['title']}[/]  [{t['status']}] priority={t['priority']}  id={t['id']}")
    console.print(f"\n[bold]Original request[/]\n{t['raw_request']}")
    if t["description"]:
        console.print(f"\n[bold]Description[/]\n{t['description']}")
    for key, label in (
        ("acceptance_criteria", "Acceptance criteria"),
        ("completed_items", "Done"),
        ("remaining_items", "Remaining"),
        ("blockers", "Blockers"),
    ):
        if t[key]:
            console.print(f"\n[bold]{label}[/]")
            for item in t[key]:
                console.print(f"  • {item}")
    if t["next_action"]:
        console.print(f"\n[bold]Next action:[/] {t['next_action']}")
    if t["unmet_dependencies"]:
        console.print(f"\n[yellow]Waiting on dependencies:[/] {', '.join(t['unmet_dependencies'])}")


@task_app.command("create")
def task_create(
    request: Annotated[str, typer.Argument(help="The request, verbatim")],
    title: Annotated[str | None, typer.Option()] = None,
    criteria: Annotated[list[str] | None, typer.Option("--criterion", "-c", help="Acceptance criterion")] = None,
    priority: Annotated[str, typer.Option()] = "normal",
    depends_on: Annotated[list[str] | None, typer.Option("--depends-on")] = None,
    standalone: Annotated[bool, typer.Option(help="Do not attach to the current directory")] = False,
) -> None:
    """Create a task in the current directory's project/workspace."""
    with client() as api:
        body: dict[str, Any] = {
            "raw_request": request,
            "title": title,
            "priority": priority,
            "acceptance_criteria": criteria or [],
            "depends_on": depends_on or [],
        }
        if not standalone:
            here = call(_resolve_here, api)
            body["workspace_id"] = here["workspace"]["id"]
            body["project_id"] = here["project_id"]
        t = call(api.post, "/api/tasks", body)
    if not out(t):
        console.print(f"created {t['key']} {t['title']} ({t['id']})")


@task_app.command("update")
def task_update(
    task: str,
    status: Annotated[str | None, typer.Option()] = None,
    next_action: Annotated[str | None, typer.Option("--next")] = None,
    description: Annotated[str | None, typer.Option()] = None,
    note: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Update status / next action / description."""
    body = {
        k: v
        for k, v in {"status": status, "next_action": next_action, "description": description, "note": note}.items()
        if v is not None
    }
    with client() as api:
        t = call(api.get, f"/api/tasks/{task}")
        t = call(api.patch, f"/api/tasks/{t['id']}", body)
    if not out(t):
        console.print(f"{t['key']} → {t['status']}")


@task_app.command("complete")
def task_complete(
    task: str,
    summary: Annotated[str, typer.Option(help="What was delivered and how it was verified")],
    result: Annotated[list[str] | None, typer.Option("--result", "-r", help="'criterion=evidence' (passed)")] = None,
) -> None:
    """Complete a task with acceptance evidence."""
    results = []
    for item in result or []:
        criterion, _, evidence = item.partition("=")
        results.append({"criterion": criterion.strip(), "passed": True, "evidence": evidence.strip()})
    with client() as api:
        t = call(api.get, f"/api/tasks/{task}")
        t = call(api.post, f"/api/tasks/{t['id']}/complete", {"summary": summary, "results": results})
    if not out(t):
        console.print(f"{t['key']} completed")


@app.command("context")
def context_cmd(
    task: Annotated[str, typer.Argument(help="Task id or key")],
    mode: Annotated[str, typer.Option(help="brief | standard | full")] = "brief",
    max_tokens: Annotated[int, typer.Option()] = 3000,
    raw: Annotated[bool, typer.Option(help="Print plain markdown")] = False,
) -> None:
    """Print the resume context an agent would receive for a task."""
    with client() as api:
        t = call(api.get, f"/api/tasks/{task}")
        ctx = call(api.get, f"/api/tasks/{t['id']}/context", params={"mode": mode, "max_tokens": max_tokens})
    if out(ctx):
        return
    if raw:
        print(ctx["markdown"])
    else:
        console.print(Markdown(ctx["markdown"]))
        err.print(
            f"[dim]{ctx['estimated_tokens']} tokens (budget {ctx['max_tokens']}"
            f"{', truncated' if ctx['truncated'] else ''})[/]"
        )


# ---------------------------------------------------------------- checkpoints


@checkpoint_app.command("add")
def checkpoint_add(
    summary: Annotated[str, typer.Option(help="Concise current state")],
    task: Annotated[str | None, typer.Option(help="Task id/key (default: $OHMYPM_TASK_ID)")] = None,
    done: Annotated[list[str] | None, typer.Option("--done")] = None,
    remaining: Annotated[list[str] | None, typer.Option("--remaining")] = None,
    next_step: Annotated[list[str] | None, typer.Option("--next")] = None,
    file: Annotated[list[str] | None, typer.Option("--file")] = None,
    attempt: Annotated[list[str] | None, typer.Option("--attempt", help="'action => result'")] = None,
    issue: Annotated[str | None, typer.Option(help="Current blocking issue")] = None,
) -> None:
    """Save a checkpoint (agents without MCP can call this; it uses $OHMYPM_AGENT_TOKEN inside a run)."""
    ref = task or os.environ.get("OHMYPM_TASK_ID")
    if not ref:
        err.print("[red]--task is required outside an ohmypm run[/]")
        raise typer.Exit(2)
    attempts = []
    for a in attempt or []:
        action, _, res = a.partition("=>")
        attempts.append({"action": action.strip(), "result": res.strip()})
    body: dict[str, Any] = {
        "summary": summary,
        "completed": done or [],
        "next_steps": next_step or [],
        "relevant_files": file or [],
        "attempts": attempts,
    }
    if remaining is not None:
        body["remaining"] = remaining
    if issue:
        body["current_issue"] = {"description": issue}
    with client() as api:
        t = call(api.get, f"/api/tasks/{ref}")
        cp = call(api.post, f"/api/tasks/{t['id']}/checkpoints", body)
    if not out(cp):
        console.print(f"checkpoint {cp['id']} saved for {t['key']}")


@checkpoint_app.command("list")
def checkpoint_list(task: str) -> None:
    """List a task's checkpoints (newest first)."""
    with client() as api:
        t = call(api.get, f"/api/tasks/{task}")
        page = call(api.get, f"/api/tasks/{t['id']}/checkpoints")
    if out(page):
        return
    table(page["items"], [("created_at", "when"), ("created_by", "by"), ("summary", "summary")])


# ---------------------------------------------------------------- runs


@run_app.command("dispatch")
def run_dispatch(
    task: str,
    agent: Annotated[str | None, typer.Option("--agent", "-a", help="claude | codex | pi | dsh | <custom>")] = None,
    profile: Annotated[str | None, typer.Option(help="Agent profile name")] = None,
    instructions: Annotated[str, typer.Option("--instructions", "-i")] = "",
    mode: Annotated[str, typer.Option(help="Context mode")] = "standard",
    resume_native: Annotated[bool, typer.Option(help="Resume the CLI's native session")] = False,
    continue_run: Annotated[str | None, typer.Option(help="Continue a specific run's native session")] = None,
    timeout: Annotated[int | None, typer.Option(help="Timeout in seconds")] = None,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Stream the run log")] = False,
) -> None:
    """Queue an agent run for a task (a runner on the workspace's host executes it)."""
    with client() as api:
        t = call(api.get, f"/api/tasks/{task}")
        run = call(
            api.post,
            "/api/runs",
            {
                "task_id": t["id"],
                "agent_type": agent,
                "profile_name": profile,
                "instructions": instructions,
                "context_mode": mode,
                "resume_native": resume_native,
                "continue_run_id": continue_run,
                "timeout_seconds": timeout,
            },
        )
    if out(run):
        return
    console.print(f"queued run {run['id']} ({run['agent_type']}) for {t['key']}")
    if follow:
        _follow(run["id"])


@run_app.command("list")
def run_list(
    task: Annotated[str | None, typer.Option()] = None,
    active: Annotated[bool, typer.Option(help="Only queued/active runs")] = False,
) -> None:
    """List runs."""
    params: dict[str, Any] = {"limit": 50}
    with client() as api:
        if task:
            params["task_id"] = call(api.get, f"/api/tasks/{task}")["id"]
        if active:
            params["active"] = True
        page = call(api.get, "/api/runs", params=params)
    if out(page):
        return
    table(
        page["items"],
        [("id", "run"), ("agent_type", "agent"), ("status", "status"), ("created_at", "created"), ("error", "error")],
    )


@run_app.command("show")
def run_show(run_id: str) -> None:
    """Show a run."""
    with client() as api:
        run = call(api.get, f"/api/runs/{run_id}")
    if not out(run):
        console.print_json(json.dumps(run, default=str))


@run_app.command("cancel")
def run_cancel(run_id: str, reason: Annotated[str, typer.Option()] = "") -> None:
    """Cancel a queued or active run."""
    with client() as api:
        run = call(api.post, f"/api/runs/{run_id}/cancel", {"reason": reason})
    console.print(f"run {run['id']}: {run['status']}{' (cancel requested)' if run['cancel_requested_at'] else ''}")


def _format_event(e: dict[str, Any]) -> str:
    p = e["payload"]
    text = p.get("text") or p.get("message") or p.get("error") or p.get("result") or ""
    if e["event_type"].startswith("tool."):
        text = (
            f"{p.get('tool')} {json.dumps(p.get('input'))[:200] if p.get('input') else ''}"
            f"{' → ' + str(p.get('output'))[:200] if p.get('output') else ''}"
        )
    elif e["event_type"] == "file.changed":
        text = p.get("path", "")
    elif not text:
        text = json.dumps(p, default=str)[:300]
    return f"[dim]{e['seq']:>4} {e['timestamp'][11:19]}[/] [cyan]{e['event_type']:<20}[/] {text}"


def _follow(run_id: str) -> None:
    import httpx

    c = cfg()
    last = 0
    while True:
        try:
            with httpx.stream(
                "GET",
                f"{c.server_url}/api/runs/{run_id}/events",
                timeout=httpx.Timeout(10.0, read=None),
                headers={
                    "Authorization": f"Bearer {c.token}",
                    "Accept": "text/event-stream",
                    "Last-Event-ID": str(last),
                },
            ) as resp:
                if resp.status_code != 200:
                    err.print(f"[red]stream failed: {resp.status_code}[/]")
                    raise typer.Exit(1)
                event = None
                for line in resp.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        if event == "end":
                            console.print(f"[bold]run finished: {data['status']}[/]")
                            return
                        last = data["seq"]
                        console.print(_format_event(data), highlight=False)
        except httpx.HTTPError as exc:
            err.print(f"[yellow]stream interrupted ({exc}); reconnecting…[/]")
            time.sleep(2)


@run_app.command("logs")
def run_logs(run_id: str, follow: Annotated[bool, typer.Option("--follow", "-f")] = False) -> None:
    """Print a run's event log (optionally follow live)."""
    if follow:
        _follow(run_id)
        return
    with client() as api:
        events = call(api.get, f"/api/runs/{run_id}/events", params={"limit": 2000})
    if out(events):
        return
    for e in events:
        console.print(_format_event(e), highlight=False)


# ---------------------------------------------------------------- agents / profiles


@agent_app.command("list")
def agent_list() -> None:
    """Agent types and on which runners they are available."""
    with client() as api:
        agents = call(api.get, "/api/agents")
        profiles = call(api.get, "/api/agent-profiles")
    if out({"agents": agents, "profiles": profiles}):
        return
    rows = []
    for a in agents:
        places = [
            f"{p['runner']}{'' if p['online'] else ' (offline)'}: "
            f"{'ok ' + (p.get('version') or '') if p['available'] else 'unavailable'}"
            for p in a["available_on"]
        ]
        rows.append(
            {
                "agent": a["agent_type"],
                "name": a.get("display_name") or "",
                "runners": "; ".join(places) or "no runner reported",
            }
        )
    table(rows, [("agent", "agent"), ("name", "name"), ("runners", "availability")])
    if profiles:
        table(
            profiles,
            [
                ("name", "profile"),
                ("agent_type", "agent"),
                ("write_mode", "write"),
                ("is_default", "default"),
                ("options", "options"),
            ],
            "Profiles",
        )


@agent_app.command("doctor")
def agent_doctor(path: Annotated[Path, typer.Argument()] = Path(".")) -> None:
    """Check local agent CLIs and which instruction/skill files each agent will discover here."""
    from ohmypm_runner.adapters.registry import build_adapters
    from ohmypm_runner.config import load_config
    from ohmypm_runner.discovery import compatibility_notes, discover

    config = load_config()
    if not config.token:
        config.token = "unused"  # noqa: S105 - doctor never contacts the server
    adapters, warnings = build_adapters(config)

    async def detect() -> list[Any]:
        return await asyncio.gather(*(a.check_available() for a in adapters.values()))

    caps = asyncio.run(detect())
    table(
        [
            {
                "agent": c.agent_type,
                "ok": "yes" if c.available else "no",
                "version": c.version or "",
                "detail": c.detail or c.executable or "",
            }
            for c in caps
        ],
        [("agent", "agent"), ("ok", "available"), ("version", "version"), ("detail", "detail")],
        "Agent CLIs",
    )
    for w in warnings:
        err.print(f"[yellow]{w}[/]")
    root = locate_workspace(path).root
    reports = discover(root)
    table(
        [
            {
                "file": r.path,
                "exists": "yes" if r.exists else "-",
                "agents": ", ".join(r.read_by),
                "what": r.description,
            }
            for r in reports
        ],
        [("file", "file"), ("exists", "exists"), ("agents", "read by"), ("what", "purpose")],
        f"Instruction files in {root}",
    )
    for note in compatibility_notes(reports):
        console.print(f"[yellow]•[/] {note}")
    allowed = any(str(root) == r or str(root).startswith(r.rstrip("/") + "/") for r in config.allowed_roots)
    console.print(
        f"runner allowed_roots: {config.allowed_roots or '(none)'} → "
        f"{'[green]this workspace is allowed[/]' if allowed else '[red]this workspace is NOT allowed[/]'}"
    )


@agent_app.command("profile-add")
def agent_profile_add(
    name: str,
    agent: Annotated[str, typer.Option("--agent", "-a")],
    options: Annotated[str, typer.Option(help='JSON options, e.g. \'{"model": "sonnet"}\'')] = "{}",
    description: Annotated[str, typer.Option(help="Agent description")] = "",
    instructions: Annotated[str, typer.Option(help="Reusable instructions for every run")] = "",
    default: Annotated[bool, typer.Option("--default")] = False,
    read_only: Annotated[bool, typer.Option(help="Does not modify the workspace")] = False,
    timeout: Annotated[int | None, typer.Option()] = None,
) -> None:
    """Create an agent profile (options are validated against the agent's whitelist)."""
    with client() as api:
        p = call(
            api.post,
            "/api/agent-profiles",
            {
                "name": name,
                "agent_type": agent,
                "description": description,
                "instructions": instructions,
                "options": json.loads(options),
                "is_default": default,
                "write_mode": not read_only,
                "timeout_seconds": timeout,
            },
        )
    console.print(f"profile {p['name']} ({p['agent_type']}) created")


# ---------------------------------------------------------------- decisions / artifacts / search


@decision_app.command("list")
def decision_list(all_: Annotated[bool, typer.Option("--all")] = False) -> None:
    """Pending decisions (or all with --all)."""
    with client() as api:
        page = call(api.get, "/api/decisions", params=None if all_ else {"status": "pending"})
    if out(page):
        return
    rows = [{**d, "opts": ", ".join(f"{o['key']}={o['label']}" for o in d["options"])} for d in page["items"]]
    table(
        rows,
        [
            ("id", "id"),
            ("status", "status"),
            ("question", "question"),
            ("opts", "options"),
            ("recommendation", "recommended"),
        ],
    )


@decision_app.command("resolve")
def decision_resolve(
    decision_id: str,
    option: Annotated[str | None, typer.Option("--option", "-o")] = None,
    response: Annotated[str | None, typer.Option("--response", "-m")] = None,
    resume: Annotated[bool, typer.Option(help="Dispatch the task's last agent again")] = False,
) -> None:
    """Answer a decision."""
    with client() as api:
        res = call(
            api.post,
            f"/api/decisions/{decision_id}/resolve",
            {"selected_option": option, "response": response, "resume": resume},
        )
    console.print(f"decision resolved{'; resumed run ' + res['resumed_run']['id'] if res.get('resumed_run') else ''}")


@artifact_app.command("list")
def artifact_list(
    task: Annotated[str | None, typer.Option()] = None, query: Annotated[str | None, typer.Option("-q")] = None
) -> None:
    """List artifacts."""
    params: dict[str, Any] = {}
    with client() as api:
        if task:
            params["task_id"] = call(api.get, f"/api/tasks/{task}")["id"]
        if query:
            params["q"] = query
        page = call(api.get, "/api/artifacts", params=params)
    if out(page):
        return
    table(
        page["items"],
        [
            ("name", "name"),
            ("type", "type"),
            ("version_label", "version"),
            ("storage_uri", "location"),
            ("verification", "verification"),
        ],
    )


@artifact_app.command("add")
def artifact_add(
    name: str,
    path: Annotated[str, typer.Argument(help="Path or URI of the artifact")],
    type_: Annotated[str, typer.Option("--type", "-t")] = "other",
    task: Annotated[str | None, typer.Option()] = None,
    description: Annotated[str, typer.Option()] = "",
    usage: Annotated[str, typer.Option(help="Command to use it")] = "",
    build: Annotated[str, typer.Option(help="Command to build it")] = "",
    version: Annotated[str | None, typer.Option()] = None,
    checksum: Annotated[bool, typer.Option(help="Compute sha256 of a local file")] = True,
) -> None:
    """Register an artifact (reference mode)."""
    import hashlib

    local = Path(path).expanduser()
    sha, size, uri = None, None, path
    if local.is_file():
        uri = str(local.resolve())
        size = local.stat().st_size
        if checksum:
            sha = hashlib.sha256(local.read_bytes()).hexdigest()
    body: dict[str, Any] = {
        "name": name,
        "type": type_,
        "storage_uri": uri,
        "description": description,
        "usage": {"command": usage},
        "build": {"command": build},
        "sha256": sha,
        "size_bytes": size,
        "version_label": version,
    }
    with client() as api:
        if task:
            body["task_id"] = call(api.get, f"/api/tasks/{task}")["id"]
        a = call(api.post, "/api/artifacts", body)
    console.print(f"artifact {a['name']} registered ({a['id']})")


@app.command("search")
def search_cmd(query: str, kind: Annotated[list[str] | None, typer.Option("--kind", "-k")] = None) -> None:
    """Search projects, workspaces, tasks, decisions, artifacts and knowledge."""
    with client() as api:
        res = call(api.get, "/api/search", params={"q": query, "kind": kind} if kind else {"q": query})
    if out(res):
        return
    table(res["hits"], [("kind", "kind"), ("title", "title"), ("snippet", "snippet"), ("id", "id")])


@app.command("status")
def status_cmd() -> None:
    """Server health and a dashboard summary."""
    c = cfg()
    with client() as api:
        health = call(api.get, "/api/health")
        dash = call(api.get, "/api/dashboard")
    if out({"health": health, "dashboard": dash}):
        return
    console.print(
        f"server {c.server_url}: {health['status']} (db {health['database']}, schema {health['schema_revision']})"
    )
    console.print(
        f"projects: {dash['projects_total']}  tasks: {dash['tasks_by_status']}  "
        f"runners online: {dash['runners_online']}  active runs: {len(dash['active_runs'])}  "
        f"pending decisions: {len(dash['pending_decisions'])}"
    )


# ---------------------------------------------------------------- runner


@runner_app.command("start")
def runner_start(
    config_path: Annotated[Path | None, typer.Option("--config", help="runner.yaml path")] = None,
    allowed_root: Annotated[list[str] | None, typer.Option("--allowed-root", help="Allowed workspace root")] = None,
    max_parallel: Annotated[int | None, typer.Option()] = None,
    name: Annotated[str | None, typer.Option()] = None,
    enable_fake: Annotated[bool, typer.Option("--enable-fake-agent", help="Enable the test agent")] = False,
    verbose: Annotated[bool, typer.Option("-v")] = False,
) -> None:
    """Run the Agent Runner in the foreground on this host."""
    from ohmypm_runner.config import load_config
    from ohmypm_runner.service import RunnerService

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    overrides: dict[str, Any] = {"max_parallel": max_parallel, "name": name}
    if allowed_root:
        overrides["allowed_roots"] = allowed_root
    if enable_fake:
        overrides["enable_fake_agent"] = True
    if state.url:
        overrides["server_url"] = state.url
    config = load_config(config_path, **overrides)
    if not config.allowed_roots:
        err.print(
            "[red]No allowed_roots configured.[/] Pass --allowed-root DIR or set allowed_roots in runner.yaml "
            "(agents may only run in workspaces below these directories)."
        )
        raise typer.Exit(2)
    try:
        service = RunnerService(config)
    except ValueError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc

    async def serve() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, service.stop)
        await service.serve()

    console.print(f"ohmypm runner {service.runner_id} → {config.server_url} (roots: {', '.join(config.allowed_roots)})")
    asyncio.run(serve())


@runner_app.command("status")
def runner_status() -> None:
    """Runners known to the server."""
    with client() as api:
        runners = call(api.get, "/api/runners")
    if out(runners):
        return
    rows = [
        {
            **r,
            "state": "online" if r["online"] else "offline",
            "agents_ok": ", ".join(a["agent_type"] for a in r["agents"] if a.get("available")),
        }
        for r in runners
    ]
    table(
        rows,
        [
            ("name", "runner"),
            ("host_id", "host"),
            ("state", "state"),
            ("active_runs", "active"),
            ("max_parallel", "max"),
            ("agents_ok", "agents"),
            ("last_heartbeat_at", "last heartbeat"),
        ],
    )


@runner_app.command("init-config")
def runner_init_config(
    allowed_root: Annotated[list[str], typer.Option("--allowed-root")],
    token: Annotated[str | None, typer.Option(help="Runner token (or keep it in OHMYPM_RUNNER_TOKEN)")] = None,
    server_url: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Write ~/.config/ohmypm/runner.yaml."""
    from ohmypm_runner.config import default_config_path

    path = default_config_path()
    if path.exists():
        err.print(f"[red]{path} already exists; edit it instead[/]")
        raise typer.Exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"server_url: {server_url or cfg().server_url}", "allowed_roots:"]
    lines += [f"  - {Path(r).expanduser().resolve()}" for r in allowed_root]
    lines += [
        "max_parallel: 2",
        "allow_dangerous: false",
        "agents:",
        "  claude: {enabled: true}",
        "  codex: {enabled: true}",
        "  pi: {enabled: true}",
        "  dsh: {enabled: true}",
        "trusted_custom_agents: []",
    ]
    if token:
        lines.insert(1, f"token: {token}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    console.print(f"wrote {path}")


# ---------------------------------------------------------------- mcp


@mcp_app.command("config")
def mcp_config(
    client_name: Annotated[str, typer.Argument(help="claude | codex | json")] = "json",
    token_env: Annotated[str, typer.Option(help="Env var holding the agent token")] = "OHMYPM_AGENT_TOKEN",  # noqa: S107
) -> None:
    """Print an MCP client configuration snippet for this server."""
    url = f"{cfg().server_url}/mcp"
    if client_name == "claude":
        print(f'claude mcp add --transport http ohmypm {url} --header "Authorization: Bearer ${{{token_env}}}"')
    elif client_name == "codex":
        print(f'[mcp_servers.ohmypm]\nurl = "{url}"\nbearer_token_env_var = "{token_env}"')
    else:
        print(
            json.dumps(
                {
                    "mcpServers": {
                        "ohmypm": {"type": "http", "url": url, "headers": {"Authorization": f"Bearer ${{{token_env}}}"}}
                    }
                },
                indent=2,
            )
        )


@app.command("open")
def open_cmd() -> None:
    """Print the Web UI URL (with a one-time token fragment for login)."""
    c = cfg()
    print(f"{c.server_url}/#token={c.token}" if c.token else c.server_url)


def run() -> None:
    app(prog_name="ohmypm")


if __name__ == "__main__":
    sys.exit(app())
