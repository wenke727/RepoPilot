from __future__ import annotations

from pathlib import Path

from app.config import load_settings, set_agent_driver
from app.core.health import get_health


def test_health_degraded_when_active_driver_command_missing(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_DRIVER", "CLAUDE_GLM")

    def fake_which(name: str):
        if name in {"git", "python3"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr("app.core.health.shutil.which", fake_which)
    monkeypatch.setattr("app.core.health.subprocess.call", lambda *args, **kwargs: 1)
    monkeypatch.setattr("app.core.health.select_conda_env", lambda: "base")

    payload = get_health(load_settings(tmp_path))

    assert payload["status"] == "degraded"
    assert payload["agent_driver"] == "CLAUDE_GLM"
    assert payload["agent_driver_ready"] is False
    assert payload["dependencies"]["claude_glm"] is False


def test_health_ok_when_active_driver_and_base_dependencies_ready(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_DRIVER", "CLAUDE_GLM")

    def fake_which(name: str):
        if name in {"git", "python3"}:
            return f"/usr/bin/{name}"
        return None

    def fake_call(cmd, **kwargs):
        return 0 if "claude-glm" in cmd[2] else 1

    monkeypatch.setattr("app.core.health.shutil.which", fake_which)
    monkeypatch.setattr("app.core.health.subprocess.call", fake_call)
    monkeypatch.setattr("app.core.health.select_conda_env", lambda: "")

    payload = get_health(load_settings(tmp_path))

    assert payload["status"] == "ok"
    assert payload["agent_driver"] == "CLAUDE_GLM"
    assert payload["agent_driver_ready"] is True
    assert payload["dependencies"]["claude_kimi"] is False
    assert payload["dependencies"]["claude_glm"] is True
    assert payload["dependencies"]["cursor_cli"] is False


def test_health_ok_when_active_driver_is_claude_and_available(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_DRIVER", "CLAUDE")

    def fake_which(name: str):
        if name in {"git", "python3", "claude"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr("app.core.health.shutil.which", fake_which)
    monkeypatch.setattr("app.core.health.subprocess.call", lambda *args, **kwargs: 1)
    monkeypatch.setattr("app.core.health.select_conda_env", lambda: "")

    payload = get_health(load_settings(tmp_path))

    assert payload["status"] == "ok"
    assert payload["agent_driver"] == "CLAUDE"
    assert payload["agent_driver_ready"] is True
    assert payload["dependencies"]["claude"] is True


def test_health_glm_falls_back_to_binary_check_when_shell_template_empty(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_DRIVER", "CLAUDE_GLM")
    monkeypatch.setenv("REPOPILOT_CLAUDE_GLM_SHELL_TEMPLATE", "")

    def fake_which(name: str):
        if name in {"git", "python3", "claude-glm"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr("app.core.health.shutil.which", fake_which)
    monkeypatch.setattr("app.core.health.subprocess.call", lambda *args, **kwargs: 1)
    monkeypatch.setattr("app.core.health.select_conda_env", lambda: "")

    payload = get_health(load_settings(tmp_path))

    assert payload["status"] == "ok"
    assert payload["agent_driver"] == "CLAUDE_GLM"
    assert payload["agent_driver_ready"] is True
    assert payload["dependencies"]["claude_glm"] is True
