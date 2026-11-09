"""Install ohmypm instructions into the *global* configuration of coding agents.

Each agent reads a user-level instruction file. ohmypm adds one clearly marked
block to that file and never touches anything outside it:

    <!-- ohmypm:start ... -->
    ...
    <!-- ohmypm:end -->

Verified locations (checked against the installed tools, 2026-11-04):

* Claude Code 2.1.x - ``$CLAUDE_CONFIG_DIR/CLAUDE.md`` (default ``~/.claude``);
  supports ``@path`` imports, so the block only imports the shared file.
* Codex CLI 0.166  - ``$CODEX_HOME/AGENTS.override.md`` if present, otherwise
  ``$CODEX_HOME/AGENTS.md`` (default ``~/.codex``). No imports: inline copy.
* Pi 1.1           - ``$PI_CODING_AGENT_DIR`` (default ``~/.pi/agent``); the
  first existing of AGENTS.override.md, AGENTS.md, AGENTS.MD, CLAUDE.md,
  CLAUDE.MD. Inline copy.
* DSH 0.2          - ``$DSH_HOME/AGENTS.md`` (default ``~/.dsh``). Inline copy.
* Antigravity CLI  - ``~/.gemini/config/AGENTS.md`` (global rules;
  bundled customization guide and official discovery docs, 2026-11-09).

Project-level instruction files are never modified.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ohmypm.agents.instructions import DEFAULT_INSTRUCTIONS
from ohmypm.config import Settings, ensure_private_dir
from ohmypm.core.errors import ValidationError
from ohmypm.storage.files import atomic_write_text

START_PREFIX = "<!-- ohmypm:start"
END_MARKER = "<!-- ohmypm:end -->"
_START_RE = re.compile(r"^<!-- ohmypm:start\b.*-->\s*$")
_END_RE = re.compile(r"^<!-- ohmypm:end -->\s*$")
MAX_BACKUPS = 10

State = Literal["installed", "outdated", "not_installed", "not_detected", "inactive", "broken"]


@dataclass(frozen=True)
class AgentSpec:
    key: str
    label: str
    env_var: str | None
    default_home: Callable[[Path], Path]
    candidates: tuple[str, ...]  # in the agent's own precedence order
    fallback: str  # file to create when none exists
    binaries: tuple[str, ...]
    mode: Literal["inline", "import"]
    verified_with: str

    def home(self, env: Mapping[str, str], user_home: Path) -> Path:
        value = env.get(self.env_var) if self.env_var else None
        return Path(value).expanduser() if value else self.default_home(user_home)

    def active_file(self, home: Path) -> Path:
        for name in self.candidates:
            path = home / name
            if path.is_file():
                return path
        return home / self.fallback


AGENTS: dict[str, AgentSpec] = {
    spec.key: spec
    for spec in (
        AgentSpec(
            key="claude",
            label="Claude Code",
            env_var="CLAUDE_CONFIG_DIR",
            default_home=lambda h: h / ".claude",
            candidates=("CLAUDE.md",),
            fallback="CLAUDE.md",
            binaries=("claude",),
            mode="import",
            verified_with="Claude Code 2.1.303 (user memory ~/.claude/CLAUDE.md with @imports)",
        ),
        AgentSpec(
            key="codex",
            label="Codex CLI",
            env_var="CODEX_HOME",
            default_home=lambda h: h / ".codex",
            candidates=("AGENTS.override.md", "AGENTS.md"),
            fallback="AGENTS.md",
            binaries=("codex",),
            mode="inline",
            verified_with="codex-cli 0.166.0 (global AGENTS.override.md / AGENTS.md in CODEX_HOME)",
        ),
        AgentSpec(
            key="pi",
            label="Pi",
            env_var="PI_CODING_AGENT_DIR",
            default_home=lambda h: h / ".pi" / "agent",
            candidates=("AGENTS.override.md", "AGENTS.md", "AGENTS.MD", "CLAUDE.md", "CLAUDE.MD"),
            fallback="AGENTS.md",
            binaries=("pi",),
            mode="inline",
            verified_with="pi-coding-agent 1.1.0 (context file in the agent dir)",
        ),
        AgentSpec(
            key="dsh",
            label="DSH",
            env_var="DSH_HOME",
            default_home=lambda h: h / ".dsh",
            candidates=("AGENTS.md",),
            fallback="AGENTS.md",
            binaries=("dsh",),
            mode="inline",
            verified_with="@deepseek-ai/dsh 0.2.0-rc.2 (dsh-agent-instructions: $DSH_HOME/AGENTS.md)",
        ),
        AgentSpec(
            key="agy",
            label="Antigravity",
            env_var=None,
            default_home=lambda h: h / ".gemini" / "config",
            candidates=("AGENTS.md",),
            fallback="AGENTS.md",
            binaries=("agy",),
            mode="inline",
            verified_with="Antigravity CLI global rules (bundled guide + official discovery docs, 2026-11-09)",
        ),
    )
}


class AgentStatus(BaseModel):
    agent: str
    label: str
    state: State
    detected: bool
    target: str | None
    mode: str
    verified_with: str
    message: str = ""


class AgentChange(BaseModel):
    agent: str
    label: str
    action: Literal["installed", "updated", "unchanged", "removed", "skipped", "failed"]
    target: str | None
    message: str = ""
    backup: str | None = None


@dataclass
class _Block:
    start: int
    end: int  # index of the end-marker line (inclusive)


def find_blocks(lines: list[str]) -> tuple[list[_Block], bool]:
    """Locate managed blocks. Returns ``(blocks, well_formed)``."""
    blocks: list[_Block] = []
    start: int | None = None
    ok = True
    for i, line in enumerate(lines):
        if _START_RE.match(line):
            if start is not None:
                ok = False
            start = i
        elif _END_RE.match(line):
            if start is None:
                ok = False
                continue
            blocks.append(_Block(start, i))
            start = None
    if start is not None:
        ok = False
    return blocks, ok


def strip_blocks(text: str) -> str:
    """Remove every managed block (and the blank separator line ohmypm added)."""
    lines = text.split("\n")
    blocks, _ = find_blocks(lines)
    for block in reversed(blocks):
        del lines[block.start : block.end + 1]
        before = block.start - 1
        blank_before = before >= 0 and lines[before] == ""
        blank_after = block.start >= len(lines) or lines[block.start] == ""
        if blank_before and blank_after:
            del lines[before]
    result = "\n".join(lines)
    return result.rstrip("\n") + "\n" if result.strip() else ""


class AgentManager:
    def __init__(
        self,
        settings: Settings,
        *,
        home: Path | None = None,
        env: Mapping[str, str] | None = None,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.settings = settings
        self.env = dict(os.environ if env is None else env)
        self.user_home = home or Path(self.env.get("HOME") or Path.home())
        self.which = which

    # ------------------------------------------------------- instructions
    @property
    def instructions_path(self) -> Path:
        return self.settings.agent_instructions_file

    def ensure_instructions(self, *, reset: bool = False) -> tuple[Path, bool]:
        """Create the shared instructions file if needed. Returns ``(path, written)``."""
        path = self.instructions_path
        if path.is_file() and not reset:
            return path, False
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_file() and path.read_text(encoding="utf-8") != DEFAULT_INSTRUCTIONS:
            shutil.copy2(path, path.with_name(path.name + f".{datetime.now():%Y%m%d-%H%M%S}.bak"))
        atomic_write_text(path, DEFAULT_INSTRUCTIONS, mode=0o644)
        return path, True

    def instructions_text(self) -> str:
        path = self.instructions_path
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return DEFAULT_INSTRUCTIONS

    def _import_ref(self) -> str:
        path = self.instructions_path.absolute()
        try:
            return "@~/" + str(path.relative_to(self.user_home))
        except ValueError:
            return "@" + str(path)

    def render_block(self, spec: AgentSpec) -> str:
        body = self._import_ref() if spec.mode == "import" else self.instructions_text().strip("\n")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
        source = self.instructions_path
        header = (
            f"{START_PREFIX} managed by `ohmypm agents`; edit {source} and run "
            f"`ohmypm agents update` instead of editing this block. sha={digest} -->"
        )
        return f"{header}\n{body}\n{END_MARKER}"

    # ------------------------------------------------------------ helpers
    def _specs(self, agents: Sequence[str] | None) -> list[AgentSpec]:
        if not agents or list(agents) == ["all"]:
            return list(AGENTS.values())
        unknown = [a for a in agents if a not in AGENTS]
        if unknown:
            raise ValidationError(
                f"Unknown agent(s): {', '.join(unknown)}", details={"allowed": [*AGENTS, "all"]}
            )
        return [AGENTS[a] for a in dict.fromkeys(agents)]

    def detected(self, spec: AgentSpec) -> bool:
        return spec.home(self.env, self.user_home).is_dir() or any(self.which(b) for b in spec.binaries)

    def _files_with_blocks(self, spec: AgentSpec) -> list[Path]:
        home = spec.home(self.env, self.user_home)
        found = []
        for name in dict.fromkeys(spec.candidates + (spec.fallback,)):
            path = home / name
            if path.is_file() and START_PREFIX in path.read_text(encoding="utf-8", errors="replace"):
                found.append(path)
        return found

    def _backup(self, spec: AgentSpec, path: Path) -> Path | None:
        if not path.exists():
            return None
        folder = ensure_private_dir(self.settings.data_dir / "agent-backups" / spec.key)
        target = folder / f"{path.name}.{datetime.now():%Y%m%d-%H%M%S-%f}"
        shutil.copy2(path, target)
        backups = sorted(folder.glob(f"{path.name}.*"))
        for old in backups[:-MAX_BACKUPS]:
            old.unlink(missing_ok=True)
        return target

    @staticmethod
    def _write(path: Path, text: str) -> None:
        # Write through symlinks (e.g. dotfile managers) instead of replacing them.
        real = Path(os.path.realpath(path))
        mode = real.stat().st_mode & 0o777 if real.exists() else 0o644
        real.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(real, text, mode=mode)

    # -------------------------------------------------------------- status
    def status(self, agents: Sequence[str] | None = None) -> list[AgentStatus]:
        result = []
        for spec in self._specs(agents):
            home = spec.home(self.env, self.user_home)
            active = spec.active_file(home)
            detected = self.detected(spec)
            expected = self.render_block(spec)
            state: State
            message = ""
            with_blocks = self._files_with_blocks(spec)
            if active.is_file():
                text = active.read_text(encoding="utf-8", errors="replace")
                lines = text.split("\n")
                blocks, ok = find_blocks(lines)
                if not ok:
                    state, message = "broken", "unbalanced ohmypm markers; fix or remove them manually"
                elif blocks:
                    current = "\n".join(lines[blocks[0].start : blocks[0].end + 1])
                    state = "installed" if current == expected and len(blocks) == 1 else "outdated"
                    if state == "outdated":
                        message = "run `ohmypm agents update`"
                else:
                    state = "inactive" if with_blocks else ("not_installed" if detected else "not_detected")
            else:
                state = "inactive" if with_blocks else ("not_installed" if detected else "not_detected")
            if state == "inactive":
                message = (
                    f"block found in {', '.join(map(str, with_blocks))}, but {spec.label} reads {active}; "
                    "run `ohmypm agents install`"
                )
            if spec.mode == "import" and state == "installed" and not self.instructions_path.is_file():
                state, message = "broken", f"imported file {self.instructions_path} is missing"
            result.append(
                AgentStatus(
                    agent=spec.key,
                    label=spec.label,
                    state=state,
                    detected=detected,
                    target=str(active),
                    mode=spec.mode,
                    verified_with=spec.verified_with,
                    message=message,
                )
            )
        return result

    # ------------------------------------------------------------- install
    def install(
        self,
        agents: Sequence[str] | None = None,
        *,
        force: bool = False,
        dry_run: bool = False,
        only_installed: bool = False,
    ) -> list[AgentChange]:
        if not dry_run:
            self.ensure_instructions()
        changes = []
        for spec in self._specs(agents):
            changes.append(
                self._install_one(spec, force=force, dry_run=dry_run, only_installed=only_installed)
            )
        return changes

    def _install_one(
        self, spec: AgentSpec, *, force: bool, dry_run: bool, only_installed: bool
    ) -> AgentChange:
        home = spec.home(self.env, self.user_home)
        active = spec.active_file(home)
        stale = [p for p in self._files_with_blocks(spec) if p != active]
        if (
            only_installed
            and not stale
            and not (active.is_file() and START_PREFIX in active.read_text("utf-8"))
        ):
            return AgentChange(
                agent=spec.key,
                label=spec.label,
                action="skipped",
                target=str(active),
                message="not installed",
            )
        if not self.detected(spec) and not force:
            return AgentChange(
                agent=spec.key,
                label=spec.label,
                action="skipped",
                target=str(active),
                message=f"{spec.label} not found ({home} missing, no `{spec.binaries[0]}` on PATH); use --force",
            )
        original = active.read_text(encoding="utf-8") if active.is_file() else ""
        lines = original.split("\n")
        blocks, ok = find_blocks(lines)
        if not ok:
            return AgentChange(
                agent=spec.key,
                label=spec.label,
                action="failed",
                target=str(active),
                message="unbalanced ohmypm markers in the file; fix or remove them manually",
            )
        block = self.render_block(spec)
        if blocks:
            first = blocks[0]
            new_lines = lines[: first.start] + block.split("\n") + lines[first.end + 1 :]
            # Collapse duplicated blocks.
            text = "\n".join(new_lines)
            extra = find_blocks(text.split("\n"))[0][1:]
            if extra:
                kept = text.split("\n")
                for b in reversed(extra):
                    del kept[b.start : b.end + 1]
                text = "\n".join(kept)
            action = "updated"
        else:
            base = original.rstrip("\n")
            text = (base + "\n\n" if base else "") + block + "\n"
            action = "installed"
        if text == original and not stale:
            return AgentChange(agent=spec.key, label=spec.label, action="unchanged", target=str(active))
        backup = None
        if not dry_run:
            if text != original:
                backup = self._backup(spec, active)
                self._write(active, text)
            for path in stale:
                self._backup(spec, path)
                self._write(path, strip_blocks(path.read_text(encoding="utf-8")))
        message = f"moved from {', '.join(map(str, stale))}" if stale else ""
        if text == original:
            action = "updated"
        return AgentChange(
            agent=spec.key,
            label=spec.label,
            action=action,
            target=str(active),
            message=message,
            backup=str(backup) if backup else None,
        )

    def update(
        self, agents: Sequence[str] | None = None, *, reset_instructions: bool = False, dry_run: bool = False
    ) -> list[AgentChange]:
        """Re-sync blocks where ohmypm is already installed."""
        if reset_instructions and not dry_run:
            self.ensure_instructions(reset=True)
        return self.install(agents, force=True, dry_run=dry_run, only_installed=True)

    # -------------------------------------------------------------- remove
    def remove(self, agents: Sequence[str] | None = None, *, dry_run: bool = False) -> list[AgentChange]:
        changes = []
        for spec in self._specs(agents):
            files = self._files_with_blocks(spec)
            if not files:
                changes.append(
                    AgentChange(
                        agent=spec.key,
                        label=spec.label,
                        action="unchanged",
                        target=str(spec.active_file(spec.home(self.env, self.user_home))),
                        message="not installed",
                    )
                )
                continue
            for path in files:
                original = path.read_text(encoding="utf-8")
                if not find_blocks(original.split("\n"))[1]:
                    changes.append(
                        AgentChange(
                            agent=spec.key,
                            label=spec.label,
                            action="failed",
                            target=str(path),
                            message="unbalanced ohmypm markers; fix them manually",
                        )
                    )
                    continue
                text = strip_blocks(original)
                backup = None
                if not dry_run:
                    backup = self._backup(spec, path)
                    if text:
                        self._write(path, text)
                    else:
                        # The file only contained our block: remove it entirely.
                        Path(os.path.realpath(path)).unlink()
                changes.append(
                    AgentChange(
                        agent=spec.key,
                        label=spec.label,
                        action="removed",
                        target=str(path),
                        message="" if text else "file contained only the ohmypm block and was deleted",
                        backup=str(backup) if backup else None,
                    )
                )
        return changes
