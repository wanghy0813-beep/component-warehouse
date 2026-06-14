import os

from fastapi import Header, HTTPException, status


ACCESS_TOKEN = os.getenv("APP_ACCESS_TOKEN", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "componentwarehouse")


def auth_required() -> bool:
    return bool(ACCESS_TOKEN)


def require_access(
    authorization: str | None = Header(default=None),
    x_access_token: str | None = Header(default=None),
):
    if not auth_required():
        return

    token = x_access_token
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    if token != ACCESS_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing access token",
        )
