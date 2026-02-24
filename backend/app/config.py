from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    repos_dir: Path
    state_dir: Path
    worktrees_dir: Path
    artifacts_dir: Path
    logs_retention_days: int = 30
    workers: int = 3


def load_settings(root_dir: str | Path | None = None) -> Settings:
    if root_dir is None:
        root = Path(__file__).resolve().parents[2]
    else:
        root = Path(root_dir).resolve()

    return Settings(
        root_dir=root,
        repos_dir=root / "repos",
        state_dir=root / "state",
        worktrees_dir=root / "worktrees",
        artifacts_dir=root / "state" / "artifacts",
    )
