"""Auto self-consumption from DAM vs reference battery LCOE (Kyiv current hour, OREE DB)."""

from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app import settings
from app.deye_api import assert_inverter_owned, deye_configured
from app.deye_self_consumption_service import get_self_consumption_pref, set_self_consumption_from_ui
from app.models import DeyeSelfConsumptionAutoDamPref
from app.oree_dam_service import KYIV, get_hourly_dam_uah_mwh, oree_dam_configured
from app.ref_battery_lcoe import compute_reference_battery_uah_per_kwh

logger = logging.getLogger(__name__)


async def get_self_consumption_auto_dam_pref(session: AsyncSession, device_sn: str) -> bool:
    sn = (device_sn or "").strip()
    if not sn:
        return False
    row = await session.get(DeyeSelfConsumptionAutoDamPref, sn)
    return bool(row.enabled) if row else False


async def upsert_self_consumption_auto_dam_pref(
    session: AsyncSession,
    device_sn: str,
    enabled: bool,
) -> None:
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    stmt = (
        pg_insert(DeyeSelfConsumptionAutoDamPref)
        .values(device_sn=sn, enabled=enabled)
        .on_conflict_do_update(
            index_elements=["device_sn"],
            set_={"enabled": enabled, "updated_on": func.now()},
        )
    )
    await session.execute(stmt)


async def set_self_consumption_auto_dam_from_ui(
    session: AsyncSession,
    device_sn: str,
    enabled: bool,
) -> None:
    if not deye_configured():
        raise RuntimeError("Deye API credentials not configured")
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    if enabled:
        await assert_inverter_owned(sn)
    await upsert_self_consumption_auto_dam_pref(session, sn, enabled)


def _dam_uah_per_kwh_at_kyiv_hour(hourly_uah_mwh: list, kyiv_hour: int):
    if kyiv_hour < 0 or kyiv_hour > 23 or len(hourly_uah_mwh) < 24:
        return None
    raw = hourly_uah_mwh[kyiv_hour]
    if raw is None:
        return None
    try:
        x = float(raw)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x / 1000.0


async def sync_self_consumption_auto_dam_for_device(session: AsyncSession, device_sn: str) -> None:
    """
    If auto-dam pref is on and night charge is off, set self-consumption enabled iff
    current Kyiv hour DAM (UAH/kWh) > reference battery LCOE (UAH/kWh).
    """
    sn = (device_sn or "").strip()
    if not sn:
        return
    auto_row = await session.get(DeyeSelfConsumptionAutoDamPref, sn)
    if not auto_row or not bool(auto_row.enabled):
        return
    from app.deye_night_charge_service import get_night_charge_pref

    night_on, _ = await get_night_charge_pref(session, sn)
    if night_on:
        return
    if not oree_dam_configured():
        return
    lcoe = await compute_reference_battery_uah_per_kwh()
    if lcoe is None or not (lcoe > 0):
        logger.debug("Self-consumption auto DAM: no battery LCOE device_sn=%s", sn)
        return
    now = datetime.now(KYIV)
    today: date = now.date()
    h = now.hour
    zone = settings.OREE_COMPARE_ZONE_EIC
    hourly = await get_hourly_dam_uah_mwh(session, today, zone)
    dam_kwh = _dam_uah_per_kwh_at_kyiv_hour(hourly, h)
    if dam_kwh is None:
        logger.debug("Self-consumption auto DAM: no DAM for %s hour=%s", today.isoformat(), h)
        return
    want = dam_kwh > float(lcoe)
    cur = await get_self_consumption_pref(session, sn)
    if bool(cur) == want:
        return
    logger.info(
        "Self-consumption auto DAM: device_sn=%s dam_uah_per_kwh=%.4f lcoe_uah_per_kwh=%.4f -> enabled=%s",
        sn,
        dam_kwh,
        float(lcoe),
        want,
    )
    await set_self_consumption_from_ui(session, sn, want)


async def run_self_consumption_auto_dam_tick() -> None:
    if not settings.DEYE_SELF_CONSUMPTION_AUTO_DAM_SCHEDULER_ENABLED:
        return
    if not deye_configured():
        return

    from app.db import async_session_factory

    async with async_session_factory() as session:
        res = await session.execute(
            select(DeyeSelfConsumptionAutoDamPref.device_sn).where(DeyeSelfConsumptionAutoDamPref.enabled.is_(True))
        )
        sns = [str(r[0]) for r in res.all() if r[0]]
    if not sns:
        return

    for sn in sns:
        async with async_session_factory() as session:
            try:
                await sync_self_consumption_auto_dam_for_device(session, sn)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Self-consumption auto DAM: sync failed device_sn=%s", sn)
