from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import tasks
from app.config import load_settings
from app.core.runner import TaskRunner
from app.models import TaskMode
from app.store.json_store import JsonStore


class _DummyScheduler:
    def request_cancel(self, task_id: str) -> None:  # pragma: no cover - not used in these tests
        _ = task_id


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


def _build_client(store: JsonStore, runner: TaskRunner) -> TestClient:
    app = FastAPI()
    app.state.store = store
    app.state.runner = runner
    app.state.scheduler = _DummyScheduler()
    app.include_router(tasks.router)
    return TestClient(app)


def _create_review_exec_task(store: JsonStore, task_title: str, worktree_path: Path) -> tuple[str, str]:
    task = store.create_task(
        {
            "repo_id": "demo",
            "title": task_title,
            "prompt": f"exec-{task_title}",
            "mode": TaskMode.EXEC.value,
            "permission_mode": "BYPASS",
            "priority": 0,
        }
    )
    run = store.create_run(task.id, worker_id="worker-1", python_env_used="test-env")
    store.update_run(
        run.id,
        {
            "worktree_path": str(worktree_path),
            "branch_name": "task/demo",
        },
    )
    patched = store.update_task(task.id, {"status": "REVIEW"})
    assert patched is not None
    return task.id, run.id


def test_done_triggers_cleanup_and_returns_done(tmp_path: Path, monkeypatch):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    client = _build_client(store, runner)

    worktree_path = tmp_path / "worktrees" / "demo" / "task-1"
    worktree_path.mkdir(parents=True, exist_ok=True)
    task_id, run_id = _create_review_exec_task(store, "done-cleanup", worktree_path)

    cleanup_calls: list[tuple[str, str]] = []

    def _cleanup(repo, path: Path, branch: str) -> None:
        cleanup_calls.append((str(path), branch))

    monkeypatch.setattr("app.core.runner.git_ops.cleanup_worktree", _cleanup)

    resp = client.post(f"/api/tasks/{task_id}/done")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "DONE"

    run_after = store.get_run(run_id)
    assert run_after is not None
    assert run_after.worktree_path == ""
    assert cleanup_calls == [(str(worktree_path), "task/demo")]

    events, _ = store.read_events(task_id, cursor=0)
    cleanup_events = [event for event in events if event.get("type") == "worktree_cleanup"]
    assert cleanup_events
    assert cleanup_events[-1]["trigger_status"] == "DONE"
    assert cleanup_events[-1]["result"] == "success"


def test_done_cleanup_failure_still_returns_done(tmp_path: Path, monkeypatch):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    client = _build_client(store, runner)

    worktree_path = tmp_path / "worktrees" / "demo" / "task-2"
    worktree_path.mkdir(parents=True, exist_ok=True)
    task_id, run_id = _create_review_exec_task(store, "done-cleanup-fail", worktree_path)

    def _cleanup(repo, path: Path, branch: str) -> None:
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr("app.core.runner.git_ops.cleanup_worktree", _cleanup)

    resp = client.post(f"/api/tasks/{task_id}/done")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "DONE"

    run_after = store.get_run(run_id)
    assert run_after is not None
    assert run_after.worktree_path == str(worktree_path)

    events, _ = store.read_events(task_id, cursor=0)
    cleanup_events = [event for event in events if event.get("type") == "worktree_cleanup"]
    assert cleanup_events
    assert cleanup_events[-1]["trigger_status"] == "DONE"
    assert cleanup_events[-1]["result"] == "failed"
    assert "cleanup boom" in cleanup_events[-1]["error_message"]
