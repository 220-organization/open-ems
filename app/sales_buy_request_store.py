"""Persist station / BESS buy requests for the admin Buy Request tab and calendar."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SalesBuyRequest

logger = logging.getLogger(__name__)

_KYIV = ZoneInfo("Europe/Kyiv")

KIND_STATION = "station"
KIND_BESS = "bess"
KIND_BESS_DISCOUNT = "bess_discount"
ALLOWED_KINDS = frozenset({KIND_STATION, KIND_BESS, KIND_BESS_DISCOUNT})


def kyiv_slot_for_now(when: Optional[datetime] = None) -> tuple[str, str]:
    """Snap to the next 10:00 / 14:00 / 18:00 Kyiv window; return (slot_id, slot_label)."""
    now = when.astimezone(_KYIV) if when is not None else datetime.now(_KYIV)
    hour = now.hour
    if hour < 12:
        window = "10:00"
    elif hour < 16:
        window = "14:00"
    else:
        window = "18:00"
    day = now.date()
    slot_id = f"{day.isoformat()}T{window}"
    slot_label = f"{day.day:02d}.{day.month:02d}.{day.year}, {window}"
    return slot_id, slot_label


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


async def save_sales_buy_request(
    db: AsyncSession,
    *,
    kind: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    title: Optional[str] = None,
    amount_label: Optional[str] = None,
    status: str = "requested",
    page_url: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    slot_id: Optional[str] = None,
    slot_label: Optional[str] = None,
) -> Optional[SalesBuyRequest]:
    kind_norm = (kind or "").strip().lower()
    if kind_norm not in ALLOWED_KINDS:
        logger.warning("Refuse sales buy request with kind=%s", kind)
        return None
    if not slot_id or not slot_label:
        slot_id, slot_label = kyiv_slot_for_now()
    now = _utcnow()
    row = SalesBuyRequest(
        id=uuid.uuid4(),
        kind=kind_norm[:32],
        name=(name or None),
        phone=(phone or None),
        slot_id=(slot_id or None),
        slot_label=(slot_label or None),
        title=(title or None),
        amount_label=(amount_label or None),
        status=(status or "requested")[:32],
        page_url=(page_url or None),
        payload=payload,
        created_on=now,
        updated_on=now,
    )
    try:
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row
    except Exception:
        logger.exception("Failed to store sales buy request kind=%s", kind_norm)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


def sales_item(row: SalesBuyRequest) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "name": row.name,
        "phone": row.phone,
        "slot_id": row.slot_id,
        "slot_label": row.slot_label,
        "title": row.title,
        "amount_label": row.amount_label,
        "status": row.status,
        "page_url": row.page_url,
        "payload": row.payload,
        "created_on": row.created_on.isoformat() if row.created_on else None,
        "calendar_group": "bess" if row.kind.startswith("bess") else "station",
    }


async def list_sales_buy_requests(db: AsyncSession, *, limit: int = 200) -> list[dict[str, Any]]:
    result = await db.execute(
        select(SalesBuyRequest).order_by(SalesBuyRequest.created_on.desc()).limit(limit)
    )
    return [sales_item(row) for row in result.scalars().all()]
