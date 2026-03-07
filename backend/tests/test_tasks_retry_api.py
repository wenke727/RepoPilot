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


def test_retry_failed_task_moves_back_to_todo(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    client = _build_client(store, runner)

    task_id = _create_exec_task(store, "retry-failed")
    patched = store.update_task(task_id, {"status": "FAILED", "error_code": "X", "error_message": "Y"})
    assert patched is not None

    resp = client.post(f"/api/tasks/{task_id}/retry", json={})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "TODO"
    assert payload["error_code"] == ""
    assert payload["error_message"] == ""


def test_retry_failed_task_appends_followup_to_prompt(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    client = _build_client(store, runner)

    task_id = _create_exec_task(store, "retry-followup")
    patched = store.update_task(task_id, {"status": "FAILED"})
    assert patched is not None

    resp = client.post(f"/api/tasks/{task_id}/retry", json={"followup": "请直接改 README 并提交"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "TODO"
    assert payload["prompt"].endswith("[用户追问]\n请直接改 README 并提交")


def test_retry_failed_task_blank_followup_keeps_prompt(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    client = _build_client(store, runner)

    task_id = _create_exec_task(store, "retry-blank-followup")
    patched = store.update_task(task_id, {"status": "FAILED"})
    assert patched is not None
    original_prompt = patched.prompt

    resp = client.post(f"/api/tasks/{task_id}/retry", json={"followup": "   "})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "TODO"
    assert payload["prompt"] == original_prompt


def test_retry_failed_task_followup_too_long_rejected(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    client = _build_client(store, runner)

    task_id = _create_exec_task(store, "retry-long-followup")
    patched = store.update_task(task_id, {"status": "FAILED"})
    assert patched is not None

    too_long = "x" * 4001
    resp = client.post(f"/api/tasks/{task_id}/retry", json={"followup": too_long})
    assert resp.status_code == 400
    assert "at most 4000 chars" in resp.json()["detail"]


def test_retry_review_task_rejected(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    client = _build_client(store, runner)

    task_id = _create_exec_task(store, "retry-review")
    patched = store.update_task(task_id, {"status": "REVIEW"})
    assert patched is not None

    resp = client.post(f"/api/tasks/{task_id}/retry", json={})
    assert resp.status_code == 400
    assert "task status must be FAILED/CANCELLED" in resp.json()["detail"]
