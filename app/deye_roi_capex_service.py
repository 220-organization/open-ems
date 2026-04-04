"""Persist ROI CAPEX (USD) and period start per Deye inverter (deye_roi_capex)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeyeRoiCapex

_KYIV = ZoneInfo("Europe/Kyiv")


def period_start_utc_from_kyiv_calendar_date(ymd: str) -> datetime:
    """First instant of calendar day ``YYYY-MM-DD`` in Europe/Kyiv, as UTC."""
    d = date.fromisoformat((ymd or "").strip())
    start_local = datetime.combine(d, time.min, tzinfo=_KYIV)
    return start_local.astimezone(timezone.utc)


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


async def upsert_roi_capex(
    session: AsyncSession,
    device_sn: str,
    capex_usd: float,
    *,
    period_start_at: Optional[datetime] = None,
) -> datetime:
    """
    Save CAPEX and set period_start_at (default: current UTC instant if omitted).
    """
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    now = datetime.now(timezone.utc)
    effective_start = period_start_at if period_start_at is not None else now
    stmt = pg_insert(DeyeRoiCapex).values(
        device_sn=sn,
        capex_usd=float(capex_usd),
        period_start_at=effective_start,
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
    return effective_start
