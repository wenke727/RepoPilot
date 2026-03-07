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


def _create_exec_task(store: JsonStore, title: str) -> str:
    task = store.create_task(
        {
            "repo_id": "demo",
            "title": title,
            "prompt": f"exec-{title}",
            "mode": TaskMode.EXEC.value,
            "permission_mode": "BYPASS",
            "priority": 0,
        }
    )
    return task.id


def test_delete_task_removes_related_state(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    client = _build_client(store, runner)

    task_id = _create_exec_task(store, "delete-target")
    keep_task_id = _create_exec_task(store, "delete-keep")

    run = store.create_run(task_id, worker_id="worker-1", python_env_used="test-env")
    store.append_event(task_id, {"type": "assistant_text", "text": "hello"})
    store.create_notification(
        {
            "task_id": task_id,
            "type": "INFO",
            "title": "delete-target",
            "body": "to be deleted",
        }
    )

    keep_run = store.create_run(keep_task_id, worker_id="worker-2", python_env_used="test-env")
    store.append_event(keep_task_id, {"type": "assistant_text", "text": "keep"})
    store.create_notification(
        {
            "task_id": keep_task_id,
            "type": "INFO",
            "title": "delete-keep",
            "body": "should remain",
        }
    )

    artifacts_root = tmp_path / "state" / "artifacts" / task_id / run.id
    artifacts_root.mkdir(parents=True, exist_ok=True)
    (artifacts_root / "snapshot.txt").write_text("artifact", encoding="utf-8")

    resp = client.delete(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["task_id"] == task_id

    assert store.get_task(task_id) is None
    assert store.get_task(keep_task_id) is not None

    assert store.get_run(run.id) is None
    assert store.get_run(keep_run.id) is not None

    notifications = store.list_notifications()
    assert all(item.task_id != task_id for item in notifications)
    assert any(item.task_id == keep_task_id for item in notifications)

    assert not (store.logs_dir / f"{task_id}.ndjson").exists()
    assert (store.logs_dir / f"{keep_task_id}.ndjson").exists()
    assert not (tmp_path / "state" / "artifacts" / task_id).exists()

    after_resp = client.get(f"/api/tasks/{task_id}")
    assert after_resp.status_code == 404


def test_delete_running_task_rejected(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    client = _build_client(store, runner)

    task_id = _create_exec_task(store, "delete-running")
    patched = store.update_task(task_id, {"status": "RUNNING"})
    assert patched is not None

    resp = client.delete(f"/api/tasks/{task_id}")
    assert resp.status_code == 409
    assert "RUNNING/PLAN_RUNNING" in resp.json()["detail"]
    assert store.get_task(task_id) is not None


def test_delete_review_exec_task_triggers_worktree_cleanup(tmp_path: Path, monkeypatch):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    client = _build_client(store, runner)

    task_id = _create_exec_task(store, "delete-review-cleanup")
    run = store.create_run(task_id, worker_id="worker-1", python_env_used="test-env")

    worktree_path = tmp_path / "worktrees" / "demo" / "delete-review-cleanup"
    worktree_path.mkdir(parents=True, exist_ok=True)
    store.update_run(
        run.id,
        {
            "worktree_path": str(worktree_path),
            "branch_name": "task/delete-review-cleanup",
        },
    )
    patched = store.update_task(task_id, {"status": "REVIEW"})
    assert patched is not None

    cleanup_calls: list[tuple[str, str]] = []

    def _cleanup(repo, path: Path, branch: str) -> None:
        cleanup_calls.append((str(path), branch))

    monkeypatch.setattr("app.core.runner.git_ops.cleanup_worktree", _cleanup)

    resp = client.delete(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    assert cleanup_calls == [(str(worktree_path), "task/delete-review-cleanup")]
    assert store.get_task(task_id) is None

