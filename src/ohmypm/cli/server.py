"""``ohmypm web`` and ``ohmypm mcp``: long-running local servers."""

from __future__ import annotations

import ipaddress
import webbrowser
from typing import Annotated

import typer

from ohmypm.cli.common import err, get_service, out


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def web(
    host: Annotated[str | None, typer.Option("--host", help="Bind address (default 127.0.0.1).")] = None,
    port: Annotated[int | None, typer.Option("--port", help="Port (default 8737).")] = None,
    open_browser: Annotated[bool, typer.Option("--open", help="Open the browser.")] = False,
    no_auth: Annotated[
        bool,
        typer.Option("--no-auth", help="Disable the access token (only for trusted single-user machines)."),
    ] = False,
    allow_remote: Annotated[
        bool, typer.Option("--allow-remote", help="Permit binding to a non-loopback address.")
    ] = False,
    dev_origin: Annotated[
        list[str] | None,
        typer.Option("--dev-origin", help="Extra allowed browser origin (e.g. Vite dev server). Repeatable."),
    ] = None,
) -> None:
    """Start the local Web UI and HTTP API (Ctrl+C to stop)."""
    import uvicorn

    from ohmypm.api.app import create_app
    from ohmypm.api.security import load_or_create_token

    settings = get_service().settings
    host = host or settings.web_host
    port = port or settings.web_port
    if not _is_loopback(host) and not allow_remote:
        err(
            f"Refusing to listen on non-loopback address {host}; pass --allow-remote if you really want this."
        )
        raise typer.Exit(2)
    token = None if no_auth else load_or_create_token(settings)
    # With --allow-remote the Host header cannot be predicted, so it is not checked.
    app = create_app(
        get_service(), token=token, extra_origins=dev_origin or [], public_host="*" if allow_remote else host
    )
    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown_host}:{port}/"
    login_url = f"{url}?token={token}" if token else url
    out(f"ohmypm web UI: {login_url}")
    if token:
        out("(the token is stored in your data directory; the link sets a browser cookie)")
    if open_browser:
        webbrowser.open(login_url)
    uvicorn.run(app, host=host, port=port, log_level="warning", proxy_headers=False, server_header=False)


def mcp() -> None:
    """Run the MCP server on stdio (configure this command in your MCP client)."""
    from ohmypm.mcp.server import run_stdio

    run_stdio(get_service())
