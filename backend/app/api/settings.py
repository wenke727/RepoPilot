from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_settings
from app.config import Settings, get_exec_mode, set_exec_mode
from app.models import ExecMode
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/exec-mode", response_model=dict)
def get_exec_mode_endpoint(settings: Settings = Depends(get_settings)):
    return {"exec_mode": get_exec_mode(settings)}


class ExecModeUpdateBody(BaseModel):
    exec_mode: ExecMode


@router.put("/exec-mode", response_model=dict)
def put_exec_mode(payload: ExecModeUpdateBody, settings: Settings = Depends(get_settings)):
    set_exec_mode(payload.exec_mode.value)
    return {"exec_mode": get_exec_mode(settings)}
