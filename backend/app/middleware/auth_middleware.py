from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from loguru import logger

from app.config import Settings
from app.core.auth import verify_token


def _skip_auth(path: str, method: str) -> bool:
    if path == "/api/health" and method == "GET":
        return True
    if path == "/api/auth/login" and method == "POST":
        return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api"):
            return await call_next(request)
        if _skip_auth(request.url.path, request.method):
            return await call_next(request)
        if not self.settings.auth_enabled:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        if not token:
            logger.debug("Auth rejected: missing token", path=request.url.path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid authorization"},
            )
        username = verify_token(token, self.settings.auth_password)
        if not username:
            logger.debug("Auth rejected: invalid or expired token", path=request.url.path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )
        return await call_next(request)
