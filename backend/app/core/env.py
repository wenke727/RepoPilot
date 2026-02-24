from __future__ import annotations

import shutil
import subprocess


def has_command(name: str) -> bool:
    return shutil.which(name) is not None


def select_conda_env(preferred: str = "dl2", fallback: str = "base") -> str:
    if not has_command("conda"):
        return ""
    try:
        out = subprocess.check_output(["conda", "env", "list"], text=True)
    except Exception:
        return ""

    envs = set()
    for raw in out.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        env_name = line.split()[0]
        if env_name == "*":
            continue
        envs.add(env_name)

    if preferred in envs:
        return preferred
    if fallback in envs:
        return fallback
    return ""


def conda_run_prefix(selected_env: str) -> list[str]:
    if not selected_env:
        return []
    return ["conda", "run", "-n", selected_env]
