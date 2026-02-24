from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fcntl import LOCK_EX, LOCK_UN, flock

from app.core.plan_parser import build_exec_prompt
from app.models import (
    Notification,
    DEFAULT_TEST_COMMAND,
    RepoConfig,
    Task,
    TaskMode,
    TaskRun,
    TaskStatus,
    utcnow_iso,
)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return cleaned.lower() or "repo"


class JsonStore:
    def __init__(self, state_dir: Path, repos_dir: Path) -> None:
        self.state_dir = state_dir
        self.repos_dir = repos_dir
        self.logs_dir = state_dir / "logs"
        self.locks_dir = state_dir / "locks"
        self.repos_file = state_dir / "repos.json"
        self.tasks_file = state_dir / "tasks.json"
        self.runs_file = state_dir / "runs.json"
        self.notifications_file = state_dir / "notifications.json"
        self._ensure_dirs_and_files()

    def _ensure_dirs_and_files(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        for file_path in [
            self.repos_file,
            self.tasks_file,
            self.runs_file,
            self.notifications_file,
        ]:
            if not file_path.exists():
                file_path.write_text("[]\n", encoding="utf-8")

    @contextmanager
    def _lock(self, name: str):
        path = self.locks_dir / f"{name}.lock"
        path.touch(exist_ok=True)
        with path.open("r+") as fh:
            flock(fh.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(fh.fileno(), LOCK_UN)

    def _read_json(self, file_path: Path) -> list[dict[str, Any]]:
        if not file_path.exists():
            return []
        data = file_path.read_text(encoding="utf-8").strip()
        if not data:
            return []
        try:
            loaded = json.loads(data)
        except json.JSONDecodeError:
            return []
        if isinstance(loaded, list):
            return loaded
        return []

    def _write_json_atomic(self, file_path: Path, payload: list[dict[str, Any]]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(file_path.parent), delete=False) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, file_path)

    def _next_id(self, existing_ids: set[str], max_wait_seconds: float = 3.0) -> str:
        deadline = time.monotonic() + max_wait_seconds
        while True:
            candidate = datetime.now().strftime("%y%m%d_%H%M%S")
            if candidate not in existing_ids:
                return candidate

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Failed to allocate unique ID in time window")

            # Keep pure timestamp format by waiting for the next second boundary.
            now_epoch = time.time()
            wait_to_next_second = 1.0 - (now_epoch - int(now_epoch))
            sleep_seconds = max(0.01, min(wait_to_next_second, remaining))
            time.sleep(sleep_seconds)

    def _detect_origin_url(self, repo_path: Path) -> str:
        try:
            out = subprocess.check_output(
                ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            return out
        except Exception:
            return ""

    def _origin_to_github_repo(self, origin: str) -> str:
        if "github.com" not in origin:
            return ""
        if origin.startswith("git@"):
            # git@github.com:owner/repo.git
            name = origin.split(":", 1)[-1]
        else:
            # https://github.com/owner/repo.git
            name = origin.split("github.com/", 1)[-1]
        return name.removesuffix(".git").strip("/")

    def _detect_main_branch(self, repo_path: Path) -> str:
        try:
            out = subprocess.check_output(
                ["git", "-C", str(repo_path), "symbolic-ref", "refs/remotes/origin/HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            return out.rsplit("/", 1)[-1]
        except Exception:
            for branch in ["main", "master"]:
                rc = subprocess.call(
                    ["git", "-C", str(repo_path), "show-ref", "--verify", f"refs/heads/{branch}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if rc == 0:
                    return branch
            return "main"

    def _remote_branch_exists(self, repo_path: Path, branch: str) -> bool:
        if not branch:
            return False
        rc = subprocess.call(
            ["git", "-C", str(repo_path), "show-ref", "--verify", f"refs/remotes/origin/{branch}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return rc == 0

    def list_repos(self) -> list[RepoConfig]:
        with self._lock("repos"):
            rows = self._read_json(self.repos_file)
        return [RepoConfig.model_validate(row) for row in rows]

    def get_repo(self, repo_id: str) -> RepoConfig | None:
        repos = self.list_repos()
        for repo in repos:
            if repo.id == repo_id:
                return repo
        return None

    def patch_repo(self, repo_id: str, patch: dict[str, Any]) -> RepoConfig | None:
        with self._lock("repos"):
            rows = self._read_json(self.repos_file)
            updated: dict[str, Any] | None = None
            for row in rows:
                if row.get("id") == repo_id:
                    for key, value in patch.items():
                        if value is not None:
                            row[key] = value
                    updated = row
                    break
            if updated is None:
                return None
            self._write_json_atomic(self.repos_file, rows)
        return RepoConfig.model_validate(updated)

    def rescan_repos(self) -> list[RepoConfig]:
        with self._lock("repos"):
            existing_rows = self._read_json(self.repos_file)
            by_root = {row["root_path"]: row for row in existing_rows if "root_path" in row}

            for child in sorted(self.repos_dir.iterdir()) if self.repos_dir.exists() else []:
                if not child.is_dir():
                    continue
                if not (child / ".git").exists():
                    continue
                origin = self._detect_origin_url(child)
                if "github.com" not in origin:
                    continue

                root_path = str(child.resolve())
                github_repo = self._origin_to_github_repo(origin)
                repo_name = child.name
                main_branch = self._detect_main_branch(child)

                if root_path in by_root:
                    row = by_root[root_path]
                    row["name"] = row.get("name") or repo_name
                    row["github_repo"] = row.get("github_repo") or github_repo
                    current_main = str(row.get("main_branch", "")).strip()
                    if not current_main or not self._remote_branch_exists(child, current_main):
                        row["main_branch"] = main_branch
                    test_cmd = str(row.get("test_command", "")).strip()
                    if not test_cmd or test_cmd == "npm test":
                        row["test_command"] = DEFAULT_TEST_COMMAND
                    row.setdefault("enabled", True)
                    row.setdefault(
                        "shared_symlink_paths",
                        ["data/dev-tasks.json", "data/dev-task.lock", "data/api-key.json"],
                    )
                    row.setdefault("forbidden_symlink_paths", ["PROGRESS.md"])
                else:
                    new_row = RepoConfig(
                        id=_slug(repo_name),
                        name=repo_name,
                        root_path=root_path,
                        main_branch=main_branch,
                        test_command=DEFAULT_TEST_COMMAND,
                        github_repo=github_repo,
                        shared_symlink_paths=[
                            "data/dev-tasks.json",
                            "data/dev-task.lock",
                            "data/api-key.json",
                        ],
                        forbidden_symlink_paths=["PROGRESS.md"],
                        enabled=True,
                    ).model_dump()

                    base_id = new_row["id"]
                    suffix = 1
                    existing_ids = {row.get("id") for row in by_root.values()}
                    while new_row["id"] in existing_ids:
                        suffix += 1
                        new_row["id"] = f"{base_id}-{suffix}"
                    by_root[root_path] = new_row

            merged_rows = sorted(by_root.values(), key=lambda row: row.get("name", ""))
            self._write_json_atomic(self.repos_file, merged_rows)

        return [RepoConfig.model_validate(row) for row in merged_rows]

    def create_task(self, data: dict[str, Any]) -> Task:
        with self._lock("tasks"):
            rows = self._read_json(self.tasks_file)
            existing_ids = {str(row.get("id", "")) for row in rows}
            task_id = self._next_id(existing_ids)
            now = utcnow_iso()
            task = Task(
                id=task_id,
                repo_id=data["repo_id"],
                title=data["title"],
                prompt=data["prompt"],
                mode=TaskMode(data.get("mode", TaskMode.EXEC)),
                status=TaskStatus.TODO,
                permission_mode=data.get("permission_mode", "BYPASS"),
                priority=int(data.get("priority", 0)),
                created_at=now,
                updated_at=now,
            )
            rows.append(task.model_dump())
            self._write_json_atomic(self.tasks_file, rows)
        return task

    def list_tasks(
        self,
        repo_id: str | None = None,
        status: TaskStatus | None = None,
        keyword: str | None = None,
    ) -> list[Task]:
        with self._lock("tasks"):
            rows = self._read_json(self.tasks_file)

        tasks = [Task.model_validate(row) for row in rows]
        if repo_id:
            tasks = [task for task in tasks if task.repo_id == repo_id]
        if status:
            tasks = [task for task in tasks if task.status == status]
        if keyword:
            low = keyword.lower()
            tasks = [
                task
                for task in tasks
                if low in task.title.lower() or low in task.prompt.lower() or low in task.id.lower()
            ]
        tasks.sort(key=lambda t: (t.priority * -1, t.created_at), reverse=False)
        return tasks

    def get_task(self, task_id: str) -> Task | None:
        with self._lock("tasks"):
            rows = self._read_json(self.tasks_file)
        for row in rows:
            if row.get("id") == task_id:
                return Task.model_validate(row)
        return None

    def update_task(self, task_id: str, patch: dict[str, Any]) -> Task | None:
        with self._lock("tasks"):
            rows = self._read_json(self.tasks_file)
            target: dict[str, Any] | None = None
            for row in rows:
                if row.get("id") == task_id:
                    row.update({k: v for k, v in patch.items() if v is not None})
                    row["updated_at"] = utcnow_iso()
                    target = row
                    break
            if target is None:
                return None
            self._write_json_atomic(self.tasks_file, rows)
        return Task.model_validate(target)

    def claim_next_task(self, worker_id: str) -> Task | None:
        with self._lock("tasks"):
            rows = self._read_json(self.tasks_file)
            now = utcnow_iso()

            candidates: list[dict[str, Any]] = []
            for row in rows:
                status = row.get("status")
                mode = row.get("mode")
                if row.get("cancel_requested"):
                    continue
                if mode == TaskMode.PLAN.value and status == TaskStatus.TODO.value:
                    candidates.append(row)
                elif mode == TaskMode.EXEC.value and status in {TaskStatus.TODO.value, TaskStatus.READY.value}:
                    candidates.append(row)

            if not candidates:
                return None

            candidates.sort(key=lambda r: (-(int(r.get("priority", 0))), r.get("created_at", "")))
            picked = candidates[0]
            if picked.get("mode") == TaskMode.PLAN.value:
                picked["status"] = TaskStatus.PLAN_RUNNING.value
            else:
                picked["status"] = TaskStatus.RUNNING.value
            picked["updated_at"] = now
            picked["worker_id"] = worker_id

            self._write_json_atomic(self.tasks_file, rows)

        return Task.model_validate(picked)

    def cancel_task(self, task_id: str) -> Task | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.status in {TaskStatus.TODO, TaskStatus.READY, TaskStatus.PLAN_REVIEW}:
            return self.update_task(task_id, {"status": TaskStatus.CANCELLED.value, "cancel_requested": True})
        return self.update_task(task_id, {"cancel_requested": True})

    def reset_task_for_retry(self, task_id: str, reset_mode: TaskMode | None = None) -> Task | None:
        task = self.get_task(task_id)
        if task is None:
            return None

        mode = reset_mode.value if reset_mode else task.mode.value
        return self.update_task(
            task_id,
            {
                "status": TaskStatus.TODO.value,
                "mode": mode,
                "error_code": "",
                "error_message": "",
                "cancel_requested": False,
                "current_run_id": None,
            },
        )

    def normalize_task_ids(self, task_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for item in task_ids:
            task_id = str(item).strip()
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            normalized.append(task_id)
        return normalized

    def _recommended_answers(self, task: Task) -> dict[str, str]:
        answers: dict[str, str] = {}
        plan = task.plan_result
        if not plan:
            return answers

        for question in plan.questions:
            option_key = question.recommended_option_key
            if isinstance(option_key, str) and option_key.strip():
                answers[question.id] = option_key.strip()
        return answers

    def batch_confirm_plan_tasks(self, task_ids: list[str]) -> tuple[list[Task], list[dict[str, str]]]:
        normalized = self.normalize_task_ids(task_ids)
        updated: list[Task] = []
        failed: list[dict[str, str]] = []

        for task_id in normalized:
            task = self.get_task(task_id)
            if task is None:
                failed.append(
                    {
                        "task_id": task_id,
                        "error_code": "TASK_NOT_FOUND",
                        "error_message": "task not found",
                    }
                )
                continue

            if task.status != TaskStatus.PLAN_REVIEW:
                failed.append(
                    {
                        "task_id": task_id,
                        "error_code": "INVALID_STATUS",
                        "error_message": f"task status must be PLAN_REVIEW, got {task.status.value}",
                    }
                )
                continue

            if task.plan_result is None:
                failed.append(
                    {
                        "task_id": task_id,
                        "error_code": "PLAN_RESULT_MISSING",
                        "error_message": "plan_result is required for PLAN_REVIEW task",
                    }
                )
                continue

            answers = self._recommended_answers(task)
            final_prompt = build_exec_prompt(task.prompt, task.plan_result, answers)
            patched = self.update_task(
                task.id,
                {
                    "mode": TaskMode.EXEC.value,
                    "status": TaskStatus.READY.value,
                    "prompt": final_prompt,
                    "plan_answers": answers,
                    "error_code": "",
                    "error_message": "",
                    "cancel_requested": False,
                },
            )
            if patched is None:
                failed.append(
                    {
                        "task_id": task_id,
                        "error_code": "UPDATE_FAILED",
                        "error_message": "failed to update task",
                    }
                )
                continue
            updated.append(patched)

        return updated, failed

    def batch_revise_plan_tasks(self, task_ids: list[str], feedback: str) -> tuple[list[Task], list[dict[str, str]]]:
        normalized = self.normalize_task_ids(task_ids)
        feedback_text = feedback.strip()
        updated: list[Task] = []
        failed: list[dict[str, str]] = []

        for task_id in normalized:
            task = self.get_task(task_id)
            if task is None:
                failed.append(
                    {
                        "task_id": task_id,
                        "error_code": "TASK_NOT_FOUND",
                        "error_message": "task not found",
                    }
                )
                continue

            if task.status != TaskStatus.PLAN_REVIEW:
                failed.append(
                    {
                        "task_id": task_id,
                        "error_code": "INVALID_STATUS",
                        "error_message": f"task status must be PLAN_REVIEW, got {task.status.value}",
                    }
                )
                continue

            if task.plan_result is None:
                failed.append(
                    {
                        "task_id": task_id,
                        "error_code": "PLAN_RESULT_MISSING",
                        "error_message": "plan_result is required for PLAN_REVIEW task",
                    }
                )
                continue

            revised_prompt = f"{task.prompt}\n\n[用户反馈]\n{feedback_text}"
            patched = self.update_task(
                task.id,
                {
                    "mode": TaskMode.PLAN.value,
                    "status": TaskStatus.TODO.value,
                    "prompt": revised_prompt,
                    "error_code": "",
                    "error_message": "",
                    "cancel_requested": False,
                },
            )
            if patched is None:
                failed.append(
                    {
                        "task_id": task_id,
                        "error_code": "UPDATE_FAILED",
                        "error_message": "failed to update task",
                    }
                )
                continue
            updated.append(patched)

        return updated, failed

    def create_run(self, task_id: str, worker_id: str, python_env_used: str) -> TaskRun:
        with self._lock("runs"):
            runs = self._read_json(self.runs_file)
            attempt = len([r for r in runs if r.get("task_id") == task_id]) + 1
            existing_ids = {str(row.get("id", "")) for row in runs}
            run = TaskRun(
                id=self._next_id(existing_ids),
                task_id=task_id,
                worker_id=worker_id,
                attempt=attempt,
                started_at=utcnow_iso(),
                python_env_used=python_env_used,
            )
            runs.append(run.model_dump())
            self._write_json_atomic(self.runs_file, runs)

        self.update_task(task_id, {"current_run_id": run.id})
        return run

    def update_run(self, run_id: str, patch: dict[str, Any]) -> TaskRun | None:
        with self._lock("runs"):
            runs = self._read_json(self.runs_file)
            target = None
            for row in runs:
                if row.get("id") == run_id:
                    row.update({k: v for k, v in patch.items() if v is not None})
                    target = row
                    break
            if target is None:
                return None
            self._write_json_atomic(self.runs_file, runs)
        return TaskRun.model_validate(target)

    def list_runs(self, task_id: str | None = None) -> list[TaskRun]:
        with self._lock("runs"):
            rows = self._read_json(self.runs_file)
        runs = [TaskRun.model_validate(row) for row in rows]
        if task_id:
            runs = [run for run in runs if run.task_id == task_id]
        runs.sort(key=lambda r: r.started_at)
        return runs

    def append_event(self, task_id: str, payload: dict[str, Any]) -> int:
        file_path = self.logs_dir / f"{task_id}.ndjson"
        with self._lock(f"log-{task_id}"):
            next_seq = 1
            if file_path.exists():
                with file_path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        next_seq = max(next_seq, int(row.get("seq", 0)) + 1)

            entry = {
                "seq": next_seq,
                "ts": utcnow_iso(),
                **payload,
            }
            with file_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return next_seq

    def read_events(self, task_id: str, cursor: int = 0) -> tuple[list[dict[str, Any]], int]:
        file_path = self.logs_dir / f"{task_id}.ndjson"
        if not file_path.exists():
            return [], cursor

        events: list[dict[str, Any]] = []
        max_cursor = cursor
        with file_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                seq = int(row.get("seq", 0))
                max_cursor = max(max_cursor, seq)
                if seq > cursor:
                    events.append(row)
        return events, max_cursor

    def create_notification(self, data: dict[str, Any]) -> Notification:
        with self._lock("notifications"):
            rows = self._read_json(self.notifications_file)
            existing_ids = {str(row.get("id", "")) for row in rows}
            notification = Notification(
                id=self._next_id(existing_ids),
                task_id=data["task_id"],
                type=data.get("type", "INFO"),
                title=data["title"],
                body=data.get("body", ""),
                created_at=utcnow_iso(),
                read=False,
            )
            rows.append(notification.model_dump())
            self._write_json_atomic(self.notifications_file, rows)
        return notification

    def list_notifications(self) -> list[Notification]:
        with self._lock("notifications"):
            rows = self._read_json(self.notifications_file)
        notifications = [Notification.model_validate(row) for row in rows]
        notifications.sort(key=lambda n: n.created_at, reverse=True)
        return notifications

    def mark_notification_read(self, notification_id: str) -> Notification | None:
        with self._lock("notifications"):
            rows = self._read_json(self.notifications_file)
            target = None
            for row in rows:
                if row.get("id") == notification_id:
                    row["read"] = True
                    target = row
                    break
            if target is None:
                return None
            self._write_json_atomic(self.notifications_file, rows)
        return Notification.model_validate(target)

    def board(self, repo_id: str | None = None) -> tuple[dict[str, list[Task]], dict[str, int]]:
        tasks = self.list_tasks(repo_id=repo_id)
        columns: dict[str, list[Task]] = {
            "TODO": [],
            "RUNNING": [],
            "REVIEW": [],
            "DONE": [],
            "FAILED": [],
            "CANCELLED": [],
        }

        for task in tasks:
            if task.status in {TaskStatus.TODO, TaskStatus.READY}:
                key = "TODO"
            elif task.status in {TaskStatus.RUNNING, TaskStatus.PLAN_RUNNING}:
                key = "RUNNING"
            elif task.status in {TaskStatus.REVIEW, TaskStatus.PLAN_REVIEW}:
                key = "REVIEW"
            elif task.status == TaskStatus.DONE:
                key = "DONE"
            elif task.status == TaskStatus.FAILED:
                key = "FAILED"
            else:
                key = "CANCELLED"
            columns[key].append(task)

        counts = {key: len(value) for key, value in columns.items()}
        return columns, counts

    def cleanup_old_logs(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0

        now = time.time()
        deleted = 0
        cutoff_seconds = retention_days * 24 * 3600
        for file_path in self.logs_dir.glob("*.ndjson"):
            age = now - file_path.stat().st_mtime
            if age > cutoff_seconds:
                file_path.unlink(missing_ok=True)
                deleted += 1
        return deleted
