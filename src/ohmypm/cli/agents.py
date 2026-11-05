"""``ohmypm agents``: manage ohmypm instructions in global agent configuration."""

from __future__ import annotations

from typing import Annotated

import typer

from ohmypm.cli.common import JsonOpt, emit_json, get_service, out

agents_app = typer.Typer(
    help="Install ohmypm usage instructions into the global config of Codex, Claude Code, Pi and DSH.",
    no_args_is_help=True,
)

AgentOpt = Annotated[
    list[str] | None,
    typer.Option("--agent", "-a", help="claude | codex | pi | dsh | all (default: all). Repeatable."),
]
DryRunOpt = Annotated[bool, typer.Option("--dry-run", help="Show what would change without writing.")]


def _manager():  # noqa: ANN202
    from ohmypm.agents.manager import AgentManager

    return AgentManager(get_service().settings)


def _print_changes(changes, json_: bool, dry_run: bool) -> None:  # noqa: ANN001
    if json_:
        emit_json({"dry_run": dry_run, "changes": changes})
        return
    prefix = "[dry-run] " if dry_run else ""
    for c in changes:
        line = f"{prefix}{c.label:<12} {c.action:<10} {c.target or ''}"
        if c.message:
            line += f"  ({c.message})"
        out(line)
        if c.backup:
            out(f"{'':<13}backup: {c.backup}")


@agents_app.command("install")
def agents_install(
    agent: AgentOpt = None,
    force: Annotated[
        bool, typer.Option("--force", help="Install even if the agent is not detected.")
    ] = False,
    dry_run: DryRunOpt = False,
    json_: JsonOpt = False,
) -> None:
    """Add (or refresh) the managed ohmypm block in each agent's global instructions.

    Existing content is preserved; re-running never duplicates the block.
    """
    manager = _manager()
    changes = manager.install(agent, force=force, dry_run=dry_run)
    _print_changes(changes, json_, dry_run)
    if not json_ and not dry_run:
        out(f"\nShared instructions: {manager.instructions_path}")


@agents_app.command("update")
def agents_update(
    agent: AgentOpt = None,
    reset_instructions: Annotated[
        bool,
        typer.Option(
            "--reset-instructions", help="Overwrite the shared instructions with the built-in default."
        ),
    ] = False,
    dry_run: DryRunOpt = False,
    json_: JsonOpt = False,
) -> None:
    """Re-sync installed blocks after editing ~/.config/ohmypm/agent-instructions.md."""
    _print_changes(
        _manager().update(agent, reset_instructions=reset_instructions, dry_run=dry_run), json_, dry_run
    )


@agents_app.command("remove")
def agents_remove(agent: AgentOpt = None, dry_run: DryRunOpt = False, json_: JsonOpt = False) -> None:
    """Remove the ohmypm block (only the block) from each agent's global instructions."""
    _print_changes(_manager().remove(agent, dry_run=dry_run), json_, dry_run)


@agents_app.command("status")
def agents_status(agent: AgentOpt = None, json_: JsonOpt = False) -> None:
    """Show where each agent reads global instructions and whether ohmypm is installed."""
    statuses = _manager().status(agent)
    if json_:
        emit_json(statuses)
        return
    for s in statuses:
        out(f"{s.label:<12} {s.state:<14} {s.target}")
        out(f"{'':<13}verified with {s.verified_with}; mode: {s.mode}")
        if s.message:
            out(f"{'':<13}{s.message}")


@agents_app.command("instructions")
def agents_instructions(
    path_only: Annotated[bool, typer.Option("--path", help="Only print the file path.")] = False,
) -> None:
    """Print the shared agent instructions (creating the default file if missing)."""
    manager = _manager()
    path, _ = manager.ensure_instructions()
    out(str(path) if path_only else manager.instructions_text().rstrip())
