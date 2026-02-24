from __future__ import annotations

import shutil
from pathlib import Path

from app.core.env import select_conda_env


def get_health(root_dir: Path) -> dict:
    deps = {
        "claude": shutil.which("claude") is not None,
        "git": shutil.which("git") is not None,
        "python3": shutil.which("python3") is not None,
        "node": shutil.which("node") is not None,
        "npm": shutil.which("npm") is not None,
        "gh": shutil.which("gh") is not None,
        "conda": shutil.which("conda") is not None,
    }
    selected = select_conda_env() or "none"
    status = "ok" if deps["claude"] and deps["git"] and deps["python3"] else "degraded"

    return {
        "status": status,
        "python_env_selected": selected,
        "dependencies": deps,
        "paths": {
            "root": str(root_dir),
            "repos": str(root_dir / "repos"),
            "state": str(root_dir / "state"),
            "worktrees": str(root_dir / "worktrees"),
        },
    }
