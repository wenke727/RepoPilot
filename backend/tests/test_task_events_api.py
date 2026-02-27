from __future__ import annotations

import json
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


def _create_task(store: JsonStore) -> str:
    task = store.create_task(
        {
            "repo_id": "demo",
            "title": "events",
            "prompt": "check events",
            "mode": TaskMode.EXEC.value,
            "permission_mode": "BYPASS",
            "priority": 0,
        }
    )
    return task.id


def _build_client(store: JsonStore) -> TestClient:
    app = FastAPI()
    app.state.store = store
    app.state.scheduler = _DummyScheduler()
    app.include_router(tasks.router)
    return TestClient(app)


def _append_stream(store: JsonStore, task_id: str, payload_or_line: dict[str, object] | str) -> int:
    if isinstance(payload_or_line, str):
        line = payload_or_line
    else:
        line = json.dumps(payload_or_line, ensure_ascii=False)
    return store.append_event(task_id, {"type": "stream", "line": line})


def test_events_api_enriches_display_and_preserves_original_fields(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    task_id = _create_task(store)
    client = _build_client(store)

    store.append_event(task_id, {"type": "command", "cmd": "echo hello"})
    _append_stream(
        store,
        task_id,
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "第一行"},
                    {"type": "text", "text": "第二行"},
                ],
            },
        },
    )
    _append_stream(
        store,
        task_id,
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "README.md"}}],
            },
        },
    )
    _append_stream(
        store,
        task_id,
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "ok"}],
            },
        },
    )
    _append_stream(store, task_id, {"type": "system", "subtype": "hook_started", "hook_name": "startup"})
    _append_stream(store, task_id, {"type": "result", "subtype": "success", "result": "任务完成"})
    _append_stream(store, task_id, "{not a json line")
    store.append_event(task_id, {"type": "assistant_text", "text": "最终总结"})
    store.append_event(task_id, {"type": "timeout", "message": "执行超时"})
    store.append_event(task_id, {"type": "artifact", "path": "state/artifacts/t-1/run-1"})

    resp = client.get(f"/api/tasks/{task_id}/events?cursor=0")
    assert resp.status_code == 200
    payload = resp.json()
    events = payload["events"]
    assert payload["next_cursor"] == 10
    assert len(events) == 10

    by_seq = {int(event["seq"]): event for event in events}

    command = by_seq[1]
    assert command["type"] == "command"
    assert command["cmd"] == "echo hello"
    assert command["display"]["group"] == "command"
    assert command["display"]["label"] == "命令"
    assert command["display"]["merge_key"] == "command:command"
    assert '"seq"' not in command["display"]["raw"]

    output = by_seq[2]
    assert output["type"] == "stream"
    assert "line" in output
    assert output["display"]["group"] == "output"
    assert output["display"]["label"] == "输出"
    assert "第一行" in output["display"]["text"]
    assert output["display"]["raw"] == output["line"]

    assistant_tool_use = by_seq[3]
    assert assistant_tool_use["display"]["group"] == "protocol"
    assert assistant_tool_use["display"]["merge_key"] == "protocol:assistant"
    assert "助手调用工具" in assistant_tool_use["display"]["text"]

    user_tool_result = by_seq[4]
    assert user_tool_result["display"]["group"] == "protocol"
    assert user_tool_result["display"]["merge_key"] == "protocol:user"
    assert "工具返回结果" in user_tool_result["display"]["text"]

    system_hook = by_seq[5]
    assert system_hook["display"]["group"] == "protocol"
    assert system_hook["display"]["merge_key"] == "protocol:hook_started"
    assert "系统事件" in system_hook["display"]["text"]

    result_success = by_seq[6]
    assert result_success["display"]["group"] == "result"
    assert result_success["display"]["label"] == "结果"
    assert result_success["display"]["merge_key"] == "result:success"
    assert result_success["display"]["text"] == "任务完成"

    unparsed_stream = by_seq[7]
    assert unparsed_stream["display"]["group"] == "protocol"
    assert unparsed_stream["display"]["merge_key"] == "protocol:unparsed"
    assert "{not a json line" in unparsed_stream["display"]["text"]
    assert unparsed_stream["display"]["raw"] == unparsed_stream["line"]

    assistant_text = by_seq[8]
    assert assistant_text["display"]["group"] == "result"
    assert assistant_text["display"]["merge_key"] == "result:assistant_text"
    assert assistant_text["display"]["text"] == "最终总结"

    timeout = by_seq[9]
    assert timeout["display"]["group"] == "timeout"
    assert timeout["display"]["merge_key"] == "timeout:timeout"
    assert timeout["display"]["text"] == "执行超时"

    artifact = by_seq[10]
    assert artifact["display"]["group"] == "artifact"
    assert artifact["display"]["merge_key"] == "artifact:artifact"
    assert artifact["display"]["text"] == "state/artifacts/t-1/run-1"

    cursor_resp = client.get(f"/api/tasks/{task_id}/events?cursor=5")
    assert cursor_resp.status_code == 200
    cursor_payload = cursor_resp.json()
    assert [int(event["seq"]) for event in cursor_payload["events"]] == [6, 7, 8, 9, 10]
    assert all("display" in event for event in cursor_payload["events"])


def test_event_display_preview_truncates_to_600_chars(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    task_id = _create_task(store)
    client = _build_client(store)

    store.append_event(task_id, {"type": "assistant_text", "text": "x" * 605})

    resp = client.get(f"/api/tasks/{task_id}/events?cursor=0")
    assert resp.status_code == 200
    event = resp.json()["events"][0]
    assert event["display"]["group"] == "result"
    assert len(event["display"]["text"]) == 601
    assert event["display"]["text"].endswith("…")


def test_get_task_includes_claude_session_id(tmp_path: Path):
    store = _create_store(tmp_path)
    _inject_demo_repo(store, tmp_path / "repos" / "demo")
    task_id = _create_task(store)
    client = _build_client(store)

    patched = store.update_task(task_id, {"claude_session_id": "22222222-2222-2222-2222-222222222222"})
    assert patched is not None

    resp = client.get(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["id"] == task_id
    assert payload["claude_session_id"] == "22222222-2222-2222-2222-222222222222"
