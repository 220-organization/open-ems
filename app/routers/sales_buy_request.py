"""Admin CRUD for unified sales buy requests (station / BESS)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_auth import require_admin_token
from app.db import get_db
from app.models import SalesBuyRequest
from app.sales_buy_request_store import (
    ALLOWED_KINDS,
    KIND_BESS,
    KIND_BESS_DISCOUNT,
    KIND_STATION,
    kyiv_slot_for_now,
    list_sales_buy_requests,
    sales_item,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sales-buy-request", tags=["sales-buy-request"])


class SalesBuyRequestList(BaseModel):
    items: list[dict[str, Any]]


class SalesBuyRequestWrite(BaseModel):
    kind: str = Field(..., description="station | bess | bess_discount")
    name: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)
    slot_label: Optional[str] = Field(None, max_length=64)
    title: Optional[str] = Field(None, max_length=400)
    amount_label: Optional[str] = Field(None, max_length=80)
    status: str = Field("requested", max_length=32)
    page_url: Optional[str] = Field(None, max_length=2000)
    payload: Optional[dict[str, Any]] = None


def _norm_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    if k not in ALLOWED_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {sorted(ALLOWED_KINDS)}",
        )
    return k


def _slot_from_label(label: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    text = (label or "").strip()
    if not text:
        return kyiv_slot_for_now()
    # Prefer existing consultation format DD.MM.YYYY, HH:MM
    import re

    match = re.match(
        r"^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[,\s]+(\d{1,2}):(\d{2}))?",
        text,
    )
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        hour = int(match.group(4) or 14)
        minute = int(match.group(5) or 0)
        window = f"{hour:02d}:{minute:02d}"
        slot_id = f"{year:04d}-{month:02d}-{day:02d}T{window}"
        slot_label = f"{day:02d}.{month:02d}.{year}, {window}"
        return slot_id, slot_label
    slot_id, slot_label = kyiv_slot_for_now()
    return slot_id, text or slot_label


@router.get("/admin", response_model=SalesBuyRequestList)
async def list_admin(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
) -> SalesBuyRequestList:
    items = await list_sales_buy_requests(db)
    return SalesBuyRequestList(items=items)


@router.post("/admin", response_model=dict, status_code=201)
async def create_admin(
    payload: SalesBuyRequestWrite,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
) -> dict[str, Any]:
    kind = _norm_kind(payload.kind)
    slot_id, slot_label = _slot_from_label(payload.slot_label)
    now = datetime.now(timezone.utc)
    row = SalesBuyRequest(
        id=uuid.uuid4(),
        kind=kind,
        name=(payload.name or "").strip() or None,
        phone=(payload.phone or "").strip() or None,
        slot_id=slot_id,
        slot_label=slot_label,
        title=(payload.title or "").strip() or None,
        amount_label=(payload.amount_label or "").strip() or None,
        status=(payload.status or "requested").strip()[:32] or "requested",
        page_url=(payload.page_url or "").strip() or None,
        payload=payload.payload,
        created_on=now,
        updated_on=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return sales_item(row)


@router.put("/admin/{request_id}", response_model=dict)
async def update_admin(
    request_id: str,
    payload: SalesBuyRequestWrite,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
) -> dict[str, Any]:
    try:
        parsed = uuid.UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    row = await db.get(SalesBuyRequest, parsed)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    kind = _norm_kind(payload.kind)
    slot_id, slot_label = _slot_from_label(payload.slot_label)
    row.kind = kind
    row.name = (payload.name or "").strip() or None
    row.phone = (payload.phone or "").strip() or None
    row.slot_id = slot_id
    row.slot_label = slot_label
    row.title = (payload.title or "").strip() or None
    row.amount_label = (payload.amount_label or "").strip() or None
    row.status = (payload.status or row.status).strip()[:32] or row.status
    row.page_url = (payload.page_url or "").strip() or None
    row.payload = payload.payload
    row.updated_on = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return sales_item(row)


@router.delete("/admin/{request_id}", status_code=204)
async def delete_admin(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
) -> None:
    try:
        parsed = uuid.UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    row = await db.get(SalesBuyRequest, parsed)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(row)
    await db.commit()


# Re-export kind constants for other modules / tests
__all__ = [
    "router",
    "KIND_STATION",
    "KIND_BESS",
    "KIND_BESS_DISCOUNT",
]
