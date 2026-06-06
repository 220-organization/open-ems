"""Backend: auto charge at Kyiv clock hour of minimum DAM price (DB), once per (day, device, low hour).

Outside the min-DAM hour, enabled devices get periodic self-consumption TOU (discharge floor) so the
battery can cover load until the next min-DAM charge window (same idea as night-charge day discharge).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app import settings
from app.deye_api import (
    assert_inverter_owned,
    apply_self_consumption_zero_export_ct,
    charge_soc_delta_then_zero_export_ct,
    deye_configured,
)
from app.deye_peak_auto_service import get_peak_auto_pref, normalize_discharge_soc_delta_pct
from app.deye_self_consumption_service import upsert_self_consumption_pref
from app.models import DeyeLowDamChargeFired, DeyeLowDamChargePref, DeyeNightChargePref
from app.oree_dam_service import KYIV, get_hourly_dam_uah_mwh

logger = logging.getLogger(__name__)

CHARGE_SOC_DELTA_PCT_ALLOWED: tuple[int, ...] = (2, 10, 20, 50, 100)


def normalize_charge_soc_delta_pct(pct: int) -> int:
    """Map legacy stored values to the nearest allowed discrete percentage."""
    if pct in CHARGE_SOC_DELTA_PCT_ALLOWED:
        return pct
    return min(CHARGE_SOC_DELTA_PCT_ALLOWED, key=lambda x: abs(x - pct))


def kyiv_local(now: datetime) -> datetime:
    """Wall clock in Europe/Kyiv regardless of server TZ."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=KYIV)
    return now.astimezone(KYIV)


def kyiv_low_dam_discharge_hour_active(now: datetime, low_hour: Optional[int]) -> bool:
    """True outside the min-DAM charge hour — battery should self-consume/discharge toward floor."""
    if low_hour is None:
        return False
    return kyiv_local(now).hour != low_hour


def low_hour_index_from_hourly_uah_mwh(hourly: list[Optional[float]]) -> Optional[int]:
    """Index 0..23 aligned with chart-day / Europe-Kyiv hour; earliest index wins ties on minimum price."""
    best_i = -1
    best_v = float("inf")
    for i, v in enumerate(hourly):
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x != x:  # NaN
            continue
        if best_i < 0 or x < best_v:
            best_v = x
            best_i = i
    return best_i if best_i >= 0 else None


async def get_low_dam_charge_pref(session: AsyncSession, device_sn: str) -> tuple[bool, int]:
    """(enabled, charge_soc_delta_pct) — defaults when row missing: False, 10."""
    sn = (device_sn or "").strip()
    if not sn:
        return False, 10
    row = await session.get(DeyeLowDamChargePref, sn)
    if not row:
        return False, 10
    pct = int(row.charge_soc_delta_pct)
    if pct not in CHARGE_SOC_DELTA_PCT_ALLOWED:
        pct = normalize_charge_soc_delta_pct(pct)
    return bool(row.enabled), pct


async def get_charge_soc_delta_stored(session: AsyncSession, device_sn: str) -> int:
    _, pct = await get_low_dam_charge_pref(session, device_sn)
    return pct


async def upsert_low_dam_charge_pref(
    session: AsyncSession,
    device_sn: str,
    enabled: bool,
    charge_soc_delta_pct: int,
) -> None:
    if charge_soc_delta_pct not in CHARGE_SOC_DELTA_PCT_ALLOWED:
        allowed = ", ".join(str(x) for x in CHARGE_SOC_DELTA_PCT_ALLOWED)
        raise ValueError(f"charge_soc_delta_pct must be one of: {allowed}")
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    stmt = (
        pg_insert(DeyeLowDamChargePref)
        .values(
            device_sn=sn,
            enabled=enabled,
            charge_soc_delta_pct=charge_soc_delta_pct,
        )
        .on_conflict_do_update(
            index_elements=["device_sn"],
            set_={
                "enabled": enabled,
                "charge_soc_delta_pct": charge_soc_delta_pct,
                "updated_on": func.now(),
            },
        )
    )
    await session.execute(stmt)


async def run_low_dam_charge_tick() -> None:
    """
    For each enabled inverter: if Kyiv hour equals DAM minimum-price hour for today (from DB), and no
    successful fire row exists for (trade_day, device_sn, low_hour), run charge and insert row.
    """
    if not settings.DEYE_LOW_DAM_CHARGE_SCHEDULER_ENABLED:
        return
    if not deye_configured():
        return

    from app.db import async_session_factory

    now = datetime.now(KYIV)
    today: date = now.date()
    kyiv_hour = now.hour
    zone = settings.OREE_COMPARE_ZONE_EIC

    async with async_session_factory() as session:
        res = await session.execute(
            select(
                DeyeLowDamChargePref.device_sn,
                DeyeLowDamChargePref.charge_soc_delta_pct,
            ).where(DeyeLowDamChargePref.enabled.is_(True))
        )
        devices = [
            (str(r[0]), normalize_charge_soc_delta_pct(int(r[1])))
            for r in res.all()
            if r[0]
        ]
        night_res = await session.execute(
            select(DeyeNightChargePref.device_sn).where(DeyeNightChargePref.enabled.is_(True))
        )
        night_charge_sns = {str(r[0]).strip() for r in night_res.all() if r[0]}
        hourly = await get_hourly_dam_uah_mwh(session, today, zone)
    if not devices:
        return

    low_idx = low_hour_index_from_hourly_uah_mwh(hourly)
    if low_idx is None:
        logger.debug("Low DAM auto: no DAM hourly data for %s", today.isoformat())
        return
    if kyiv_hour != low_idx:
        return

    for sn, delta_pct in devices:
        if sn in night_charge_sns:
            continue
        async with async_session_factory() as session:
            q = await session.execute(
                select(DeyeLowDamChargeFired).where(
                    DeyeLowDamChargeFired.trade_day == today,
                    DeyeLowDamChargeFired.device_sn == sn,
                    DeyeLowDamChargeFired.low_hour == low_idx,
                )
            )
            if q.scalar_one_or_none() is not None:
                continue

        logger.info(
            "Low DAM auto: charge starting device_sn=%s trade_day=%s low_hour=%s delta_pct=%s",
            sn,
            today.isoformat(),
            low_idx,
            delta_pct,
        )
        try:
            await charge_soc_delta_then_zero_export_ct(sn, float(delta_pct))
        except Exception:
            logger.exception("Low DAM auto: charge failed device_sn=%s", sn)
            continue

        async with async_session_factory() as session:
            session.add(
                DeyeLowDamChargeFired(
                    trade_day=today,
                    device_sn=sn,
                    low_hour=low_idx,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.warning("Low DAM auto: duplicate success row device_sn=%s", sn)
            else:
                logger.info("Low DAM auto: success recorded device_sn=%s", sn)


async def run_low_dam_day_discharge_tick() -> None:
    """Apply self-consumption TOU (discharge floor) outside min-DAM hour for low-DAM devices."""
    if not settings.DEYE_LOW_DAM_CHARGE_SCHEDULER_ENABLED:
        return
    if not deye_configured():
        return

    from app.db import async_session_factory

    now = datetime.now(KYIV)
    today: date = now.date()
    zone = settings.OREE_COMPARE_ZONE_EIC

    async with async_session_factory() as session:
        res = await session.execute(
            select(DeyeLowDamChargePref.device_sn).where(DeyeLowDamChargePref.enabled.is_(True))
        )
        devices = [str(r[0]) for r in res.all() if r[0]]
        night_res = await session.execute(
            select(DeyeNightChargePref.device_sn).where(DeyeNightChargePref.enabled.is_(True))
        )
        night_charge_sns = {str(r[0]).strip() for r in night_res.all() if r[0]}
        hourly = await get_hourly_dam_uah_mwh(session, today, zone)
    if not devices:
        return

    low_idx = low_hour_index_from_hourly_uah_mwh(hourly)
    if not kyiv_low_dam_discharge_hour_active(now, low_idx):
        return

    for sn in devices:
        if sn in night_charge_sns:
            continue
        try:
            async with async_session_factory() as session:
                _, floor_pct = await get_peak_auto_pref(session, sn)
            await apply_self_consumption_zero_export_ct(
                sn,
                tou_soc_floor_pct=float(normalize_discharge_soc_delta_pct(int(floor_pct))),
            )
            logger.debug(
                "Low DAM day discharge: self-consumption applied device_sn=%s floor_pct=%s low_hour=%s",
                sn,
                floor_pct,
                low_idx,
            )
        except Exception:
            logger.exception("Low DAM day discharge: apply failed device_sn=%s", sn)


async def set_low_dam_charge_from_ui(
    session: AsyncSession,
    device_sn: str,
    enabled: bool,
    charge_soc_delta_pct: int,
) -> None:
    """Validate ownership when enabling; upsert pref; enable self-consumption on inverter when enabling."""
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    pct = normalize_charge_soc_delta_pct(int(charge_soc_delta_pct))
    if enabled:
        await assert_inverter_owned(sn)
        if not deye_configured():
            raise RuntimeError("Deye API credentials not configured")
        await upsert_low_dam_charge_pref(session, sn, True, pct)
        await upsert_self_consumption_pref(session, sn, True)
        _, floor_pct = await get_peak_auto_pref(session, sn)
        await apply_self_consumption_zero_export_ct(
            sn,
            tou_soc_floor_pct=float(normalize_discharge_soc_delta_pct(int(floor_pct))),
        )
        logger.info("Low DAM enabled: self-consumption applied device_sn=%s floor_pct=%s", sn, floor_pct)
    else:
        await upsert_low_dam_charge_pref(session, sn, False, pct)
