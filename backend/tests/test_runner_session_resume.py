from __future__ import annotations

from pathlib import Path

from app.config import load_settings, set_agent_driver
from app.core.runner import TaskRunner
from app.models import Task, TaskMode
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


def _create_task(store: JsonStore) -> tuple[str, Task]:
    task = store.create_task(
        {
            "repo_id": "demo",
            "title": "session-test",
            "prompt": "check session",
            "mode": TaskMode.EXEC.value,
            "permission_mode": "BYPASS",
            "priority": 0,
        }
    )
    return task.id, task


def _find_flag_value(cmd: list[str], flag: str) -> str:
    idx = cmd.index(flag)
    return cmd[idx + 1]


def _mark_session_confirmed(store: JsonStore, task_id: str, session_id: str) -> None:
    store.append_event(
        task_id,
        {
            "type": "session_confirmed",
            "session_id": session_id,
            "message": f"Confirmed Claude session {session_id}",
        },
    )


def _assert_shell_wrapped(cmd: list[str], template: str) -> None:
    assert cmd[0] == "zsh"
    assert cmd[1] == "-ic"
    assert cmd[2] == f'{template} "$@"'
    assert cmd[3] == "repopilot"


def test_stream_claude_first_run_uses_session_id_and_persists(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    task_id, task = _create_task(store)

    calls: list[list[str]] = []

    def fake_run(task, cmd, workdir, timeout_seconds, expected_session_id=None):
        calls.append(cmd)
        return 0, "ok", False

    monkeypatch.setattr(runner, "_run_claude_cmd", fake_run)

    exit_code, text, cancelled = runner._stream_claude(task, prompt="hello", workdir=tmp_path)
    assert exit_code == 0
    assert text == "ok"
    assert cancelled is False
    assert len(calls) == 1
    _assert_shell_wrapped(calls[0], "claude-kimi")
    assert "--session-id" in calls[0]
    assert "--resume" not in calls[0]

    session_id = _find_flag_value(calls[0], "--session-id")
    stored_task = store.get_task(task_id)
    assert stored_task is not None
    assert stored_task.claude_session_id == session_id


def test_stream_claude_with_existing_session_uses_resume(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    task_id, _ = _create_task(store)
    session_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    patched = store.update_task(task_id, {"claude_session_id": session_id})
    assert patched is not None
    _mark_session_confirmed(store, task_id, session_id)

    calls: list[list[str]] = []

    def fake_run(task, cmd, workdir, timeout_seconds, expected_session_id=None):
        calls.append(cmd)
        return 0, "ok", False

    monkeypatch.setattr(runner, "_run_claude_cmd", fake_run)

    exit_code, text, cancelled = runner._stream_claude(patched, prompt="hello", workdir=tmp_path)
    assert exit_code == 0
    assert text == "ok"
    assert cancelled is False
    assert len(calls) == 1
    _assert_shell_wrapped(calls[0], "claude-kimi")
    assert "--resume" in calls[0]
    assert "--session-id" not in calls[0]
    assert _find_flag_value(calls[0], "--resume") == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_stream_claude_resume_failure_falls_back_to_new_session(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    task_id, _ = _create_task(store)
    session_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    patched = store.update_task(task_id, {"claude_session_id": session_id})
    assert patched is not None
    _mark_session_confirmed(store, task_id, session_id)

    calls: list[list[str]] = []

    def fake_run(task, cmd, workdir, timeout_seconds, expected_session_id=None):
        calls.append(cmd)
        if len(calls) == 1:
            return 1, "No conversation found with session ID: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", False
        return 0, "ok", False

    monkeypatch.setattr(runner, "_run_claude_cmd", fake_run)

    exit_code, text, cancelled = runner._stream_claude(patched, prompt="hello", workdir=tmp_path)
    assert exit_code == 0
    assert text == "ok"
    assert cancelled is False
    assert len(calls) == 2
    _assert_shell_wrapped(calls[0], "claude-kimi")
    _assert_shell_wrapped(calls[1], "claude-kimi")
    assert "--resume" in calls[0]
    assert _find_flag_value(calls[0], "--resume") == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert "--session-id" in calls[1]
    fallback_session_id = _find_flag_value(calls[1], "--session-id")
    assert fallback_session_id != "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    stored_task = store.get_task(task_id)
    assert stored_task is not None
    assert stored_task.claude_session_id == fallback_session_id

    events, _ = store.read_events(task_id, cursor=0)
    event_types = [event.get("type") for event in events]
    assert "session_resume_failed" in event_types
    assert "session_fallback_created" in event_types


def test_stream_claude_non_session_error_does_not_fallback(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    task_id, _ = _create_task(store)
    session_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    patched = store.update_task(task_id, {"claude_session_id": session_id})
    assert patched is not None
    _mark_session_confirmed(store, task_id, session_id)

    calls: list[list[str]] = []

    def fake_run(task, cmd, workdir, timeout_seconds, expected_session_id=None):
        calls.append(cmd)
        return 1, "fatal: unrelated execution error", False

    monkeypatch.setattr(runner, "_run_claude_cmd", fake_run)

    exit_code, text, cancelled = runner._stream_claude(patched, prompt="hello", workdir=tmp_path)
    assert exit_code == 1
    assert text == "fatal: unrelated execution error"
    assert cancelled is False
    assert len(calls) == 1
    _assert_shell_wrapped(calls[0], "claude-kimi")
    assert "--resume" in calls[0]

    events, _ = store.read_events(task_id, cursor=0)
    event_types = [event.get("type") for event in events]
    assert "session_resume_failed" not in event_types
    assert "session_fallback_created" not in event_types


def test_stream_claude_existing_unconfirmed_session_skips_resume(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    task_id, _ = _create_task(store)
    patched = store.update_task(task_id, {"claude_session_id": "dddddddd-dddd-dddd-dddd-dddddddddddd"})
    assert patched is not None

    calls: list[list[str]] = []

    def fake_run(task, cmd, workdir, timeout_seconds, expected_session_id=None):
        calls.append(cmd)
        return 0, "ok", False

    monkeypatch.setattr(runner, "_run_claude_cmd", fake_run)

    exit_code, text, cancelled = runner._stream_claude(patched, prompt="hello", workdir=tmp_path)
    assert exit_code == 0
    assert text == "ok"
    assert cancelled is False
    assert len(calls) == 1
    _assert_shell_wrapped(calls[0], "claude-kimi")
    assert "--session-id" in calls[0]
    assert "--resume" not in calls[0]

    events, _ = store.read_events(task_id, cursor=0)
    event_types = [event.get("type") for event in events]
    assert "session_resume_skipped" in event_types


def test_stream_claude_uses_glm_driver_command_when_configured(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_DRIVER", "CLAUDE_GLM")
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    _, task = _create_task(store)

    calls: list[list[str]] = []

    def fake_run(task, cmd, workdir, timeout_seconds, expected_session_id=None):
        calls.append(cmd)
        return 0, "ok", False

    monkeypatch.setattr(runner, "_run_claude_cmd", fake_run)

    exit_code, text, cancelled = runner._stream_claude(task, prompt="hello", workdir=tmp_path)
    assert exit_code == 0
    assert text == "ok"
    assert cancelled is False
    assert len(calls) == 1
    _assert_shell_wrapped(calls[0], "claude-glm")
    assert "--session-id" in calls[0]


def test_stream_claude_glm_empty_shell_template_falls_back_to_cmd(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_DRIVER", "CLAUDE_GLM")
    monkeypatch.setenv("REPOPILOT_CLAUDE_GLM_SHELL_TEMPLATE", "")
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    _, task = _create_task(store)

    calls: list[list[str]] = []

    def fake_run(task, cmd, workdir, timeout_seconds, expected_session_id=None):
        calls.append(cmd)
        return 0, "ok", False

    monkeypatch.setattr(runner, "_run_claude_cmd", fake_run)

    exit_code, text, cancelled = runner._stream_claude(task, prompt="hello", workdir=tmp_path)
    assert exit_code == 0
    assert text == "ok"
    assert cancelled is False
    assert len(calls) == 1
    assert calls[0][0] == "claude-glm"
    assert "--session-id" in calls[0]


def test_stream_claude_uses_claude_driver_command_when_configured(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_DRIVER", "CLAUDE")
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    runner = TaskRunner(store, load_settings(tmp_path))
    _, task = _create_task(store)

    calls: list[list[str]] = []

    def fake_run(task, cmd, workdir, timeout_seconds, expected_session_id=None):
        calls.append(cmd)
        return 0, "ok", False

    monkeypatch.setattr(runner, "_run_claude_cmd", fake_run)

    exit_code, text, cancelled = runner._stream_claude(task, prompt="hello", workdir=tmp_path)
    assert exit_code == 0
    assert text == "ok"
    assert cancelled is False
    assert len(calls) == 1
    assert calls[0][0] == "claude"
    assert "--session-id" in calls[0]
