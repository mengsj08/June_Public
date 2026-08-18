#!/usr/bin/env python3
"""Tests for the Python git hygiene governance probe."""

import importlib.util
import subprocess
from pathlib import Path
import pytest


_HERE = Path(__file__).resolve().parent
_GIT_HYGIENE = _HERE.parent / "governance" / "git_hygiene.py"
if not _GIT_HYGIENE.is_file():
    pytest.skip("missing optional source path: governance/git_hygiene.py", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("git_hygiene", _GIT_HYGIENE)
git_hygiene = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(git_hygiene)


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _commit_all(repo, message="commit"):
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)


def test_default_does_not_fetch_and_tracked_secret_is_path_only(tmp_path, monkeypatch):
    root = tmp_path / "Documents"
    repo = root / "AI-Agent-Hub" / "demo"
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    _init_repo(repo)
    secret_value = "DO_NOT_LEAK_THIS_SECRET_VALUE"
    (repo / ".env").write_text(f"TOKEN={secret_value}\n", encoding="utf-8")
    (repo / ".env.example").write_text("TOKEN=example\n", encoding="utf-8")
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    _commit_all(repo, "init")
    _git(repo, "remote", "add", "origin", str(remote))

    real_git = git_hygiene._git

    def guard_fetch(repo_path, args, timeout=20):
        assert args[0] != "fetch"
        return real_git(repo_path, args, timeout=timeout)

    monkeypatch.setattr(git_hygiene, "_git", guard_fetch)

    result = git_hygiene.scan_git_hygiene(str(root))
    scanned = result["repos"][0]

    assert result["schema"] == "git_hygiene/v1"
    assert result["fetch"] is False
    assert scanned["fetch"]["attempted"] is False
    assert scanned["tracked_secrets"] == [{"path": ".env"}]
    assert secret_value not in repr(result)


def test_dirty_no_remote_exclude_drift_and_broad_add_docs(tmp_path):
    root = tmp_path / "Documents"
    repo = root / "ResearchLab" / "demo"
    _init_repo(repo)
    (repo / "README.md").write_text("# demo\n\nRun `git add -A` before commit.\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    _commit_all(repo, "init")
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (repo / ".git" / "info" / "exclude").write_text("# local\nlocal-only/\n", encoding="utf-8")

    result = git_hygiene.scan_git_hygiene(str(root))
    scanned = result["repos"][0]

    assert scanned["no_remote"] is True
    assert scanned["dirty"]["count"] == 1
    assert scanned["exclude_drift"] == [{"pattern": "local-only/"}]
    assert scanned["broad_add_docs"][0]["path"] == "README.md"
    assert {
        "dirty_tree",
        "no_remote",
        "local_exclude_drift",
        "doc_broad_add_antipattern",
    }.issubset(set(scanned["risks"]))


def test_explicit_no_remote_policy_is_not_a_backup_risk(tmp_path):
    root = tmp_path / "Documents"
    repo = root / "AI-Agent-Hub" / "local-control-plane"
    _init_repo(repo)
    (repo / "AGENTS.md").write_text("# Local policy\n\nNo git remote by design.\n", encoding="utf-8")
    (repo / "README.md").write_text("# local\n", encoding="utf-8")
    _commit_all(repo, "init")

    result = git_hygiene.scan_git_hygiene(str(root))
    scanned = result["repos"][0]

    assert scanned["no_remote"] is True
    assert scanned["expected_no_remote"] is True
    assert scanned["no_remote_policy_evidence"] == "AGENTS.md"
    assert "no_remote" not in scanned["risks"]
    assert result["summary"]["no_remote_repos"] == 0
    assert result["summary"]["expected_no_remote_repos"] == 1


def test_remote_probe_failure_is_not_misreported_as_no_remote(tmp_path, monkeypatch):
    root = tmp_path / "Documents"
    repo = root / "AI-Agent-Hub" / "probe-failure"
    _init_repo(repo)
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    _commit_all(repo, "init")
    real_git_lines = git_hygiene._git_lines

    def fail_remote(repo_path, args, timeout=20):
        if args == ["remote"]:
            return [], "sandbox denied runtime library", 1
        return real_git_lines(repo_path, args, timeout=timeout)

    monkeypatch.setattr(git_hygiene, "_git_lines", fail_remote)
    result = git_hygiene.scan_git_hygiene(str(root))
    scanned = result["repos"][0]

    assert scanned["no_remote"] is False
    assert scanned["remote"]["error"] == "remote_probe_failed"
    assert scanned["probe_errors"] == ["remote_probe_failed"]
    assert "git_probe_error" in scanned["risks"]
    assert "no_remote" not in scanned["risks"]
    assert result["summary"]["no_remote_repos"] == 0
    assert result["summary"]["probe_error_repos"] == 1


def test_ahead_behind_and_pull_overlap_are_structured(tmp_path):
    root = tmp_path / "Documents"
    remote = tmp_path / "origin.git"
    repo = root / "AI-Agent-Hub" / "diverged"
    other = tmp_path / "other"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    _init_repo(repo)
    (repo / "shared.txt").write_text("base\n", encoding="utf-8")
    (repo / "local.txt").write_text("base\n", encoding="utf-8")
    _commit_all(repo, "init")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")

    subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(other)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "Test User")
    (other / "incoming.txt").write_text("remote\n", encoding="utf-8")
    _commit_all(other, "remote change")
    _git(other, "push", "origin", "main")

    _git(repo, "fetch", "origin")
    (repo / "local.txt").write_text("local\n", encoding="utf-8")
    _commit_all(repo, "local change")
    (repo / "incoming.txt").write_text("local untracked overlap\n", encoding="utf-8")

    result = git_hygiene.scan_git_hygiene(str(root))
    scanned = result["repos"][0]

    assert scanned["ahead_behind"]["ahead"] == 1
    assert scanned["ahead_behind"]["behind"] == 1
    assert scanned["pull_safety"]["status"] == "unsafe_overlap"
    assert scanned["pull_safety"]["overlap_paths"] == ["incoming.txt"]
    assert {"unpushed_commits", "behind_remote", "pull_unsafe_overlap"}.issubset(set(scanned["risks"]))


def test_merged_remote_branch_is_reported(tmp_path):
    root = tmp_path / "Documents"
    remote = tmp_path / "origin.git"
    repo = root / "KnowledgeManagement" / "branches"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    _init_repo(repo)
    (repo / "README.md").write_text("# branches\n", encoding="utf-8")
    _commit_all(repo, "init")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")
    _git(repo, "checkout", "-q", "-b", "old-topic")
    (repo / "old.txt").write_text("old\n", encoding="utf-8")
    _commit_all(repo, "old branch")
    _git(repo, "push", "-u", "origin", "old-topic")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--ff-only", "old-topic")
    _git(repo, "push", "origin", "main")
    _git(repo, "fetch", "origin")

    result = git_hygiene.scan_git_hygiene(str(root))
    scanned = result["repos"][0]

    assert "origin/old-topic" in scanned["merged_remote_branches"]
    assert "merged_branch_undeleted" in scanned["risks"]
