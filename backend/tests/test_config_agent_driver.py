from __future__ import annotations

from pathlib import Path

from app.config import load_settings, set_agent_driver


def test_load_settings_default_agent_driver_is_claude_kimi(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.delenv("REPOPILOT_AGENT_DRIVER", raising=False)

    settings = load_settings(tmp_path)

    assert settings.agent_driver == "CLAUDE_KIMI"


def test_load_settings_agent_driver_glm_from_env(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_DRIVER", "CLAUDE_GLM")

    settings = load_settings(tmp_path)

    assert settings.agent_driver == "CLAUDE_GLM"


def test_load_settings_agent_driver_claude_from_env(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_DRIVER", "CLAUDE")

    settings = load_settings(tmp_path)

    assert settings.agent_driver == "CLAUDE"


def test_load_settings_agent_driver_invalid_falls_back_to_claude_kimi(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_DRIVER", "INVALID_DRIVER")

    settings = load_settings(tmp_path)

    assert settings.agent_driver == "CLAUDE_KIMI"


def test_load_settings_agent_driver_command_overrides(tmp_path: Path, monkeypatch):
    set_agent_driver("")
    monkeypatch.setenv("REPOPILOT_AGENT_SHELL", "bash")
    monkeypatch.setenv("REPOPILOT_CLAUDE_CMD", "claude-raw")
    monkeypatch.setenv("REPOPILOT_CLAUDE_KIMI_CMD", "cc-kimi")
    monkeypatch.setenv("REPOPILOT_CLAUDE_GLM_CMD", "cc-glm")
    monkeypatch.setenv("REPOPILOT_CLAUDE_KIMI_SHELL_TEMPLATE", "kimi-wrapper --profile prod")
    monkeypatch.setenv("REPOPILOT_CLAUDE_GLM_SHELL_TEMPLATE", "")
    monkeypatch.setenv("REPOPILOT_CURSOR_CLI_CMD", "cursor-agent")

    settings = load_settings(tmp_path)

    assert settings.agent_shell == "bash"
    assert settings.claude_cmd == "claude-raw"
    assert settings.claude_kimi_cmd == "cc-kimi"
    assert settings.claude_glm_cmd == "cc-glm"
    assert settings.claude_kimi_shell_template == "kimi-wrapper --profile prod"
    assert settings.claude_glm_shell_template == ""
    assert settings.cursor_cli_cmd == "cursor-agent"
