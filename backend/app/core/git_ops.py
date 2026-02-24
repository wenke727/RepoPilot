from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import httpx

from app.models import RepoConfig


class GitError(RuntimeError):
    pass


class PRCredentialsMissing(GitError):
    pass


@dataclass
class WorktreeInfo:
    path: Path
    branch: str


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise GitError(f"Command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-").lower() or "task"


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _detect_remote_default_branch(repo_path: Path) -> str:
    proc = _run(
        ["git", "-C", str(repo_path), "symbolic-ref", "refs/remotes/origin/HEAD"],
        check=False,
    )
    if proc.returncode != 0:
        return ""
    ref = proc.stdout.strip()
    if not ref:
        return ""
    return ref.rsplit("/", 1)[-1]


def _candidate_base_refs(repo_path: Path, preferred: str) -> list[str]:
    default_branch = _detect_remote_default_branch(repo_path)

    candidates = [
        f"origin/{preferred}",
        preferred,
        f"origin/{default_branch}" if default_branch else "",
        default_branch,
    ]
    return _unique(candidates)


def create_worktree(repo: RepoConfig, worktrees_root: Path, task_id: str, title: str) -> WorktreeInfo:
    repo_path = Path(repo.root_path)
    branch = f"task/{task_id}-{_slug(title)[:36]}"
    target = worktrees_root / repo.id / task_id
    target.parent.mkdir(parents=True, exist_ok=True)

    # Best-effort cleanup from previous crashed/failed runs.
    _run(["git", "-C", str(repo_path), "worktree", "remove", "--force", str(target)], check=False)
    _run(["git", "-C", str(repo_path), "worktree", "prune"], check=False)
    _run(["git", "-C", str(repo_path), "branch", "-D", branch], check=False)

    if target.exists():
        shutil.rmtree(target)

    _run(["git", "-C", str(repo_path), "fetch", "origin"], check=False)

    last_err = ""
    for base_ref in _candidate_base_refs(repo_path, repo.main_branch):
        add_cmd = [
            "git",
            "-C",
            str(repo_path),
            "worktree",
            "add",
            "-b",
            branch,
            str(target),
            base_ref,
        ]
        result = _run(add_cmd, check=False)
        if result.returncode == 0:
            return WorktreeInfo(path=target, branch=branch)
        last_err = result.stderr.strip() or result.stdout.strip()

    raise GitError(
        "Command failed: git -C "
        f"{repo_path} worktree add -b {branch} {target} <base-ref>\n"
        f"Candidates tried: {_candidate_base_refs(repo_path, repo.main_branch)}\n"
        f"{last_err}"
    )


def setup_isolated_data(worktree: Path, repo: RepoConfig) -> None:
    (worktree / "data").mkdir(parents=True, exist_ok=True)
    forbidden = set(repo.forbidden_symlink_paths)

    for rel in repo.shared_symlink_paths:
        if rel in forbidden:
            continue
        src = Path(repo.root_path) / rel
        if not src.exists():
            continue
        dest = worktree / rel
        if any((worktree / denied).resolve() == dest.resolve() for denied in forbidden if (worktree / denied).exists()):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() or dest.is_symlink():
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        os.symlink(src, dest)


def has_changes(worktree: Path) -> bool:
    proc = _run(["git", "status", "--porcelain"], cwd=worktree)
    return bool(proc.stdout.strip())


def has_material_changes(worktree: Path, baseline_commit: str) -> bool:
    # Treat either working tree diff or a moved HEAD as real changes.
    if has_changes(worktree):
        return True
    return current_commit(worktree) != baseline_commit


def commit_all(worktree: Path, message: str) -> str:
    _run(["git", "add", "-A"], cwd=worktree)
    diff = _run(["git", "diff", "--cached", "--quiet"], cwd=worktree, check=False)
    if diff.returncode == 0:
        return current_commit(worktree)
    _run(["git", "commit", "-m", message], cwd=worktree)
    return current_commit(worktree)


def current_commit(worktree: Path) -> str:
    proc = _run(["git", "rev-parse", "HEAD"], cwd=worktree)
    return proc.stdout.strip()


def rebase_with_main(worktree: Path, main_branch: str) -> None:
    _run(["git", "fetch", "origin", main_branch], cwd=worktree)
    _run(["git", "rebase", f"origin/{main_branch}"], cwd=worktree)


def run_tests(worktree: Path, test_command: str, timeout: int = 1200) -> None:
    proc = subprocess.run(test_command, cwd=worktree, shell=True, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        combined = f"{proc.stdout}\n{proc.stderr}"
        if 'Missing script: "test"' in combined:
            raise GitError(
                "Tests failed: npm script \"test\" not found. "
                "Please set repo.test_command to a valid command via PATCH /api/repos/{repo_id}, "
                "for example: \"npm run test:unit\" or \"echo skip-tests\"."
            )
        raise GitError(f"Tests failed:\n{proc.stdout}\n{proc.stderr}")


def push_branch(worktree: Path, branch: str) -> None:
    _run(["git", "push", "-u", "origin", branch], cwd=worktree)


def build_compare_url(github_repo: str, base: str, head: str) -> str:
    repo = github_repo.strip("/")
    if not repo or "/" not in repo:
        return ""
    return f"https://github.com/{repo}/compare/{quote(base, safe='')}...{quote(head, safe='')}?expand=1"


def create_pr(
    repo: RepoConfig,
    branch: str,
    title: str,
    body: str,
    github_token: str | None = None,
) -> str:
    if shutil.which("gh"):
        cmd = [
            "gh",
            "pr",
            "create",
            "--repo",
            repo.github_repo,
            "--base",
            repo.main_branch,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            url = proc.stdout.strip().splitlines()[-1].strip()
            if url.startswith("http"):
                return url
        # fallback to API if gh is unavailable or failed

    token = github_token or os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise PRCredentialsMissing("Cannot create PR: neither gh success nor GITHUB_TOKEN available")
    if "/" not in repo.github_repo:
        raise GitError(f"Invalid github_repo: {repo.github_repo}")

    owner, name = repo.github_repo.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{name}/pulls"
    payload = {
        "title": title,
        "head": branch,
        "base": repo.main_branch,
        "body": body,
    }

    with httpx.Client(timeout=20.0) as client:
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json=payload,
        )
    if resp.status_code >= 300:
        raise GitError(f"Create PR failed: {resp.status_code} {resp.text}")

    data = resp.json()
    return str(data.get("html_url", ""))


def cleanup_worktree(repo: RepoConfig, worktree: Path, branch: str) -> None:
    repo_path = Path(repo.root_path)
    _run(["git", "-C", str(repo_path), "worktree", "remove", "--force", str(worktree)], check=False)
    _run(["git", "-C", str(repo_path), "worktree", "prune"], check=False)
    _run(["git", "-C", str(repo_path), "branch", "-D", branch], check=False)


def snapshot_worktree(worktree: Path, artifacts_root: Path, task_id: str, run_id: str) -> Path:
    target = artifacts_root / task_id / run_id
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    # Keep task output files for debugging; skip git metadata.
    shutil.copytree(worktree, target, ignore=shutil.ignore_patterns(".git"))
    return target
