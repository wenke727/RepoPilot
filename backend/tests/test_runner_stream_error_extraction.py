from __future__ import annotations

import json
from pathlib import Path

from app.config import load_settings
from app.core.runner import TaskRunner
from app.store.json_store import JsonStore


def _create_runner(tmp_path: Path) -> TaskRunner:
    store = JsonStore(state_dir=tmp_path / "state", repos_dir=tmp_path / "repos")
    return TaskRunner(store, load_settings(tmp_path))


def test_extract_text_from_stream_line_includes_errors_array(tmp_path: Path):
    runner = _create_runner(tmp_path)
    line = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "errors": ["No conversation found with session ID: deadbeef"],
        }
    )

    text = runner._extract_text_from_stream_line(line)
    assert "No conversation found with session ID: deadbeef" in text


def test_extract_text_from_stream_line_handles_errors_objects_and_error_object(tmp_path: Path):
    runner = _create_runner(tmp_path)
    line = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "errors": [{"message": "Resume token invalid"}],
            "error": {"message": "Fallback required"},
        }
    )

    text = runner._extract_text_from_stream_line(line)
    assert "Resume token invalid" in text
    assert "Fallback required" in text
