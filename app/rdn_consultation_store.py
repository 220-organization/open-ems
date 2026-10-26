"""Persist RDN consultation payments and callbacks for the admin tab."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RdnConsultation

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def save_consultation(
    db: AsyncSession,
    *,
    kind: str,
    status: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    slot_id: Optional[str] = None,
    slot_label: Optional[str] = None,
    description: Optional[str] = None,
    amount_uah: Optional[int] = None,
    invoice_id: Optional[str] = None,
    payment_id: Optional[str] = None,
) -> None:
    now = _utcnow()
    row = RdnConsultation(
        id=uuid.uuid4(),
        kind=kind[:16],
        name=(name or None),
        phone=(phone or None),
        slot_id=(slot_id or None),
        slot_label=(slot_label or None),
        description=(description or None),
        amount_uah=amount_uah,
        status=(status or "created")[:32],
        invoice_id=(invoice_id or None),
        payment_id=(payment_id or None),
        created_on=now,
        updated_on=now,
    )
    try:
        db.add(row)
        await db.commit()
    except Exception:
        logger.exception("Failed to store RDN consultation kind=%s", kind)
        await _rollback(db)


async def update_consultation_status(
    db: AsyncSession,
    *,
    status: str,
    payment_id: Optional[str] = None,
    invoice_id: Optional[str] = None,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    slot_id: Optional[str] = None,
    slot_label: Optional[str] = None,
    description: Optional[str] = None,
) -> None:
    payment_id = (payment_id or "").strip() or None
    invoice_id = (invoice_id or "").strip() or None
    if not payment_id and not invoice_id:
        return
    clauses = []
    if payment_id:
        clauses.append(RdnConsultation.payment_id == payment_id)
    if invoice_id:
        clauses.append(RdnConsultation.invoice_id == invoice_id)
    try:
        result = await db.execute(
            select(RdnConsultation)
            .where(or_(*clauses))
            .order_by(RdnConsultation.created_on.desc())
        )
        row = result.scalars().first()
        if row is None:
            return
        row.status = (status or row.status)[:32]
        row.updated_on = _utcnow()
        if name:
            row.name = name
        if phone:
            row.phone = phone
        if slot_id:
            row.slot_id = slot_id
        if slot_label:
            row.slot_label = slot_label
        if description:
            row.description = description
        await db.commit()
    except Exception:
        logger.exception("Failed to update RDN consultation status")
        await _rollback(db)


async def list_consultations(db: AsyncSession, *, limit: int = 200) -> list[dict[str, Any]]:
    result = await db.execute(
        select(RdnConsultation).order_by(RdnConsultation.created_on.desc()).limit(limit)
    )
    items: list[dict[str, Any]] = []
    for row in result.scalars().all():
        items.append(_consultation_item(row))
    return items


def _blank(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text or None


async def create_consultation_admin(
    db: AsyncSession,
    *,
    kind: str,
    status: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    slot_label: Optional[str] = None,
    description: Optional[str] = None,
    amount_uah: Optional[int] = None,
) -> dict[str, Any]:
    now = _utcnow()
    row = RdnConsultation(
        id=uuid.uuid4(),
        kind=kind[:16],
        name=_blank(name),
        phone=_blank(phone),
        slot_label=_blank(slot_label),
        description=_blank(description),
        amount_uah=amount_uah,
        status=(status or "created")[:32],
        created_on=now,
        updated_on=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _consultation_item(row)


async def update_consultation_admin(
    db: AsyncSession,
    row_id: str,
    **fields: Any,
) -> Optional[dict[str, Any]]:
    try:
        parsed = uuid.UUID(row_id)
    except ValueError:
        return None
    result = await db.execute(select(RdnConsultation).where(RdnConsultation.id == parsed))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if "kind" in fields and fields["kind"]:
        row.kind = str(fields["kind"])[:16]
    if "status" in fields and fields["status"]:
        row.status = str(fields["status"])[:32]
    if "name" in fields:
        row.name = _blank(fields["name"])
    if "phone" in fields:
        row.phone = _blank(fields["phone"])
    if "slot_label" in fields:
        row.slot_label = _blank(fields["slot_label"])
    if "description" in fields:
        row.description = _blank(fields["description"])
    if "amount_uah" in fields:
        row.amount_uah = fields["amount_uah"]
    row.updated_on = _utcnow()
    await db.commit()
    await db.refresh(row)
    return _consultation_item(row)


async def delete_consultation_admin(db: AsyncSession, row_id: str) -> bool:
    try:
        parsed = uuid.UUID(row_id)
    except ValueError:
        return False
    result = await db.execute(select(RdnConsultation).where(RdnConsultation.id == parsed))
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


def _consultation_item(row: RdnConsultation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "name": row.name,
        "phone": row.phone,
        "slot_label": row.slot_label,
        "description": row.description,
        "amount_uah": row.amount_uah,
        "status": row.status,
        "created_on": row.created_on,
    }


async def _rollback(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        logger.exception("RDN consultation rollback failed")
