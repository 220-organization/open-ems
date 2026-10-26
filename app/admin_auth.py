"""Admin token auth for Open EMS moderation endpoints."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException, status

from app import settings


def consultation_admin_open() -> bool:
    """Skip the RDN consultation admin password on a local ./run-local.sh process.

    Production Compose points DATABASE_URL at the ``db`` service, not host port 5433.
    ``RDN_CONSULTATION_ADMIN_OPEN=0`` forces the password even locally.
    """
    raw = (os.environ.get("RDN_CONSULTATION_ADMIN_OPEN") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    url = os.environ.get("DATABASE_URL") or ""
    return "127.0.0.1:5433" in url or "localhost:5433" in url


def require_admin_token(token: Optional[str] = Header(None, alias="token")) -> str:
    if consultation_admin_open():
        return (token or "").strip() or "local"
    expected = (settings.OPEN_EMS_ADMIN_TOKEN or "").strip()
    provided = (token or "").strip()
    if not expected or provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return provided


def verify_admin_password(password: str) -> bool:
    expected = (settings.OPEN_EMS_ADMIN_PASSWORD or "").strip()
    return bool(expected) and (password or "").strip() == expected
