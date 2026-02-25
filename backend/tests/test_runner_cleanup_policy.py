from __future__ import annotations

from pathlib import Path

from app.config import load_settings
from app.core import git_ops
from app.core.runner import TaskRunner
from app.models import TaskMode
from app.store.json_store import JsonStore


def _create_store(tmp_path: Path) -> JsonStore:
    return JsonStore(state_dir=tmp_path / "state", repos_dir=tmp_path / "repos")


def _inject_demo_repo(store: JsonStore, repo_root: Path) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / ".git").mkdir(exist_ok=True)
    with store._lock("repos"):
        rows = store._read_json(store.repos_file)
        rows.append(
            {
                "id": "demo",
                "name": "demo",
                "root_path": str(repo_root),
                "main_branch": "main",
                "test_command": "echo skip-tests",
                "github_repo": "owner/demo",
                "shared_symlink_paths": [],
                "forbidden_symlink_paths": ["PROGRESS.md"],
                "enabled": True,
            }
        )
        store._write_json_atomic(store.repos_file, rows)


def _create_exec_task(store: JsonStore, title: str):
    return store.create_task(
        {
            "repo_id": "demo",
            "title": title,
            "prompt": f"do-{title}",
            "mode": TaskMode.EXEC.value,
            "permission_mode": "BYPASS",
            "priority": 0,
        }
    )


def _mock_exec_pipeline(monkeypatch, worktree: Path) -> None:
    monkeypatch.setattr(
        "app.core.runner.git_ops.create_worktree",
        lambda repo, root, task_id, title: git_ops.WorktreeInfo(path=worktree, branch="task/demo"),
    )
    monkeypatch.setattr("app.core.runner.git_ops.setup_isolated_data", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.core.runner.git_ops.current_commit", lambda *args, **kwargs: "base")
    monkeypatch.setattr("app.core.runner.git_ops.has_material_changes", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.core.runner.git_ops.commit_all", lambda *args, **kwargs: "abc123")
    monkeypatch.setattr("app.core.runner.git_ops.rebase_with_main", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.core.runner.git_ops.run_tests", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.core.runner.git_ops.push_branch", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.core.runner.git_ops.create_pr", lambda *args, **kwargs: "https://example.com/pr/1")


def test_exec_success_keeps_worktree_until_done(tmp_path: Path, monkeypatch):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))

    task = _create_exec_task(store, "success")
    run = store.create_run(task.id, worker_id="worker-1", python_env_used="test-env")
    worktree = tmp_path / "worktrees" / "demo" / task.id
    worktree.mkdir(parents=True, exist_ok=True)

    _mock_exec_pipeline(monkeypatch, worktree)
    monkeypatch.setattr(runner, "_stream_claude", lambda task, prompt, workdir: (0, "assistant-output", False))

    cleanup_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.core.runner.git_ops.cleanup_worktree",
        lambda repo, path, branch: cleanup_calls.append((str(path), branch)),
    )

    runner._run_exec(task, run.id)

    task_after = store.get_task(task.id)
    run_after = store.get_run(run.id)
    assert task_after is not None
    assert task_after.status.value == "REVIEW"
    assert run_after is not None
    assert run_after.worktree_path == str(worktree)
    assert cleanup_calls == []


def test_exec_failed_cleans_worktree_and_clears_path(tmp_path: Path, monkeypatch):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))

    task = _create_exec_task(store, "failed")
    run = store.create_run(task.id, worker_id="worker-1", python_env_used="test-env")
    worktree = tmp_path / "worktrees" / "demo" / task.id
    worktree.mkdir(parents=True, exist_ok=True)

    _mock_exec_pipeline(monkeypatch, worktree)
    monkeypatch.setattr(runner, "_stream_claude", lambda task, prompt, workdir: (1, "", False))

    order: list[str] = []
    snapshot_path = tmp_path / "state" / "artifacts" / task.id / run.id

    def _snapshot(worktree: Path, artifacts_root: Path, task_id: str, run_id: str) -> Path:
        order.append("snapshot")
        snapshot_path.mkdir(parents=True, exist_ok=True)
        return snapshot_path

    def _cleanup(repo, path: Path, branch: str) -> None:
        order.append("cleanup")

    monkeypatch.setattr("app.core.runner.git_ops.snapshot_worktree", _snapshot)
    monkeypatch.setattr("app.core.runner.git_ops.cleanup_worktree", _cleanup)

    runner._run_exec(task, run.id)

    task_after = store.get_task(task.id)
    run_after = store.get_run(run.id)
    assert task_after is not None
    assert task_after.status.value == "FAILED"
    assert run_after is not None
    assert run_after.worktree_path == ""
    assert run_after.metrics.get("artifact_path") == str(snapshot_path)
    assert order == ["snapshot", "cleanup"]


def test_exec_cancelled_cleans_with_artifact_then_clears_path(tmp_path: Path, monkeypatch):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))

    task = _create_exec_task(store, "cancelled")
    run = store.create_run(task.id, worker_id="worker-1", python_env_used="test-env")
    worktree = tmp_path / "worktrees" / "demo" / task.id
    worktree.mkdir(parents=True, exist_ok=True)

    _mock_exec_pipeline(monkeypatch, worktree)
    monkeypatch.setattr(runner, "_stream_claude", lambda task, prompt, workdir: (0, "", True))

    order: list[str] = []
    snapshot_path = tmp_path / "state" / "artifacts" / task.id / run.id

    def _snapshot(worktree: Path, artifacts_root: Path, task_id: str, run_id: str) -> Path:
        order.append("snapshot")
        snapshot_path.mkdir(parents=True, exist_ok=True)
        return snapshot_path

    def _cleanup(repo, path: Path, branch: str) -> None:
        order.append("cleanup")

    monkeypatch.setattr("app.core.runner.git_ops.snapshot_worktree", _snapshot)
    monkeypatch.setattr("app.core.runner.git_ops.cleanup_worktree", _cleanup)

    runner._run_exec(task, run.id)

    task_after = store.get_task(task.id)
    run_after = store.get_run(run.id)
    assert task_after is not None
    assert task_after.status.value == "CANCELLED"
    assert run_after is not None
    assert run_after.worktree_path == ""
    assert run_after.metrics.get("artifact_path") == str(snapshot_path)
    assert order == ["snapshot", "cleanup"]
