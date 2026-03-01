from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import Settings, get_exec_mode
from app.core import git_ops
from app.core.env import select_conda_env
from app.core.plan_parser import parse_plan, plan_prompt
from app.core.strategy import build_default_strategy
from app.models import (
    PermissionMode,
    RepoConfig,
    Task,
    TaskMode,
    TaskStatus,
    utcnow_iso,
)
from app.store.json_store import JsonStore


class TaskRunner:
    _RESUME_FALLBACK_ERROR_PATTERNS = (
        re.compile(r"session id .*not found", re.IGNORECASE),
        re.compile(r"failed to resume", re.IGNORECASE),
        re.compile(r"unable to resume", re.IGNORECASE),
        re.compile(r"cannot resume", re.IGNORECASE),
        re.compile(r"invalid session", re.IGNORECASE),
        re.compile(r"session .*does not exist", re.IGNORECASE),
    )

    def __init__(self, store: JsonStore, settings: Settings) -> None:
        self.logger = logging.getLogger("app.runner")
        self.store = store
        self.settings = settings
        self._proc_lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[str]] = {}

    def cancel(self, task_id: str) -> None:
        self.logger.info("Terminating process for task=%s", task_id)
        with self._proc_lock:
            proc = self._processes.get(task_id)
        if not proc:
            return
        if proc.poll() is None:
            proc.terminate()

    def _register_proc(self, task_id: str, proc: subprocess.Popen[str]) -> None:
        with self._proc_lock:
            self._processes[task_id] = proc

    def _unregister_proc(self, task_id: str) -> None:
        with self._proc_lock:
            self._processes.pop(task_id, None)

    def _is_cancel_requested(self, task_id: str) -> bool:
        task = self.store.get_task(task_id)
        if not task:
            return False
        return bool(task.cancel_requested)

    def _ensure_task_session_id(self, task: Task) -> tuple[str, bool]:
        if task.claude_session_id:
            return task.claude_session_id, False

        latest = self.store.get_task(task.id)
        if latest and latest.claude_session_id:
            task.claude_session_id = latest.claude_session_id
            return latest.claude_session_id, False

        new_session_id = str(uuid.uuid4())
        patched = self.store.update_task(task.id, {"claude_session_id": new_session_id})
        if patched and patched.claude_session_id:
            task.claude_session_id = patched.claude_session_id
            return patched.claude_session_id, True

        task.claude_session_id = new_session_id
        return new_session_id, True

    def _build_claude_cmd(
        self,
        task: Task,
        prompt: str,
        *,
        session_id: str,
        use_resume: bool,
    ) -> list[str]:
        cmd = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        if use_resume:
            cmd.extend(["--resume", session_id])
        else:
            cmd.extend(["--session-id", session_id])

        if task.permission_mode == PermissionMode.BYPASS:
            cmd.extend(["--permission-mode", "bypassPermissions"])
        else:
            cmd.extend(["--permission-mode", "default"])
        return cmd

    def _is_resume_recoverable_error(self, text: str) -> bool:
        if not text.strip():
            return False
        return any(pattern.search(text) for pattern in self._RESUME_FALLBACK_ERROR_PATTERNS)

    def _run_claude_cmd(
        self,
        task: Task,
        cmd: list[str],
        workdir: Path,
        timeout_seconds: int,
    ) -> tuple[int, str, bool]:
        self.store.append_event(task.id, {"type": "command", "cmd": " ".join(cmd)})
        proc = subprocess.Popen(
            cmd,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._register_proc(task.id, proc)

        collected_text: list[str] = []
        cancelled = False
        start = time.time()

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue

                self.store.append_event(task.id, {"type": "stream", "line": line})
                maybe_text = self._extract_text_from_stream_line(line)
                if maybe_text:
                    collected_text.append(maybe_text)

                if self._is_cancel_requested(task.id):
                    cancelled = True
                    proc.terminate()
                    break

                if time.time() - start > timeout_seconds:
                    self.store.append_event(task.id, {"type": "timeout", "message": "Task exceeded 45 minutes"})
                    proc.terminate()
                    break

            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        finally:
            self._unregister_proc(task.id)

        # If another thread/API terminated the process, still classify as cancelled.
        if not cancelled and self._is_cancel_requested(task.id):
            cancelled = True

        return proc.returncode or 0, "\n".join(collected_text).strip(), cancelled

    def _stream_claude(
        self,
        task: Task,
        prompt: str,
        workdir: Path,
        timeout_seconds: int = 2700,
    ) -> tuple[int, str, bool]:
        session_id, created = self._ensure_task_session_id(task)
        use_resume = not created
        if created:
            self.store.append_event(
                task.id,
                {
                    "type": "session_created",
                    "session_id": session_id,
                    "message": f"Created Claude session {session_id}",
                },
            )
        else:
            self.store.append_event(
                task.id,
                {
                    "type": "session_resumed",
                    "session_id": session_id,
                    "message": f"Resuming Claude session {session_id}",
                },
            )

        cmd = self._build_claude_cmd(task, prompt, session_id=session_id, use_resume=use_resume)
        exit_code, text, cancelled = self._run_claude_cmd(task, cmd, workdir, timeout_seconds)

        should_fallback = (
            use_resume
            and not cancelled
            and exit_code != 0
            and self._is_resume_recoverable_error(text)
        )
        if not should_fallback:
            return exit_code, text, cancelled

        self.store.append_event(
            task.id,
            {
                "type": "session_resume_failed",
                "session_id": session_id,
                "message": f"Resume failed for session {session_id}; fallback to a new session",
                "error_text": text[:1000],
            },
        )

        new_session_id = str(uuid.uuid4())
        patched = self.store.update_task(task.id, {"claude_session_id": new_session_id})
        if patched and patched.claude_session_id:
            new_session_id = patched.claude_session_id
        task.claude_session_id = new_session_id
        self.store.append_event(
            task.id,
            {
                "type": "session_fallback_created",
                "old_session_id": session_id,
                "session_id": new_session_id,
                "message": f"Created fallback Claude session {new_session_id}",
            },
        )

        fallback_cmd = self._build_claude_cmd(task, prompt, session_id=new_session_id, use_resume=False)
        return self._run_claude_cmd(task, fallback_cmd, workdir, timeout_seconds)

    def _extract_text_from_stream_line(self, line: str) -> str:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return line

        chunks: list[str] = []

        if isinstance(payload.get("text"), str):
            chunks.append(payload["text"])

        result = payload.get("result")
        if isinstance(result, str):
            chunks.append(result)

        message = payload.get("message")
        if isinstance(message, dict):
            content = message.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        chunks.append(item["text"])

        delta = payload.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("text"), str):
            chunks.append(delta["text"])

        return "\n".join(chunks).strip()

    def _finish_run(self, run_id: str, patch: dict[str, Any]) -> None:
        patch.setdefault("ended_at", utcnow_iso())
        self.store.update_run(run_id, patch)

    def _mark_cancelled(self, task: Task, run_id: str, reason: str) -> None:
        self.store.update_task(
            task.id,
            {
                "status": TaskStatus.CANCELLED.value,
                "error_code": "CANCELLED",
                "error_message": reason,
                "current_run_id": run_id,
            },
        )
        self.store.create_notification(
            {
                "task_id": task.id,
                "type": "INFO",
                "title": f"任务已取消: {task.title}",
                "body": reason,
            }
        )

    def _mark_failed(self, task: Task, run_id: str, code: str, message: str) -> None:
        self.store.update_task(
            task.id,
            {
                "status": TaskStatus.FAILED.value,
                "error_code": code,
                "error_message": message,
                "current_run_id": run_id,
            },
        )
        self.store.create_notification(
            {
                "task_id": task.id,
                "type": "ERROR",
                "title": f"任务失败: {task.title}",
                "body": message[:500],
            }
        )

    def _mark_review(self, task: Task, run_id: str, pr_url: str) -> None:
        self.store.update_task(
            task.id,
            {
                "status": TaskStatus.REVIEW.value,
                "pr_url": pr_url,
                "error_code": "",
                "error_message": "",
                "current_run_id": run_id,
                "cancel_requested": False,
            },
        )
        self.store.create_notification(
            {
                "task_id": task.id,
                "type": "SUCCESS",
                "title": f"任务进入 Review: {task.title}",
                "body": pr_url,
            }
        )

    def _cleanup_exec_worktree_for_run(
        self,
        task: Task,
        run_id: str,
        trigger_status: TaskStatus,
        snapshot_on_failure: bool,
    ) -> bool:
        run = self.store.get_run(run_id)
        if run is None:
            self.logger.warning("Skip worktree cleanup: run not found task=%s run=%s", task.id, run_id)
            self.store.append_event(
                task.id,
                {
                    "type": "worktree_cleanup",
                    "trigger_status": trigger_status.value,
                    "result": "run_not_found",
                    "run_id": run_id,
                },
            )
            return False

        worktree_path = run.worktree_path.strip()
        if not worktree_path:
            self.store.append_event(
                task.id,
                {
                    "type": "worktree_cleanup",
                    "trigger_status": trigger_status.value,
                    "result": "skip_empty_path",
                    "run_id": run_id,
                },
            )
            return True

        repo = self.store.get_repo(task.repo_id)
        if repo is None:
            self.logger.warning("Skip worktree cleanup: repo not found task=%s repo=%s", task.id, task.repo_id)
            self.store.append_event(
                task.id,
                {
                    "type": "worktree_cleanup",
                    "trigger_status": trigger_status.value,
                    "result": "repo_not_found",
                    "run_id": run_id,
                    "worktree_path": worktree_path,
                },
            )
            return False

        worktree = Path(worktree_path)
        if snapshot_on_failure:
            try:
                snapshot = git_ops.snapshot_worktree(
                    worktree=worktree,
                    artifacts_root=self.settings.artifacts_dir,
                    task_id=task.id,
                    run_id=run_id,
                )
                self.store.update_run(run_id, {"metrics": {"artifact_path": str(snapshot)}})
                self.store.append_event(task.id, {"type": "artifact", "path": str(snapshot)})
                self.logger.info("Saved failed task artifact task=%s run=%s path=%s", task.id, run_id, snapshot)
            except Exception as exc:  # pragma: no cover
                self.logger.warning("Failed to save task artifact task=%s run=%s err=%s", task.id, run_id, exc)

        try:
            git_ops.cleanup_worktree(repo, worktree, run.branch_name)
            self.store.update_run(run_id, {"worktree_path": ""})
            self.store.append_event(
                task.id,
                {
                    "type": "worktree_cleanup",
                    "trigger_status": trigger_status.value,
                    "result": "success",
                    "run_id": run_id,
                    "worktree_path": worktree_path,
                    "branch_name": run.branch_name,
                },
            )
            return True
        except Exception as exc:  # pragma: no cover
            self.logger.warning("Worktree cleanup failed task=%s run=%s err=%s", task.id, run_id, exc)
            self.store.append_event(
                task.id,
                {
                    "type": "worktree_cleanup",
                    "trigger_status": trigger_status.value,
                    "result": "failed",
                    "run_id": run_id,
                    "worktree_path": worktree_path,
                    "branch_name": run.branch_name,
                    "error_message": str(exc)[:500],
                },
            )
            return False

    def cleanup_exec_worktree_for_task(
        self,
        task: Task,
        trigger_status: TaskStatus,
        snapshot_on_failure: bool = False,
    ) -> bool:
        if task.mode != TaskMode.EXEC:
            return False
        if not task.current_run_id:
            self.store.append_event(
                task.id,
                {
                    "type": "worktree_cleanup",
                    "trigger_status": trigger_status.value,
                    "result": "skip_no_current_run",
                },
            )
            return False
        return self._cleanup_exec_worktree_for_run(
            task=task,
            run_id=task.current_run_id,
            trigger_status=trigger_status,
            snapshot_on_failure=snapshot_on_failure,
        )

    def run_task(self, task: Task, worker_id: str) -> None:
        selected_env = select_conda_env()
        self.logger.info(
            "Run start task=%s worker=%s mode=%s env=%s",
            task.id,
            worker_id,
            task.mode.value,
            selected_env or "none",
        )
        run = self.store.create_run(task.id, worker_id=worker_id, python_env_used=selected_env or "none")

        if task.mode == TaskMode.PLAN:
            self._run_plan(task, run.id)
            return

        if get_exec_mode(self.settings) == "FIXED":
            self._run_exec_fixed(task, run.id)
        else:
            self._run_exec_agentic(task, run.id)

    def _run_plan(self, task: Task, run_id: str) -> None:
        repo = self.store.get_repo(task.repo_id)
        if not repo:
            self.logger.error("Plan failed repo not found task=%s repo=%s", task.id, task.repo_id)
            self._finish_run(run_id, {"exit_code": 1})
            self._mark_failed(task, run_id, "REPO_NOT_FOUND", f"Repo not found: {task.repo_id}")
            return

        repo_path = Path(repo.root_path)
        self.store.update_run(run_id, {"worktree_path": str(repo_path)})
        prompt = plan_prompt(task.prompt)
        exit_code, text, cancelled = self._stream_claude(task, prompt=prompt, workdir=repo_path)

        if cancelled:
            self.logger.info("Plan cancelled task=%s run=%s", task.id, run_id)
            self._finish_run(run_id, {"exit_code": exit_code})
            self._mark_cancelled(task, run_id, "任务在 Plan 阶段被取消")
            return

        if exit_code != 0:
            self.logger.warning("Plan failed task=%s run=%s exit=%s", task.id, run_id, exit_code)
            self._finish_run(run_id, {"exit_code": exit_code})
            self._mark_failed(task, run_id, "PLAN_EXIT_NONZERO", f"Claude exited with code {exit_code}")
            return

        parsed = parse_plan(text)
        self.store.update_task(
            task.id,
            {
                "status": TaskStatus.PLAN_REVIEW.value,
                "plan_result": parsed.model_dump(),
                "error_code": "",
                "error_message": "",
                "current_run_id": run_id,
            },
        )
        self.store.create_notification(
            {
                "task_id": task.id,
                "type": "INFO",
                "title": f"Plan 待确认: {task.title}",
                "body": "请在任务详情中确认 Plan 选项后继续执行。",
            }
        )
        self.logger.info("Plan ready for review task=%s run=%s", task.id, run_id)
        self._finish_run(run_id, {"exit_code": 0})

    def _build_agentic_prompt(self, task: Task, repo: RepoConfig, branch: str) -> str:
        """Build task prompt with post-coding instructions for Claude to run git/test/push/PR."""
        main = repo.main_branch
        test_cmd = (repo.test_command or "").strip()
        has_github = bool(repo.github_repo and "/" in repo.github_repo.strip())
        lines = [
            task.prompt,
            "",
            "---",
            "【编码完成后请自行执行以下步骤，使用终端命令完成】",
            "",
            "1. 提交变更:",
            "   git add -A && git commit -m \"task(" + task.id + "): apply changes\"",
            "",
            "2. 变基到主分支（若有冲突请解决后 git add 再 git rebase --continue）:",
            f"   git fetch origin {main} && git rebase origin/{main}",
            "",
        ]
        if test_cmd:
            lines.append("3. 运行测试:")
            lines.append(f"   {test_cmd}")
            lines.append("")
            lines.append("4. 推送当前分支:")
        else:
            lines.append("3. 推送当前分支:")
        lines.append(f"   git push -u origin {branch}")
        if has_github:
            lines.append("")
            lines.append("5. 创建 PR（若 gh 可用）:")
            lines.append(f"   gh pr create --base {main} --head {branch} --title \"[{task.id}] {task.title}\" --body \"Automated by RepoPilot\"")
        lines.append("")
        return "\n".join(lines)

    def _extract_pr_url(self, text: str, repo: RepoConfig | None, branch: str) -> str:
        """Extract first GitHub PR URL from Claude output; fallback to compare URL if none."""
        match = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+", text)
        if match:
            return match.group(0)
        if repo and repo.github_repo and "/" in repo.github_repo.strip():
            return git_ops.build_compare_url(repo.github_repo, repo.main_branch, branch) or ""
        return ""

    def _run_exec_fixed(self, task: Task, run_id: str) -> None:
        repo = self.store.get_repo(task.repo_id)
        if not repo:
            self.logger.error("Exec failed repo not found task=%s repo=%s", task.id, task.repo_id)
            self._finish_run(run_id, {"exit_code": 1})
            self._mark_failed(task, run_id, "REPO_NOT_FOUND", f"Repo not found: {task.repo_id}")
            return

        worktree_info: git_ops.WorktreeInfo | None = None
        try:
            worktree_info = git_ops.create_worktree(repo, self.settings.worktrees_dir, task.id, task.title)
            self.store.update_run(
                run_id,
                {"worktree_path": str(worktree_info.path), "branch_name": worktree_info.branch},
            )
            git_ops.setup_isolated_data(worktree_info.path, repo)
            baseline_commit = git_ops.current_commit(worktree_info.path)

            exit_code, text, cancelled = self._stream_claude(
                task,
                prompt=task.prompt,
                workdir=worktree_info.path,
            )
            self.store.append_event(task.id, {"type": "assistant_text", "text": text})

            if cancelled:
                self.logger.info("Exec cancelled task=%s run=%s", task.id, run_id)
                self._finish_run(run_id, {"exit_code": exit_code})
                self._mark_cancelled(task, run_id, "任务在执行阶段被取消")
                return

            if exit_code != 0:
                self.logger.warning("Exec failed non-zero task=%s run=%s exit=%s", task.id, run_id, exit_code)
                self._finish_run(run_id, {"exit_code": exit_code})
                self._mark_failed(task, run_id, "EXEC_EXIT_NONZERO", f"Claude exited with code {exit_code}")
                return

            if not git_ops.has_material_changes(worktree_info.path, baseline_commit):
                self.logger.warning("Exec produced no changes task=%s run=%s", task.id, run_id)
                self._finish_run(run_id, {"exit_code": 1})
                self._mark_failed(task, run_id, "NO_CHANGES", "Claude finished but produced no git changes")
                return

            commit_sha = git_ops.commit_all(worktree_info.path, f"task({task.id}): apply changes")
            self.store.update_run(run_id, {"commit_sha": commit_sha})

            git_ops.rebase_with_main(worktree_info.path, repo.main_branch)
            git_ops.run_tests(worktree_info.path, repo.test_command)
            git_ops.push_branch(worktree_info.path, worktree_info.branch)

            try:
                pr_url = git_ops.create_pr(
                    repo,
                    branch=worktree_info.branch,
                    title=f"[{task.id}] {task.title}",
                    body="Automated by Claude Code Web Manager",
                )
            except git_ops.PRCredentialsMissing as exc:
                pr_url = git_ops.build_compare_url(repo.github_repo, repo.main_branch, worktree_info.branch)
                if not pr_url:
                    raise git_ops.GitError(str(exc))
                self.store.append_event(
                    task.id,
                    {
                        "type": "pr_fallback",
                        "message": str(exc),
                        "compare_url": pr_url,
                    },
                )
                self.logger.warning(
                    "PR credentials missing, fallback compare URL used task=%s run=%s url=%s",
                    task.id,
                    run_id,
                    pr_url,
                )

            self._mark_review(task, run_id, pr_url)
            self.logger.info("Exec done, moved to REVIEW task=%s run=%s pr=%s", task.id, run_id, pr_url)
            self._finish_run(run_id, {"exit_code": 0, "commit_sha": commit_sha})
        except git_ops.GitError as exc:
            self.logger.warning("Git pipeline failed task=%s run=%s err=%s", task.id, run_id, exc)
            self._finish_run(run_id, {"exit_code": 1})
            self._mark_failed(task, run_id, "GIT_PIPELINE_FAILED", str(exc))
        except Exception as exc:  # pragma: no cover
            self.logger.exception("Unexpected runner error task=%s run=%s", task.id, run_id)
            self._finish_run(run_id, {"exit_code": 1})
            self._mark_failed(task, run_id, "UNEXPECTED_ERROR", str(exc))
        finally:
            if worktree_info is not None:
                task_after = self.store.get_task(task.id)
                if task_after and task_after.status in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
                    self._cleanup_exec_worktree_for_run(
                        task=task_after,
                        run_id=run_id,
                        trigger_status=task_after.status,
                        snapshot_on_failure=True,
                    )

    def _run_exec_agentic(self, task: Task, run_id: str) -> None:
        repo = self.store.get_repo(task.repo_id)
        if not repo:
            self.logger.error("Exec failed repo not found task=%s repo=%s", task.id, task.repo_id)
            self._finish_run(run_id, {"exit_code": 1})
            self._mark_failed(task, run_id, "REPO_NOT_FOUND", f"Repo not found: {task.repo_id}")
            return

        worktree_info: git_ops.WorktreeInfo | None = None
        try:
            worktree_info = git_ops.create_worktree(repo, self.settings.worktrees_dir, task.id, task.title)
            self.store.update_run(
                run_id,
                {"worktree_path": str(worktree_info.path), "branch_name": worktree_info.branch},
            )
            git_ops.setup_isolated_data(worktree_info.path, repo)

            strategy = build_default_strategy(repo)
            self.store.update_task(task.id, {"exec_strategy": strategy.model_dump()})
            self.store.append_event(
                task.id,
                {"type": "strategy_generated", "message": strategy.rationale or "Claude 全权执行（编码 + 提交/变基/测试/推送/PR）"},
            )

            prompt = self._build_agentic_prompt(task, repo, worktree_info.branch)
            exit_code, text, cancelled = self._stream_claude(
                task,
                prompt=prompt,
                workdir=worktree_info.path,
            )
            self.store.append_event(task.id, {"type": "assistant_text", "text": text})

            if cancelled:
                self.logger.info("Exec cancelled task=%s run=%s", task.id, run_id)
                self._finish_run(run_id, {"exit_code": exit_code})
                self._mark_cancelled(task, run_id, "任务在执行阶段被取消")
                return

            if exit_code != 0:
                self.logger.warning("Exec failed non-zero task=%s run=%s exit=%s", task.id, run_id, exit_code)
                self._finish_run(run_id, {"exit_code": exit_code})
                self._mark_failed(task, run_id, "EXEC_EXIT_NONZERO", f"Claude exited with code {exit_code}")
                return

            pr_url = self._extract_pr_url(text, repo, worktree_info.branch)
            self._mark_review(task, run_id, pr_url)
            self.logger.info("Exec done (agentic), moved to REVIEW task=%s run=%s pr=%s", task.id, run_id, pr_url)
            self._finish_run(run_id, {"exit_code": 0})
        except git_ops.GitError as exc:
            self.logger.warning("Git pipeline failed task=%s run=%s err=%s", task.id, run_id, exc)
            self._finish_run(run_id, {"exit_code": 1})
            self._mark_failed(task, run_id, "GIT_PIPELINE_FAILED", str(exc))
        except Exception as exc:  # pragma: no cover
            self.logger.exception("Unexpected runner error task=%s run=%s", task.id, run_id)
            self._finish_run(run_id, {"exit_code": 1})
            self._mark_failed(task, run_id, "UNEXPECTED_ERROR", str(exc))
        finally:
            if worktree_info is not None:
                task_after = self.store.get_task(task.id)
                if task_after and task_after.status in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
                    self._cleanup_exec_worktree_for_run(
                        task=task_after,
                        run_id=run_id,
                        trigger_status=task_after.status,
                        snapshot_on_failure=True,
                    )
