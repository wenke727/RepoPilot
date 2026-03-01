from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel

from app.api.deps import get_settings
from app.config import Settings
from app.core.auth import create_token

router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool
    token: str | None = None


@router.post("/auth/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
):
    if not settings.auth_enabled:
        logger.debug("Login called but auth disabled, returning ok")
        return LoginResponse(ok=True, token=None)
    if body.username != settings.auth_username or body.password != settings.auth_password:
        logger.warning("Login failed", username=body.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_token(body.username, settings.auth_password)
    logger.info("Login success", username=body.username)
    return LoginResponse(ok=True, token=token)
