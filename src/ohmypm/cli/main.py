"""ohmypm command line interface.

Exit codes: 0 ok · 1 error · 2 usage · 3 project not registered ·
4 not found · 5 validation · 6 conflict.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ohmypm import __version__
from ohmypm.cli import data, memory, projects
from ohmypm.cli.agents import agents_app
from ohmypm.cli.common import OhmypmGroup
from ohmypm.cli.log import log_app
from ohmypm.cli.server import mcp, web

app = typer.Typer(
    name="ohmypm",
    cls=OhmypmGroup,
    help=(
        "ohmypm - Oh My Project Memory. Local, zero-intrusion development memory for AI agents.\n\n"
        "Commands detect the project from the current directory (or use --project / --cwd). "
        "Add --json for machine-readable output."
    ),
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"ohmypm {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option("--version", "-V", callback=_version, is_eager=True, help="Show the version and exit."),
    ] = False,
) -> None:
    pass


app.command("register")(projects.register)
app.command("unregister")(projects.unregister)
app.command("status")(projects.status)
app.command("list")(projects.list_projects)
app.add_typer(projects.project_app, name="project")
app.add_typer(log_app, name="log")
app.add_typer(memory.summary_app, name="summary")
app.command("context")(memory.context)
app.command("search")(memory.search)
app.add_typer(data.assets_app, name="assets")
app.add_typer(agents_app, name="agents")
app.command("web")(web)
app.command("mcp")(mcp)
app.command("export")(data.export)
app.command("backup")(data.backup)
app.command("restore")(data.restore)
app.command("doctor")(data.doctor)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
