from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_EXEC_MODE_OVERRIDE: str | None = None


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


def load_settings(root_dir: str | Path | None = None) -> Settings:
    if root_dir is None:
        root = Path(__file__).resolve().parents[2]
    else:
        root = Path(root_dir).resolve()

    raw = os.environ.get("REPOPILOT_EXEC_MODE", "AGENTIC")
    exec_mode = "AGENTIC" if raw.upper() == "AGENTIC" else "FIXED"

    return Settings(
        root_dir=root,
        repos_dir=root / "repos",
        state_dir=root / "state",
        worktrees_dir=root / "worktrees",
        artifacts_dir=root / "state" / "artifacts",
        exec_mode=exec_mode,
    )
