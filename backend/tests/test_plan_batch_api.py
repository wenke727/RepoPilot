from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import tasks
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
                "test_command": "npm test",
                "github_repo": "owner/demo",
                "shared_symlink_paths": [],
                "forbidden_symlink_paths": ["PROGRESS.md"],
                "enabled": True,
            }
        )
        store._write_json_atomic(store.repos_file, rows)


def _create_plan_review_task(store: JsonStore, title: str) -> str:
    task = store.create_task(
        {
            "repo_id": "demo",
            "title": title,
            "prompt": f"prompt-{title}",
            "mode": TaskMode.PLAN.value,
            "permission_mode": "BYPASS",
            "priority": 0,
        }
    )
    patched = store.update_task(
        task.id,
        {
            "status": "PLAN_REVIEW",
            "plan_result": {
                "summary": "summary",
                "questions": [
                    {
                        "id": "q1",
                        "title": "Q1",
                        "question": "what",
                        "options": [{"key": "a", "label": "A"}],
                        "recommended_option_key": "a",
                    }
                ],
                "recommended_prompt": "go",
                "raw_text": "{}",
                "valid_json": True,
            },
        },
    )
    assert patched is not None
    return task.id


def _build_client(store: JsonStore) -> TestClient:
    app = FastAPI()
    app.state.store = store
    app.state.scheduler = _DummyScheduler()
    app.include_router(tasks.router)
    return TestClient(app)


def test_batch_confirm_api_contract_partial_success(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    ok_id = _create_plan_review_task(store, "ok")

    bad_task = store.create_task(
        {
            "repo_id": "demo",
            "title": "todo",
            "prompt": "todo",
            "mode": TaskMode.PLAN.value,
            "permission_mode": "BYPASS",
            "priority": 0,
        }
    )

    client = _build_client(store)
    resp = client.post(
        "/api/tasks/plan/batch/confirm",
        json={"task_ids": [ok_id, bad_task.id]},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["counts"] == {"requested": 2, "updated": 1, "failed": 1}
    assert len(payload["updated"]) == 1
    assert payload["failed"][0]["task_id"] == bad_task.id
    assert payload["failed"][0]["error_code"] == "INVALID_STATUS"

    events, _ = store.read_events(ok_id, cursor=0)
    assert any(event.get("type") == "plan_batch_confirm" for event in events)


def test_batch_revise_api_contract_success(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    task_id = _create_plan_review_task(store, "revise")
    client = _build_client(store)

    resp = client.post(
        "/api/tasks/plan/batch/revise",
        json={"task_ids": [task_id], "feedback": "请先补充验收标准"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["counts"] == {"requested": 1, "updated": 1, "failed": 0}
    assert payload["failed"] == []

    task = store.get_task(task_id)
    assert task is not None
    assert task.status.value == "TODO"
    assert task.mode.value == "PLAN"
    assert "[用户反馈]\n请先补充验收标准" in task.prompt

    events, _ = store.read_events(task_id, cursor=0)
    assert any(event.get("type") == "plan_batch_revise" for event in events)


def test_batch_plan_api_validation_returns_400(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    client = _build_client(store)

    empty_ids = client.post("/api/tasks/plan/batch/confirm", json={"task_ids": []})
    assert empty_ids.status_code == 400

    too_many = client.post(
        "/api/tasks/plan/batch/confirm",
        json={"task_ids": [f"task-{idx}" for idx in range(101)]},
    )
    assert too_many.status_code == 400

    blank_feedback = client.post(
        "/api/tasks/plan/batch/revise",
        json={"task_ids": ["x"], "feedback": "   "},
    )
    assert blank_feedback.status_code == 400
