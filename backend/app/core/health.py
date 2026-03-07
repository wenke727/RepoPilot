from __future__ import annotations

import shlex
import subprocess
import shutil

from app.config import Settings, get_agent_driver
from app.core.env import select_conda_env


def _first_token(template: str) -> str:
    raw = (template or "").strip()
    if not raw:
        return ""
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return ""
    return tokens[0] if tokens else ""


def _shell_resolves_command(shell: str, cmd: str) -> bool:
    shell_name = (shell or "zsh").strip() or "zsh"
    if not cmd:
        return False
    quoted = shlex.quote(cmd)
    try:
        rc = subprocess.call(
            [shell_name, "-ic", f"command -v {quoted} >/dev/null 2>&1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return rc == 0


def _driver_shell_dependency(shell: str, template: str, fallback_cmd: str) -> bool:
    cmd = _first_token(template)
    if cmd:
        return _shell_resolves_command(shell, cmd)
    return shutil.which(fallback_cmd) is not None


def get_health(settings: Settings) -> dict:
    shell = settings.agent_shell
    deps = {
        "claude": shutil.which(settings.claude_cmd) is not None,
        "claude_kimi": _driver_shell_dependency(shell, settings.claude_kimi_shell_template, settings.claude_kimi_cmd),
        "claude_glm": _driver_shell_dependency(shell, settings.claude_glm_shell_template, settings.claude_glm_cmd),
        "cursor_cli": shutil.which(settings.cursor_cli_cmd) is not None,
        "git": shutil.which("git") is not None,
        "python3": shutil.which("python3") is not None,
        "node": shutil.which("node") is not None,
        "npm": shutil.which("npm") is not None,
        "gh": shutil.which("gh") is not None,
        "conda": shutil.which("conda") is not None,
    }
    driver = get_agent_driver(settings)
    if driver == "CLAUDE":
        driver_ready = deps["claude"]
    elif driver == "CLAUDE_KIMI":
        driver_ready = deps["claude_kimi"]
    elif driver == "CLAUDE_GLM":
        driver_ready = deps["claude_glm"]
    elif driver == "CURSOR_CLI":
        driver_ready = deps["cursor_cli"]
    else:
        driver_ready = False

    selected = select_conda_env() or "none"
    status = "ok" if deps["git"] and deps["python3"] and driver_ready else "degraded"

    return {
        "status": status,
        "python_env_selected": selected,
        "agent_driver": driver,
        "agent_driver_ready": driver_ready,
        "dependencies": deps,
        "paths": {
            "root": str(settings.root_dir),
            "repos": str(settings.root_dir / "repos"),
            "state": str(settings.root_dir / "state"),
            "worktrees": str(settings.root_dir / "worktrees"),
        },
    }
