from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_settings
from app.config import Settings
from app.core.health import get_health
from app.models import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)):
    return get_health(settings.root_dir)
