from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core import git_ops
from app.models import RepoConfig


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def test_has_material_changes_detects_new_commit(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)

    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=repo)
    _run(["git", "commit", "-m", "init"], cwd=repo)

    baseline = git_ops.current_commit(repo)
    assert git_ops.has_material_changes(repo, baseline) is False

    # Simulate model committing directly in the worktree.
    (repo / "README.md").write_text("updated\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=repo)
    _run(["git", "commit", "-m", "model commit"], cwd=repo)

    assert git_ops.has_material_changes(repo, baseline) is True


def test_build_compare_url_encodes_branch_name():
    url = git_ops.build_compare_url(
        github_repo="owner/repo",
        base="main",
        head="task/中文-branch",
    )
    assert url == "https://github.com/owner/repo/compare/main...task%2F%E4%B8%AD%E6%96%87-branch?expand=1"


def test_create_pr_raises_credentials_missing_without_gh_or_token(monkeypatch):
    repo = RepoConfig(
        id="demo",
        name="demo",
        root_path="/tmp/demo",
        main_branch="main",
        test_command="echo skip-tests",
        github_repo="owner/demo",
        shared_symlink_paths=[],
        forbidden_symlink_paths=["PROGRESS.md"],
        enabled=True,
    )
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(git_ops.shutil, "which", lambda _: None)

    with pytest.raises(git_ops.PRCredentialsMissing):
        git_ops.create_pr(repo=repo, branch="task/x", title="t", body="b")
