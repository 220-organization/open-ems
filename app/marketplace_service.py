"""CRUD helpers for marketplace locations and payments."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace_schemas import (
    MarketplaceLocationCreate,
    MarketplaceLocationUpdate,
    MarketplaceRequestType,
    MarketplaceStatus,
)
from app.models import MarketplaceInfoPayment, MarketplaceLocation


async def create_marketplace_location(
    db: AsyncSession, payload: MarketplaceLocationCreate
) -> MarketplaceLocation:
    row = MarketplaceLocation(
        request_type=payload.request_type.value,
        name=payload.name,
        phone=payload.phone,
        kw_available=payload.kw_available,
        distribution_contract=payload.distribution_contract,
        messenger=payload.messenger,
        locations=[loc.model_dump() for loc in payload.locations],
        parking_photos=list(payload.parking_photos or []),
        connection_point_photos=list(payload.connection_point_photos or []),
        distribution_contract_photos=list(payload.distribution_contract_photos or []),
        distance_meters=payload.distance_meters,
        price_per_kwh_extra=payload.price_per_kwh_extra,
        monthly_price_parking=payload.monthly_price_parking,
        status=MarketplaceStatus.PENDING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_public_marketplace_locations(
    db: AsyncSession,
    request_type: Optional[MarketplaceRequestType] = None,
    skip: int = 0,
    limit: int = 500,
) -> List[MarketplaceLocation]:
    query = (
        select(MarketplaceLocation)
        .where(MarketplaceLocation.status == MarketplaceStatus.PUBLISHED.value)
        .order_by(desc(MarketplaceLocation.created_on))
        .offset(skip)
        .limit(limit)
    )
    if request_type is not None:
        query = query.where(MarketplaceLocation.request_type == request_type.value)
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_pending_marketplace_locations(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 500,
) -> List[MarketplaceLocation]:
    query = (
        select(MarketplaceLocation)
        .where(MarketplaceLocation.status == MarketplaceStatus.PENDING.value)
        .order_by(desc(MarketplaceLocation.created_on))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_pending_marketplace_locations(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(MarketplaceLocation)
        .where(MarketplaceLocation.status == MarketplaceStatus.PENDING.value)
    )
    return int(result.scalar_one() or 0)


async def list_admin_marketplace_locations(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 1000,
) -> List[MarketplaceLocation]:
    query = (
        select(MarketplaceLocation)
        .order_by(desc(MarketplaceLocation.created_on))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_marketplace_location(db: AsyncSession, row_id: UUID) -> Optional[MarketplaceLocation]:
    result = await db.execute(select(MarketplaceLocation).where(MarketplaceLocation.id == row_id))
    return result.scalar_one_or_none()


async def update_marketplace_location(
    db: AsyncSession, row_id: UUID, payload: MarketplaceLocationUpdate
) -> Optional[MarketplaceLocation]:
    row = await get_marketplace_location(db, row_id)
    if row is None:
        return None
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return row
    if "status" in updates and updates["status"] is not None:
        status_val = updates["status"]
        row.status = status_val.value if hasattr(status_val, "value") else status_val
    for field in (
        "name",
        "phone",
        "kw_available",
        "distribution_contract",
        "distance_meters",
        "price_per_kwh_extra",
        "monthly_price_parking",
    ):
        if field in updates:
            setattr(row, field, updates[field])
    await db.commit()
    await db.refresh(row)
    return row


async def delete_marketplace_location(db: AsyncSession, row_id: UUID) -> Optional[MarketplaceLocation]:
    row = await get_marketplace_location(db, row_id)
    if row is None:
        return None
    await db.delete(row)
    await db.commit()
    return row


async def increment_marketplace_view_count(
    db: AsyncSession, row_id: UUID
) -> Optional[MarketplaceLocation]:
    row = await get_marketplace_location(db, row_id)
    if row is None or row.status != MarketplaceStatus.PUBLISHED.value:
        return None
    row.view_count = int(row.view_count or 0) + 1
    await db.commit()
    await db.refresh(row)
    return row


async def create_marketplace_info_payment(
    db: AsyncSession,
    *,
    payment_id: UUID,
    location_id: Optional[UUID],
    invoice_id: str,
    amount_cents: int,
    client_ui_id: Optional[str] = None,
    payment_kind: str = "location_info",
) -> MarketplaceInfoPayment:
    row = MarketplaceInfoPayment(
        id=payment_id,
        location_id=location_id,
        payment_kind=payment_kind,
        invoice_id=invoice_id,
        amount_cents=amount_cents,
        status="CREATED",
        client_ui_id=client_ui_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_marketplace_info_payment(
    db: AsyncSession, payment_id: UUID
) -> Optional[MarketplaceInfoPayment]:
    result = await db.execute(
        select(MarketplaceInfoPayment).where(MarketplaceInfoPayment.id == payment_id)
    )
    return result.scalar_one_or_none()


async def get_marketplace_info_payment_by_invoice(
    db: AsyncSession, invoice_id: str
) -> Optional[MarketplaceInfoPayment]:
    result = await db.execute(
        select(MarketplaceInfoPayment).where(MarketplaceInfoPayment.invoice_id == invoice_id)
    )
    return result.scalar_one_or_none()


async def update_marketplace_info_payment_status(
    db: AsyncSession, payment_id: UUID, status: str
) -> Optional[MarketplaceInfoPayment]:
    row = await get_marketplace_info_payment(db, payment_id)
    if row is None:
        return None
    row.status = status
    await db.commit()
    await db.refresh(row)
    return row
