"""Persist ROI CAPEX (USD) and period start per Deye inverter (deye_roi_capex)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeyeRoiCapex


async def get_roi_capex_map_for_devices(session: AsyncSession, device_sns: list[str]) -> dict[str, float]:
    """CAPEX (USD) per device serial for inverter dropdown labels."""
    uniq = list({str(s or "").strip() for s in device_sns if s and str(s).strip()})
    if not uniq:
        return {}
    result = await session.execute(
        select(DeyeRoiCapex.device_sn, DeyeRoiCapex.capex_usd).where(DeyeRoiCapex.device_sn.in_(uniq))
    )
    return {str(r[0]): float(r[1]) for r in result.all()}


async def get_roi_capex(session: AsyncSession, device_sn: str) -> Optional[dict[str, Any]]:
    sn = (device_sn or "").strip()
    if not sn:
        return None
    res = await session.execute(select(DeyeRoiCapex).where(DeyeRoiCapex.device_sn == sn))
    row = res.scalar_one_or_none()
    if row is None:
        return None
    return {
        "capexUsd": float(row.capex_usd),
        "periodStartIso": row.period_start_at.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }


async def upsert_roi_capex(session: AsyncSession, device_sn: str, capex_usd: float) -> datetime:
    """
    Save CAPEX and set period_start_at to now (each save starts a new ROI window, same as UI).
    """
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    now = datetime.now(timezone.utc)
    stmt = pg_insert(DeyeRoiCapex).values(
        device_sn=sn,
        capex_usd=float(capex_usd),
        period_start_at=now,
        updated_on=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["device_sn"],
        set_={
            "capex_usd": stmt.excluded.capex_usd,
            "period_start_at": stmt.excluded.period_start_at,
            "updated_on": stmt.excluded.updated_on,
        },
    )
    await session.execute(stmt)
    return now
