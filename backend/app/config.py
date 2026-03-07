from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_EXEC_MODE_OVERRIDE: str | None = None
_AGENT_DRIVER_OVERRIDE: str | None = None

_DEFAULT_AGENT_DRIVER = "CLAUDE_KIMI"
_ALLOWED_AGENT_DRIVERS = {"CLAUDE", "CLAUDE_KIMI", "CLAUDE_GLM", "CURSOR_CLI"}


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    repos_dir: Path
    state_dir: Path
    worktrees_dir: Path
    artifacts_dir: Path
    logs_retention_days: int = 30
    workers: int = 3
    exec_mode: str = "AGENTIC"
    agent_driver: str = _DEFAULT_AGENT_DRIVER
    agent_shell: str = "zsh"
    claude_cmd: str = "claude"
    claude_kimi_cmd: str = "claude-kimi"
    claude_glm_cmd: str = "claude-glm"
    claude_kimi_shell_template: str = "claude-kimi"
    claude_glm_shell_template: str = "claude-glm"
    cursor_cli_cmd: str = "cursor"
    auth_username: str | None = None
    auth_password: str | None = None

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_username and self.auth_password)


def get_exec_mode(settings: Settings) -> str:
    """Current exec mode: runtime override if set, else settings.exec_mode."""
    global _EXEC_MODE_OVERRIDE
    if _EXEC_MODE_OVERRIDE is not None:
        return _EXEC_MODE_OVERRIDE
    return settings.exec_mode


def set_exec_mode(mode: str) -> None:
    """Set runtime exec mode (AGENTIC or FIXED)."""
    global _EXEC_MODE_OVERRIDE
    if mode.upper() in ("AGENTIC", "FIXED"):
        _EXEC_MODE_OVERRIDE = mode.upper()
    else:
        _EXEC_MODE_OVERRIDE = None


def get_agent_driver(settings: Settings) -> str:
    """Current agent driver: runtime override if set, else settings.agent_driver."""
    global _AGENT_DRIVER_OVERRIDE
    if _AGENT_DRIVER_OVERRIDE is not None:
        return _AGENT_DRIVER_OVERRIDE
    return settings.agent_driver


def set_agent_driver(driver: str) -> None:
    """Set runtime agent driver."""
    global _AGENT_DRIVER_OVERRIDE
    normalized = (driver or "").upper().strip()
    if normalized in _ALLOWED_AGENT_DRIVERS:
        _AGENT_DRIVER_OVERRIDE = normalized
    else:
        _AGENT_DRIVER_OVERRIDE = None


def _normalize_agent_driver(raw: str | None) -> str:
    normalized = (raw or "").upper().strip()
    if normalized in _ALLOWED_AGENT_DRIVERS:
        return normalized
    return _DEFAULT_AGENT_DRIVER


def load_settings(root_dir: str | Path | None = None) -> Settings:
    if root_dir is None:
        root = Path(__file__).resolve().parents[2]
    else:
        root = Path(root_dir).resolve()

    load_dotenv(root / ".env")

    raw = os.environ.get("REPOPILOT_EXEC_MODE", "AGENTIC")
    exec_mode = "AGENTIC" if raw.upper() == "AGENTIC" else "FIXED"
    agent_driver = _normalize_agent_driver(os.environ.get("REPOPILOT_AGENT_DRIVER", _DEFAULT_AGENT_DRIVER))
    agent_shell = (os.environ.get("REPOPILOT_AGENT_SHELL", "zsh") or "zsh").strip()
    claude_cmd = (os.environ.get("REPOPILOT_CLAUDE_CMD", "claude") or "claude").strip()
    claude_kimi_cmd = (os.environ.get("REPOPILOT_CLAUDE_KIMI_CMD", "claude-kimi") or "claude-kimi").strip()
    claude_glm_cmd = (os.environ.get("REPOPILOT_CLAUDE_GLM_CMD", "claude-glm") or "claude-glm").strip()
    claude_kimi_shell_template = os.environ.get("REPOPILOT_CLAUDE_KIMI_SHELL_TEMPLATE", "claude-kimi").strip()
    claude_glm_shell_template = os.environ.get("REPOPILOT_CLAUDE_GLM_SHELL_TEMPLATE", "claude-glm").strip()
    cursor_cli_cmd = (os.environ.get("REPOPILOT_CURSOR_CLI_CMD", "cursor") or "cursor").strip()
    auth_username = os.environ.get("REPOPILOT_AUTH_USERNAME") or None
    auth_password = os.environ.get("REPOPILOT_AUTH_PASSWORD") or None

    return Settings(
        root_dir=root,
        repos_dir=root / "repos",
        state_dir=root / "state",
        worktrees_dir=root / "worktrees",
        artifacts_dir=root / "state" / "artifacts",
        exec_mode=exec_mode,
        agent_driver=agent_driver,
        agent_shell=agent_shell,
        claude_cmd=claude_cmd,
        claude_kimi_cmd=claude_kimi_cmd,
        claude_glm_cmd=claude_glm_cmd,
        claude_kimi_shell_template=claude_kimi_shell_template,
        claude_glm_shell_template=claude_glm_shell_template,
        cursor_cli_cmd=cursor_cli_cmd,
        auth_username=auth_username,
        auth_password=auth_password,
    )
