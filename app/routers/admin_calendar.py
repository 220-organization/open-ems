"""Public ICS feed and the Google Calendar subscribe link for /admin."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_auth import require_admin_token
from app.admin_calendar_ics import (
    build_ics,
    calendar_feed_token_ok,
    feed_url,
    google_subscribe_url,
    public_origin,
)
from app.db import get_db
from app.rdn_consultation_store import list_consultations
from app.sales_buy_request_store import list_sales_buy_requests

router = APIRouter(tags=["admin-calendar"])


@router.get("/api/admin/calendar/google")
async def admin_calendar_google(
    _auth: str = Depends(require_admin_token),
) -> dict[str, str]:
    feed = feed_url()
    return {"feed_url": feed, "google_url": google_subscribe_url(feed)}


@router.api_route("/api/admin/calendar.ics", methods=["GET", "HEAD"])
async def admin_calendar_ics(
    token: str = "",
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not calendar_feed_token_ok(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
    consultations = await list_consultations(db, limit=500)
    buys = await list_sales_buy_requests(db, limit=500)
    items: list[dict[str, Any]] = [
        {**row, "source": "consultation", "calendar_group": "consultation"} for row in consultations
    ]
    items.extend({**row, "source": "buy"} for row in buys)
    body = build_ics(items, admin_url=f"{public_origin()}/admin")
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="220-km-admin.ics"',
            "Cache-Control": "no-cache",
        },
    )
