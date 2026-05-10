"""Self-consumption mode: battery discharges to cover home load (ZERO_EXPORT_TO_CT).

When enabled:
- Sends ZERO_EXPORT_TO_CT with TOU SoC = max(5%, user's "till SoC X%" from peak pref) so the battery
  can cover load without draining below that floor.
- Peak export (peak auto) still fires at peak hour using whatever SoC remains after self-consumption.
- After peak export completes, restores to ZERO_EXPORT_TO_CT with TOU SoC = max(5%, discharge target).
"""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.deye_api import (
    assert_inverter_owned,
    apply_self_consumption_zero_export_ct,
    deye_configured,
)
from app.deye_peak_auto_service import get_peak_auto_pref
from app.models import DeyeSelfConsumptionPref

logger = logging.getLogger(__name__)


async def get_self_consumption_pref(session: AsyncSession, device_sn: str) -> bool:
    """Return enabled flag; defaults to False when row is missing."""
    sn = (device_sn or "").strip()
    if not sn:
        return False
    row = await session.get(DeyeSelfConsumptionPref, sn)
    return bool(row.enabled) if row else False


async def upsert_self_consumption_pref(
    session: AsyncSession,
    device_sn: str,
    enabled: bool,
) -> None:
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    stmt = (
        pg_insert(DeyeSelfConsumptionPref)
        .values(device_sn=sn, enabled=enabled)
        .on_conflict_do_update(
            index_elements=["device_sn"],
            set_={"enabled": enabled, "updated_on": func.now()},
        )
    )
    await session.execute(stmt)


async def set_self_consumption_from_ui(
    session: AsyncSession,
    device_sn: str,
    enabled: bool,
) -> None:
    """Validate ownership when enabling; upsert pref; apply ZERO_EXPORT_TO_CT when enabling."""
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    if not deye_configured():
        raise RuntimeError("Deye API credentials not configured")
    if enabled:
        await assert_inverter_owned(sn)
    await upsert_self_consumption_pref(session, sn, enabled)
    if enabled:
        _, floor_pct = await get_peak_auto_pref(session, sn)
        await apply_self_consumption_zero_export_ct(sn, tou_soc_floor_pct=float(floor_pct))
