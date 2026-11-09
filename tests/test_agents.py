from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ohmypm.agents.instructions import DEFAULT_INSTRUCTIONS
from ohmypm.agents.manager import END_MARKER, START_PREFIX, AgentManager, strip_blocks
from ohmypm.cli.common import reset_service
from ohmypm.cli.main import app
from tests.conftest import tree_snapshot


def no_binaries(_name: str) -> None:
    return None


@pytest.fixture
def home(isolated_env: Path) -> Path:
    return isolated_env


@pytest.fixture
def manager(settings, home: Path) -> AgentManager:
    return AgentManager(settings, home=home, env={"HOME": str(home)}, which=no_binaries)


def make_agent_homes(home: Path) -> None:
    for d in (".claude", ".codex", ".pi/agent", ".dsh", ".gemini/config"):
        (home / d).mkdir(parents=True, exist_ok=True)


def test_undetected_agents_are_skipped(manager: AgentManager, home: Path) -> None:
    changes = manager.install()
    assert {c.action for c in changes} == {"skipped"}
    assert not (home / ".claude").exists() and not (home / ".codex").exists()
    assert {s.state for s in manager.status()} == {"not_detected"}
    # The shared instructions file is created in ohmypm's config dir.
    assert manager.instructions_path.read_text(encoding="utf-8") == DEFAULT_INSTRUCTIONS


def test_force_install_creates_files(manager: AgentManager, home: Path) -> None:
    changes = manager.install(["codex"], force=True)
    assert changes[0].action == "installed"
    assert (home / ".codex" / "AGENTS.md").is_file()


def test_install_preserves_user_content_and_is_idempotent(manager: AgentManager, home: Path) -> None:
    make_agent_homes(home)
    user_claude = "# My rules\n\n- be terse\n"
    (home / ".claude" / "CLAUDE.md").write_text(user_claude, encoding="utf-8")
    user_codex = "Always run tests.\n"
    (home / ".codex" / "AGENTS.md").write_text(user_codex, encoding="utf-8")

    changes = {c.agent: c for c in manager.install()}
    assert {c.action for c in changes.values()} == {"installed"}
    assert changes["claude"].backup and Path(changes["claude"].backup).read_text() == user_claude
    assert settings_dir_contains(changes["claude"].backup, manager)

    claude = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith(user_claude)
    assert f"\n@{manager.instructions_path}\n" in claude  # import mode (config dir outside HOME here)
    assert "ohmypm status --json" not in claude
    codex = (home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    assert codex.startswith(user_codex) and "ohmypm status --json" in codex  # inline mode
    assert (home / ".pi" / "agent" / "AGENTS.md").is_file()
    assert (home / ".dsh" / "AGENTS.md").is_file()
    assert {s.state for s in manager.status()} == {"installed"}

    snapshot = {p: p.read_text() for p in home.rglob("*.md")}
    second = manager.install()
    assert {c.action for c in second} == {"unchanged"}
    assert {p: p.read_text() for p in home.rglob("*.md")} == snapshot
    assert codex.count(START_PREFIX) == 1 and codex.count(END_MARKER) == 1


def settings_dir_contains(path: str, manager: AgentManager) -> bool:
    return str(manager.settings.data_dir) in path


def test_update_after_editing_instructions(manager: AgentManager, home: Path) -> None:
    make_agent_homes(home)
    manager.install()
    custom = "# Custom ohmypm rules\nAlways log decisions.\n"
    manager.instructions_path.write_text(custom, encoding="utf-8")
    states = {s.agent: s.state for s in manager.status()}
    assert states["codex"] == "outdated" and states["claude"] == "installed"  # import needs no update
    changes = {c.agent: c.action for c in manager.update()}
    assert changes["codex"] == "updated" and changes["claude"] == "unchanged"
    assert "Always log decisions." in (home / ".codex" / "AGENTS.md").read_text()
    assert {s.state for s in manager.status()} == {"installed"}
    # Install never overwrites a customised instructions file.
    manager.install()
    assert manager.instructions_path.read_text() == custom
    manager.update(reset_instructions=True)
    assert manager.instructions_path.read_text() == DEFAULT_INSTRUCTIONS
    assert list(manager.instructions_path.parent.glob("agent-instructions.md.*.bak"))


def test_update_skips_agents_without_block(manager: AgentManager, home: Path) -> None:
    make_agent_homes(home)
    manager.install(["codex"])
    changes = {c.agent: c.action for c in manager.update()}
    assert changes == {
        "claude": "skipped",
        "codex": "unchanged",
        "pi": "skipped",
        "dsh": "skipped",
        "agy": "skipped",
    }
    assert not (home / ".claude" / "CLAUDE.md").exists()


def test_remove_restores_original(manager: AgentManager, home: Path) -> None:
    make_agent_homes(home)
    original = "# Mine\n\nKeep this.\n"
    (home / ".codex" / "AGENTS.md").write_text(original, encoding="utf-8")
    manager.install()
    changes = {c.agent: c for c in manager.remove()}
    assert (home / ".codex" / "AGENTS.md").read_text() == original
    # Files that only contained the block are deleted again.
    assert not (home / ".claude" / "CLAUDE.md").exists()
    assert "deleted" in changes["claude"].message
    assert {s.state for s in manager.status()} == {"not_installed"}
    assert {c.action for c in manager.remove()} == {"unchanged"}


def test_block_in_middle_of_file_is_updated_in_place(manager: AgentManager, home: Path) -> None:
    make_agent_homes(home)
    manager.install(["dsh"])
    path = home / ".dsh" / "AGENTS.md"
    block = path.read_text()
    path.write_text("top\n\n" + block + "\nbottom\n", encoding="utf-8")
    manager.instructions_path.write_text("new rules\n", encoding="utf-8")
    manager.update(["dsh"])
    text = path.read_text()
    assert text.startswith("top\n\n" + START_PREFIX) and text.rstrip().endswith("bottom")
    assert "new rules" in text
    manager.remove(["dsh"])
    assert path.read_text() == "top\n\nbottom\n"


def test_codex_override_file_takes_precedence(manager: AgentManager, home: Path) -> None:
    make_agent_homes(home)
    manager.install(["codex"])
    assert START_PREFIX in (home / ".codex" / "AGENTS.md").read_text()
    (home / ".codex" / "AGENTS.override.md").write_text("override rules\n", encoding="utf-8")
    status = manager.status(["codex"])[0]
    assert status.state == "inactive" and status.target.endswith("AGENTS.override.md")
    change = manager.install(["codex"])[0]
    assert change.target.endswith("AGENTS.override.md") and "moved from" in change.message
    assert START_PREFIX in (home / ".codex" / "AGENTS.override.md").read_text()
    assert (
        not (home / ".codex" / "AGENTS.md").exists()
        or START_PREFIX not in (home / ".codex" / "AGENTS.md").read_text()
    )


def test_pi_uses_existing_claude_md_in_agent_dir(manager: AgentManager, home: Path) -> None:
    make_agent_homes(home)
    (home / ".pi" / "agent" / "CLAUDE.md").write_text("pi rules\n", encoding="utf-8")
    change = manager.install(["pi"])[0]
    assert change.target == str(home / ".pi" / "agent" / "CLAUDE.md")
    assert not (home / ".pi" / "agent" / "AGENTS.md").exists()


def test_env_overrides(settings, home: Path, tmp_path: Path) -> None:
    codex_home = tmp_path / "custom-codex"
    codex_home.mkdir()
    manager = AgentManager(
        settings, home=home, env={"HOME": str(home), "CODEX_HOME": str(codex_home)}, which=no_binaries
    )
    assert manager.install(["codex"])[0].action == "installed"
    assert (codex_home / "AGENTS.md").is_file()


def test_detection_by_binary(settings, home: Path) -> None:
    manager = AgentManager(
        settings,
        home=home,
        env={"HOME": str(home)},
        which=lambda name: "/usr/bin/pi" if name == "pi" else None,
    )
    assert manager.install(["pi"])[0].action == "installed"
    assert (home / ".pi" / "agent" / "AGENTS.md").is_file()


def test_symlinked_config_is_written_through(manager: AgentManager, home: Path, tmp_path: Path) -> None:
    make_agent_homes(home)
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "AGENTS.md"
    real.write_text("dotfile rules\n", encoding="utf-8")
    link = home / ".codex" / "AGENTS.md"
    link.symlink_to(real)
    manager.install(["codex"])
    assert link.is_symlink()
    assert START_PREFIX in real.read_text()


def test_broken_markers_are_not_touched(manager: AgentManager, home: Path) -> None:
    make_agent_homes(home)
    path = home / ".codex" / "AGENTS.md"
    broken = f"mine\n{START_PREFIX} x -->\nhalf a block\n"
    path.write_text(broken, encoding="utf-8")
    assert manager.install(["codex"])[0].action == "failed"
    assert manager.status(["codex"])[0].state == "broken"
    assert manager.remove(["codex"])[0].action == "failed"
    assert path.read_text() == broken


def test_dry_run_writes_nothing(manager: AgentManager, home: Path) -> None:
    make_agent_homes(home)
    before = tree_snapshot(home)
    changes = manager.install(dry_run=True)
    assert {c.action for c in changes} == {"installed"}
    assert tree_snapshot(home) == before
    assert not manager.instructions_path.exists()


def test_registered_projects_are_never_touched(
    manager: AgentManager, home: Path, workspace: Path, service
) -> None:
    make_agent_homes(home)
    (workspace / "AGENTS.md").write_text("project rules\n", encoding="utf-8")
    (workspace / "CLAUDE.md").write_text("project claude\n", encoding="utf-8")
    service.register(workspace)
    before = tree_snapshot(workspace)
    manager.install()
    manager.update()
    manager.remove()
    assert tree_snapshot(workspace) == before


def test_strip_blocks_without_block_is_identity() -> None:
    assert strip_blocks("a\n\nb\n") == "a\n\nb\n"


def test_unknown_agent(manager: AgentManager) -> None:
    from ohmypm.core.errors import ValidationError

    with pytest.raises(ValidationError):
        manager.install(["vim"])


def test_agy_global_rules_lifecycle(manager: AgentManager, home: Path) -> None:
    # The CLI on PATH is enough to detect agy before its config directory exists.
    manager.which = lambda name: "/usr/bin/agy" if name == "agy" else None
    path = home / ".gemini" / "config" / "AGENTS.md"
    other_rules = home / ".gemini" / "AGENTS.md"
    other_rules.parent.mkdir(parents=True)
    other_rules.write_text("# Personal rules\nKeep these too.\n")
    original = "# Global rules\n\nPreserve this content.\n"

    planned = manager.install(["agy"], dry_run=True)
    assert planned[0].action == "installed" and planned[0].target == str(path)
    assert not path.exists()
    path.parent.mkdir(parents=True)
    path.write_text(original)

    installed = manager.install(["agy"])[0]
    assert installed.action == "installed"
    assert installed.backup and Path(installed.backup).read_text() == original
    assert path.read_text().startswith(original)
    assert DEFAULT_INSTRUCTIONS in path.read_text()
    assert manager.status(["agy"])[0].state == "installed"
    assert manager.install(["agy"])[0].action == "unchanged"

    manager.instructions_path.write_text("# Updated memory rules\nUse structured Markdown.\n")
    assert manager.status(["agy"])[0].state == "outdated"
    assert manager.update(["agy"])[0].action == "updated"
    assert "Use structured Markdown." in path.read_text()
    assert path.read_text().count(START_PREFIX) == 1

    assert manager.remove(["agy"])[0].action == "removed"
    assert path.read_text() == original
    assert other_rules.read_text() == "# Personal rules\nKeep these too.\n"


def test_agents_cli(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_agent_homes(home)
    monkeypatch.setenv("PATH", "/nonexistent")
    runner = CliRunner()

    def run(*args: str):
        reset_service()
        result = runner.invoke(app, ["agents", *args])
        assert result.exit_code == 0, (args, result.stdout, result.stderr)
        return result

    data = json.loads(run("install", "--json").stdout)
    assert {c["action"] for c in data["changes"]} == {"installed"}
    status = json.loads(run("status", "--json").stdout)
    assert {s["state"] for s in status} == {"installed"}
    assert "verified with" in run("status").stdout
    assert "ohmypm status --json" in run("instructions").stdout
    assert json.loads(run("update", "--json").stdout)["changes"][0]["action"] == "unchanged"
    removed = json.loads(run("remove", "--agent", "codex", "--json").stdout)
    assert removed["changes"][0]["action"] == "removed"
    bad = runner.invoke(app, ["agents", "install", "--agent", "vim"])
    assert bad.exit_code == 5
    reset_service()


def test_claude_import_uses_home_relative_path(home: Path, tmp_path: Path) -> None:
    from ohmypm.config import load_settings

    settings = load_settings(config_dir=home / ".config" / "ohmypm")
    manager = AgentManager(settings, home=home, env={"HOME": str(home)}, which=no_binaries)
    make_agent_homes(home)
    manager.install(["claude"])
    assert "\n@~/.config/ohmypm/agent-instructions.md\n" in (home / ".claude" / "CLAUDE.md").read_text()
