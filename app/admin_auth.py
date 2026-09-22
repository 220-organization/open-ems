"""Admin token auth for Open EMS moderation endpoints."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app import settings


def require_admin_token(token: str | None = Header(None, alias="token")) -> str:
    expected = (settings.OPEN_EMS_ADMIN_TOKEN or "").strip()
    provided = (token or "").strip()
    if not expected or provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return provided


def verify_admin_password(password: str) -> bool:
    expected = (settings.OPEN_EMS_ADMIN_PASSWORD or "").strip()
    return bool(expected) and (password or "").strip() == expected
