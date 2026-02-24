from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_settings
from app.config import Settings
from app.core.logging_setup import tail_file

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/backend")
def get_backend_logs(
    lines: int = Query(default=200, ge=1, le=2000),
    settings: Settings = Depends(get_settings),
):
    log_path = Path(settings.state_dir) / "logs" / "backend.log"
    content = tail_file(log_path, lines=lines)
    return {
        "path": str(log_path),
        "lines": len(content),
        "content": content,
    }
