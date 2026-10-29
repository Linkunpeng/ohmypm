"""Instruction/skill/MCP file discovery report for ``ohmypm agent doctor``.

ohmypm does not translate between agent config formats; each CLI discovers its own files when it is
started with the workspace as its working directory. This module only reports which files exist and
which agents are expected to read them, so users can spot gaps (e.g. a CLAUDE.md that Codex ignores).

Sources: Claude Code ``--help`` (CLAUDE.md auto-discovery); Pi ``--help`` (AGENTS.md and CLAUDE.md
discovery); for Codex and dsh, file names found in the installed binaries (indicative only).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CANDIDATES: list[tuple[str, tuple[str, ...], str]] = [
    ("AGENTS.md", ("codex", "pi", "dsh"), "shared agent instructions"),
    ("AGENTS.override.md", ("codex",), "Codex override instructions"),
    ("CLAUDE.md", ("claude", "pi", "dsh"), "Claude Code project memory"),
    ("CLAUDE.local.md", ("claude",), "Claude Code local memory"),
    (".claude/settings.json", ("claude",), "Claude Code project settings"),
    (".claude/skills", ("claude",), "Claude Code project skills"),
    (".mcp.json", ("claude",), "project MCP servers (Claude Code)"),
    (".agents/skills", ("codex", "pi", "dsh"), "shared skills directory"),
    (".codex", ("codex",), "Codex project config"),
    (".pi", ("pi",), "Pi project config"),
    (".dsh/skills", ("dsh",), "dsh skills"),
]


@dataclass
class FileReport:
    path: str
    exists: bool
    read_by: tuple[str, ...]
    description: str


def discover(workspace: Path) -> list[FileReport]:
    return [FileReport(rel, (workspace / rel).exists(), agents, desc) for rel, agents, desc in CANDIDATES]


def compatibility_notes(reports: list[FileReport]) -> list[str]:
    present = {r.path for r in reports if r.exists}
    notes = []
    if "AGENTS.md" in present and "CLAUDE.md" not in present:
        notes.append(
            "AGENTS.md exists but CLAUDE.md does not: Claude Code will not read AGENTS.md by itself. "
            "Consider a CLAUDE.md containing '@AGENTS.md'."
        )
    if "CLAUDE.md" in present and "AGENTS.md" not in present:
        notes.append("CLAUDE.md exists but AGENTS.md does not: Codex will not see these instructions.")
    if ".claude/skills" in present and ".agents/skills" not in present:
        notes.append("Skills only exist under .claude/skills; other agents look in .agents/skills.")
    return notes
