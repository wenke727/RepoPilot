from __future__ import annotations

import time

import jwt

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24


def create_token(username: str, secret: str) -> str:
    payload = {
        "sub": username,
        "exp": int(time.time()) + JWT_EXPIRY_HOURS * 3600,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_token(token: str, secret: str) -> str | None:
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
