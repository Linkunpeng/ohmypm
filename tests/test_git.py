"""Git commit stamps on records and summaries, and summary drift in status/context."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ohmypm.config import load_settings
from ohmypm.core import gitinfo
from ohmypm.core.schemas import EntryCreate, SummaryUpdate
from ohmypm.core.service import MemoryService
from ohmypm.storage.database import Database

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "Test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.com")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    commit(root, "init")
    return root


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(root: Path, message: str) -> str:
    (root / "log.txt").open("a").write(message + "\n")
    _git(root, "add", "log.txt")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def pid(service: MemoryService, repo: Path) -> str:
    return service.register(repo)[0].id


# ------------------------------------------------------------------ gitinfo
def test_head_and_commits_since(repo: Path) -> None:
    first = _git(repo, "rev-parse", "HEAD")
    assert gitinfo.head(repo) == {"commit": first, "branch": "main"}
    assert gitinfo.commits_since(repo, first) == 0
    commit(repo, "two")
    commit(repo, "three")
    assert gitinfo.commits_since(repo, first) == 2
    _git(repo, "checkout", "-q", "--detach", first)
    assert gitinfo.head(repo) == {"commit": first, "branch": None}


def test_git_failures_yield_none(tmp_path: Path, repo: Path) -> None:
    assert gitinfo.head(tmp_path / "missing") is None
    plain = tmp_path / "plain"
    plain.mkdir()
    assert gitinfo.head(plain) is None
    assert gitinfo.commits_since(repo, "0" * 40) is None  # unknown commit (e.g. after a rebase)
    assert gitinfo.commits_since(repo, "--all") is None  # never passed through as an option


def test_valid_stamp_and_label() -> None:
    sha = "a" * 40
    assert gitinfo.valid_stamp({"commit": sha, "branch": "dev"}) == {"commit": sha, "branch": "dev"}
    assert gitinfo.valid_stamp({"commit": sha, "branch": 3}) == {"commit": sha, "branch": None}
    assert gitinfo.valid_stamp({"commit": "HEAD"}) is None
    assert gitinfo.valid_stamp("abc") is None
    assert gitinfo.label({"commit": sha, "branch": "dev"}) == "aaaaaaa (dev)"
    assert gitinfo.label({"commit": sha, "branch": None}) == "aaaaaaa"


# ------------------------------------------------------------------ records
def test_new_records_are_stamped(service: MemoryService, repo: Path, pid: str) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    entry = service.add_entry(EntryCreate(type="milestone", title="Done"), path=repo / "sub")
    assert entry.metadata["git"] == {"commit": head, "branch": "main"}
    # An explicit stamp from the caller wins.
    custom = {"commit": "b" * 40, "branch": "feature"}
    entry = service.add_entry(EntryCreate(title="Imported", metadata={"git": custom}), project=pid)
    assert entry.metadata["git"] == custom


def test_records_outside_git_are_not_stamped(service: MemoryService, workspace: Path) -> None:
    service.register(workspace)
    entry = service.add_entry(EntryCreate(title="No repo"), path=workspace)
    assert "git" not in entry.metadata


def test_stamps_can_be_disabled(tmp_path: Path, repo: Path) -> None:
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / "config.toml").write_text("[git]\nstamps = false\n")
    settings = load_settings()
    assert settings.git_stamps is False
    db = Database(settings)
    try:
        svc = MemoryService(settings, db)
        svc.register(repo)
        entry = svc.add_entry(EntryCreate(title="Quiet"), path=repo)
        summary, _ = svc.set_summary(SummaryUpdate(overview="x"), path=repo)
        assert "git" not in entry.metadata
        assert summary.git is None
        assert svc.status(repo)["summary_commits_behind"] is None
    finally:
        db.dispose()


# ------------------------------------------------------------------ summary
def test_summary_stamp_and_drift(service: MemoryService, repo: Path, pid: str) -> None:
    first = _git(repo, "rev-parse", "HEAD")
    summary, _ = service.set_summary(SummaryUpdate(overview="Robot"), project=pid)
    assert summary.git == {"commit": first, "branch": "main"}
    status = service.status(repo)
    assert status["summary_git"] == summary.git
    assert status["summary_commits_behind"] == 0
    assert status["records_since_summary"] == 0
    assert "Since the summary" not in service.context(project=pid).markdown

    commit(repo, "feature a")
    second = commit(repo, "feature b")
    service.add_entry(EntryCreate(type="milestone", title="Feature A"), project=pid)
    status = service.status(repo)
    assert status["summary_commits_behind"] == 2
    assert status["records_since_summary"] == 1
    ctx = service.context(project=pid)
    assert ctx.stats["summary_commits_behind"] == 2
    assert ctx.stats["records_since_summary"] == 1
    assert f"at `{first[:7]}` (main)" in ctx.markdown
    assert f"2 commit(s) on HEAD (`git log --oneline {first[:7]}..HEAD`)" in ctx.markdown
    assert "1 new record(s)" in ctx.markdown
    # Records show the commit they were written at.
    assert f"at {second[:7]}" in ctx.markdown

    # Updating the summary moves the stamp; the old stamp stays in the revision.
    summary, _ = service.set_summary(SummaryUpdate(current_state="A done"), project=pid)
    assert summary.git == {"commit": second, "branch": "main"}
    assert service.summary_history(project=pid)[-1]["data"]["git"] == {"commit": first, "branch": "main"}
    status = service.status(repo)
    assert (status["summary_commits_behind"], status["records_since_summary"]) == (0, 0)
    assert "Since the summary" not in service.context(project=pid).markdown


def test_unchanged_summary_keeps_its_stamp(service: MemoryService, repo: Path, pid: str) -> None:
    first = _git(repo, "rev-parse", "HEAD")
    service.set_summary(SummaryUpdate(overview="Robot"), project=pid)
    commit(repo, "more")
    summary, changed = service.set_summary(SummaryUpdate(overview="Robot"), project=pid)
    assert not changed
    assert summary.git["commit"] == first


def test_rewritten_history_drops_commit_count(service: MemoryService, repo: Path, pid: str) -> None:
    commit(repo, "to be dropped")
    service.set_summary(SummaryUpdate(overview="Robot"), project=pid)
    _git(repo, "reset", "-q", "--hard", "HEAD~1")
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    _git(repo, "gc", "-q", "--prune=now")
    status = service.status(repo)
    assert status["summary_git"] is not None
    assert status["summary_commits_behind"] is None
    assert "commit(s) on HEAD" not in service.context(project=pid).markdown


# ---------------------------------------------------------------------- CLI
def test_cli_shows_stamps(repo: Path, pid: str) -> None:
    from typer.testing import CliRunner

    from ohmypm.cli.common import reset_service
    from ohmypm.cli.main import app

    reset_service()
    runner = CliRunner()
    head = _git(repo, "rev-parse", "HEAD")[:7]
    result = runner.invoke(app, ["log", "add", "--cwd", str(repo), "-t", "Stamped", "-c", "x", "--json"])
    assert result.exit_code == 0, result.output
    number = json.loads(result.output)["sequence"]
    result = runner.invoke(app, ["log", "show", str(number), "--cwd", str(repo)])
    assert f"git: {head} (main)" in result.output
    assert "metadata:" not in result.output
    runner.invoke(app, ["summary", "set", "--cwd", str(repo), "--content", "## Overview\n\nRobot"])
    commit(repo, "later")
    result = runner.invoke(app, ["status", "--cwd", str(repo)])
    assert f"at {head}" in result.output
    assert "since then: 1 commit(s)" in result.output


def test_context_flags_records_written_many_commits_ago(service: MemoryService, repo: Path, pid: str) -> None:
    first = _git(repo, "rev-parse", "HEAD")
    service.add_entry(EntryCreate(type="knowledge", title="Build with make", content="make all"), project=pid)
    for n in range(3):
        commit(repo, f"change {n}")
    recent = service.add_entry(EntryCreate(type="milestone", title="Recent work"), project=pid)

    service.update_context_settings({"old_record_commits": 3}, project=pid)
    ctx = service.context(project=pid)
    entries = {e.sequence: e for s in ctx.sections for e in s.entries}
    assert entries[1].commits_since == 3 and entries[1].outdated
    assert entries[recent.sequence].commits_since == 0 and not entries[recent.sequence].outdated
    assert f"at {first[:7]} (3 commits ago)" in ctx.markdown

    service.update_context_settings({"old_record_commits": 4}, project=pid)
    ctx = service.context(project=pid)
    assert "commits ago" not in ctx.markdown
    service.update_context_settings({"old_record_commits": 0}, project=pid)  # disabled
    assert "commits ago" not in service.context(project=pid).markdown
