from pathlib import Path
from datetime import datetime
import re
import subprocess

from app.models import DEFAULT_TEST_COMMAND, TaskMode
from app.store.json_store import JsonStore


def create_store(tmp_path: Path) -> JsonStore:
    state_dir = tmp_path / 'state'
    repos_dir = tmp_path / 'repos'
    store = JsonStore(state_dir=state_dir, repos_dir=repos_dir)
    return store


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def test_task_create_and_claim(tmp_path: Path):
    store = create_store(tmp_path)

    repo_root = tmp_path / 'repos' / 'demo'
    repo_root.mkdir(parents=True)
    (repo_root / '.git').mkdir()

    # inject repo directly
    store.patch_repo('missing', {})
    with store._lock('repos'):
        rows = store._read_json(store.repos_file)
        rows.append(
            {
                'id': 'demo',
                'name': 'demo',
                'root_path': str(repo_root),
                'main_branch': 'main',
                'test_command': 'npm test',
                'github_repo': 'owner/demo',
                'shared_symlink_paths': [],
                'forbidden_symlink_paths': ['PROGRESS.md'],
                'enabled': True,
            }
        )
        store._write_json_atomic(store.repos_file, rows)

    task = store.create_task(
        {
            'repo_id': 'demo',
            'title': 'T1',
            'prompt': 'P1',
            'mode': TaskMode.EXEC.value,
            'permission_mode': 'BYPASS',
            'priority': 0,
        }
    )

    claimed = store.claim_next_task('worker-1')
    assert claimed is not None
    assert claimed.id == task.id
    assert claimed.status.value == 'RUNNING'


def test_board_plan_review_maps_to_review(tmp_path: Path):
    store = create_store(tmp_path)
    repo_root = tmp_path / 'repos' / 'demo'
    repo_root.mkdir(parents=True)
    (repo_root / '.git').mkdir()

    with store._lock('repos'):
        rows = store._read_json(store.repos_file)
        rows.append(
            {
                'id': 'demo',
                'name': 'demo',
                'root_path': str(repo_root),
                'main_branch': 'main',
                'test_command': 'npm test',
                'github_repo': 'owner/demo',
                'shared_symlink_paths': [],
                'forbidden_symlink_paths': ['PROGRESS.md'],
                'enabled': True,
            }
        )
        store._write_json_atomic(store.repos_file, rows)

    task = store.create_task(
        {
            'repo_id': 'demo',
            'title': 'Plan',
            'prompt': 'P',
            'mode': TaskMode.PLAN.value,
            'permission_mode': 'BYPASS',
            'priority': 0,
        }
    )
    store.update_task(task.id, {'status': 'PLAN_REVIEW'})

    columns, counts = store.board()
    assert len(columns['REVIEW']) == 1
    assert counts['REVIEW'] == 1


def test_new_ids_use_daily_sequence_format(tmp_path: Path):
    store = create_store(tmp_path)
    repo_root = tmp_path / 'repos' / 'demo'
    repo_root.mkdir(parents=True)
    (repo_root / '.git').mkdir()

    with store._lock('repos'):
        rows = store._read_json(store.repos_file)
        rows.append(
            {
                'id': 'demo',
                'name': 'demo',
                'root_path': str(repo_root),
                'main_branch': 'main',
                'test_command': 'npm test',
                'github_repo': 'owner/demo',
                'shared_symlink_paths': [],
                'forbidden_symlink_paths': ['PROGRESS.md'],
                'enabled': True,
            }
        )
        store._write_json_atomic(store.repos_file, rows)

    task = store.create_task(
        {
            'repo_id': 'demo',
            'title': 'T1',
            'prompt': 'P1',
            'mode': TaskMode.EXEC.value,
            'permission_mode': 'BYPASS',
            'priority': 0,
        }
    )
    run = store.create_run(task.id, worker_id='worker-1', python_env_used='dl2')
    notif = store.create_notification(
        {
            'task_id': task.id,
            'type': 'INFO',
            'title': 'hello',
            'body': 'world',
        }
    )

    pattern = re.compile(r'^\d{6}-\d{3}$')
    assert pattern.match(task.id)
    assert pattern.match(run.id)
    assert pattern.match(notif.id)


def test_task_id_sequence_increments_within_day(tmp_path: Path, monkeypatch):
    store = create_store(tmp_path)
    repo_root = tmp_path / 'repos' / 'demo'
    repo_root.mkdir(parents=True)
    (repo_root / '.git').mkdir()

    with store._lock('repos'):
        rows = store._read_json(store.repos_file)
        rows.append(
            {
                'id': 'demo',
                'name': 'demo',
                'root_path': str(repo_root),
                'main_branch': 'main',
                'test_command': 'npm test',
                'github_repo': 'owner/demo',
                'shared_symlink_paths': [],
                'forbidden_symlink_paths': ['PROGRESS.md'],
                'enabled': True,
            }
        )
        store._write_json_atomic(store.repos_file, rows)

    first_ts = datetime(2026, 2, 10, 23, 11, 11)

    with store._lock('tasks'):
        rows = store._read_json(store.tasks_file)
        rows.append({'id': first_ts.strftime('%y%m%d-001')})
        store._write_json_atomic(store.tasks_file, rows)

    class FakeDateTime:
        @classmethod
        def now(cls):
            return first_ts

    monkeypatch.setattr('app.store.json_store.datetime', FakeDateTime)

    task = store.create_task(
        {
            'repo_id': 'demo',
            'title': 'collision',
            'prompt': 'prompt',
            'mode': TaskMode.EXEC.value,
            'permission_mode': 'BYPASS',
            'priority': 0,
        }
    )
    assert task.id == first_ts.strftime('%y%m%d-002')


def test_task_id_overflow_falls_back_to_timestamp(tmp_path: Path, monkeypatch):
    store = create_store(tmp_path)
    repo_root = tmp_path / 'repos' / 'demo'
    repo_root.mkdir(parents=True)
    (repo_root / '.git').mkdir()

    with store._lock('repos'):
        rows = store._read_json(store.repos_file)
        rows.append(
            {
                'id': 'demo',
                'name': 'demo',
                'root_path': str(repo_root),
                'main_branch': 'main',
                'test_command': 'npm test',
                'github_repo': 'owner/demo',
                'shared_symlink_paths': [],
                'forbidden_symlink_paths': ['PROGRESS.md'],
                'enabled': True,
            }
        )
        store._write_json_atomic(store.repos_file, rows)

    first_ts = datetime(2026, 2, 10, 23, 11, 11)

    with store._lock('tasks'):
        rows = store._read_json(store.tasks_file)
        rows.extend({'id': f"{first_ts.strftime('%y%m%d')}-{idx:03d}"} for idx in range(1, 1000))
        store._write_json_atomic(store.tasks_file, rows)

    class FakeDateTime:
        @classmethod
        def now(cls):
            return first_ts

    monkeypatch.setattr('app.store.json_store.datetime', FakeDateTime)

    task = store.create_task(
        {
            'repo_id': 'demo',
            'title': 'overflow',
            'prompt': 'prompt',
            'mode': TaskMode.EXEC.value,
            'permission_mode': 'BYPASS',
            'priority': 0,
        }
    )
    assert task.id == first_ts.strftime('%y%m%d_%H%M%S')


def test_legacy_id_still_readable(tmp_path: Path):
    store = create_store(tmp_path)
    legacy_id = 'task-legacy-1234'
    with store._lock('tasks'):
        rows = store._read_json(store.tasks_file)
        rows.append(
            {
                'id': legacy_id,
                'repo_id': 'demo',
                'title': 'legacy',
                'prompt': 'legacy prompt',
                'mode': 'EXEC',
                'status': 'TODO',
                'permission_mode': 'BYPASS',
                'priority': 0,
                'created_at': '2026-02-21T00:00:00+00:00',
                'updated_at': '2026-02-21T00:00:00+00:00',
                'current_run_id': None,
                'plan_result': None,
                'plan_answers': {},
                'pr_url': '',
                'error_code': '',
                'error_message': '',
                'cancel_requested': False,
            }
        )
        store._write_json_atomic(store.tasks_file, rows)

    task = store.get_task(legacy_id)
    assert task is not None
    assert task.id == legacy_id


def test_rescan_sets_safe_default_test_command(tmp_path: Path):
    store = create_store(tmp_path)
    repo_root = tmp_path / "repos" / "demo"
    repo_root.mkdir(parents=True)
    _run(["git", "init"], cwd=repo_root)
    _run(["git", "remote", "add", "origin", "https://github.com/owner/demo.git"], cwd=repo_root)

    repos = store.rescan_repos()
    assert len(repos) == 1
    assert repos[0].test_command == DEFAULT_TEST_COMMAND


def test_rescan_migrates_plain_npm_test_to_safe_default(tmp_path: Path):
    store = create_store(tmp_path)
    repo_root = tmp_path / "repos" / "demo"
    repo_root.mkdir(parents=True)
    _run(["git", "init"], cwd=repo_root)
    _run(["git", "remote", "add", "origin", "https://github.com/owner/demo.git"], cwd=repo_root)

    with store._lock("repos"):
        rows = [
            {
                "id": "demo",
                "name": "demo",
                "root_path": str(repo_root.resolve()),
                "main_branch": "main",
                "test_command": "npm test",
                "github_repo": "owner/demo",
                "shared_symlink_paths": [],
                "forbidden_symlink_paths": ["PROGRESS.md"],
                "enabled": True,
            }
        ]
        store._write_json_atomic(store.repos_file, rows)

    repos = store.rescan_repos()
    assert len(repos) == 1
    assert repos[0].test_command == DEFAULT_TEST_COMMAND


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
    plan_result = {
        "summary": "summary",
        "questions": [
            {
                "id": "q1",
                "title": "Q1",
                "question": "?",
                "options": [{"key": "a", "label": "A"}],
                "recommended_option_key": "a",
            },
            {
                "id": "q2",
                "title": "Q2",
                "question": "?",
                "options": [{"key": "b", "label": "B"}],
                "recommended_option_key": None,
            },
        ],
        "recommended_prompt": "go",
        "raw_text": "{}",
        "valid_json": True,
    }
    patched = store.update_task(task.id, {"status": "PLAN_REVIEW", "plan_result": plan_result})
    assert patched is not None
    return task.id


def test_batch_confirm_plan_tasks_success_uses_recommended_answers(tmp_path: Path):
    store = create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    task_id = _create_plan_review_task(store, "t1")

    updated, failed = store.batch_confirm_plan_tasks([task_id, task_id])
    assert len(updated) == 1
    assert failed == []

    task = store.get_task(task_id)
    assert task is not None
    assert task.status.value == "READY"
    assert task.mode.value == "EXEC"
    assert task.plan_answers == {"q1": "a"}


def test_batch_confirm_plan_tasks_partial_failure(tmp_path: Path):
    store = create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    ok_id = _create_plan_review_task(store, "ok")

    todo_task = store.create_task(
        {
            "repo_id": "demo",
            "title": "todo",
            "prompt": "todo",
            "mode": TaskMode.PLAN.value,
            "permission_mode": "BYPASS",
            "priority": 0,
        }
    )

    updated, failed = store.batch_confirm_plan_tasks([ok_id, todo_task.id, "missing-task"])
    assert len(updated) == 1
    assert {item["error_code"] for item in failed} == {"INVALID_STATUS", "TASK_NOT_FOUND"}


def test_batch_revise_plan_tasks_moves_tasks_back_to_todo(tmp_path: Path):
    store = create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    task_ids = [
        _create_plan_review_task(store, "r1"),
        _create_plan_review_task(store, "r2"),
    ]

    updated, failed = store.batch_revise_plan_tasks(task_ids, "请补充验收标准")
    assert len(updated) == 2
    assert failed == []

    for task_id in task_ids:
        task = store.get_task(task_id)
        assert task is not None
        assert task.status.value == "TODO"
        assert task.mode.value == "PLAN"
        assert "[用户反馈]\n请补充验收标准" in task.prompt
