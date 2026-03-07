from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_settings
from app.config import Settings, get_agent_driver, get_exec_mode, set_agent_driver, set_exec_mode
from app.models import AgentDriver, ExecMode
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings", tags=["settings"])

SUPPORTED_AGENT_DRIVERS = [AgentDriver.CLAUDE.value, AgentDriver.CLAUDE_KIMI.value, AgentDriver.CLAUDE_GLM.value]
RESERVED_AGENT_DRIVERS = [AgentDriver.CURSOR_CLI.value]


def _agent_driver_response(settings: Settings) -> dict:
    return {
        "agent_driver": get_agent_driver(settings),
        "supported": SUPPORTED_AGENT_DRIVERS,
        "reserved": RESERVED_AGENT_DRIVERS,
    }


@router.get("/exec-mode", response_model=dict)
def get_exec_mode_endpoint(settings: Settings = Depends(get_settings)):
    return {"exec_mode": get_exec_mode(settings)}


class ExecModeUpdateBody(BaseModel):
    exec_mode: ExecMode


@router.put("/exec-mode", response_model=dict)
def put_exec_mode(payload: ExecModeUpdateBody, settings: Settings = Depends(get_settings)):
    set_exec_mode(payload.exec_mode.value)
    return {"exec_mode": get_exec_mode(settings)}


class AgentDriverUpdateBody(BaseModel):
    agent_driver: AgentDriver


@router.get("/agent-driver", response_model=dict)
def get_agent_driver_endpoint(settings: Settings = Depends(get_settings)):
    return _agent_driver_response(settings)


@router.put("/agent-driver", response_model=dict)
def put_agent_driver(payload: AgentDriverUpdateBody, settings: Settings = Depends(get_settings)):
    if payload.agent_driver == AgentDriver.CURSOR_CLI:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "DRIVER_RESERVED_NOT_IMPLEMENTED",
                "message": "CURSOR_CLI is reserved and not implemented",
            },
        )
    set_agent_driver(payload.agent_driver.value)
    return _agent_driver_response(settings)
