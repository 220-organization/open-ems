"""Backend: auto charge during the cheapest 3 Kyiv hours around the daily DAM minimum (DB).

Find today's minimum DAM hour, scan ±3 h around it, pick the 3 consecutive hours with the lowest
total price, and start charge at the first of those hours (charge runs ~3 h). Once per (day, device,
low hour). Outside the charge window, enabled devices get periodic self-consumption TOU (discharge
floor) so the battery can cover load until the next min-DAM charge window.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
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
LOW_DAM_CHARGE_HOURS = 3
LOW_DAM_ANALYSIS_RADIUS_HOURS = 3


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


def _hourly_price_or_none(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def kyiv_low_dam_charge_window_active(
    now: datetime,
    charge_start_hour: Optional[int],
    *,
    charge_hours: int = LOW_DAM_CHARGE_HOURS,
) -> bool:
    """True during the scheduled min-DAM charge block [start, start + charge_hours)."""
    if charge_start_hour is None:
        return False
    h = kyiv_local(now).hour
    return charge_start_hour <= h < charge_start_hour + charge_hours


def kyiv_low_dam_discharge_hour_active(
    now: datetime,
    charge_start_hour: Optional[int],
    *,
    charge_hours: int = LOW_DAM_CHARGE_HOURS,
) -> bool:
    """True outside the min-DAM charge window — battery should self-consume/discharge toward floor."""
    if charge_start_hour is None:
        return False
    return not kyiv_low_dam_charge_window_active(now, charge_start_hour, charge_hours=charge_hours)


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


def low_dam_charge_plan_from_hourly(
    hourly: list[Optional[float]],
    *,
    charge_hours: int = LOW_DAM_CHARGE_HOURS,
    analysis_radius_hours: int = LOW_DAM_ANALYSIS_RADIUS_HOURS,
) -> tuple[Optional[int], Optional[int]]:
    """
    (low_hour, charge_start_hour): minimum DAM hour and first hour of the cheapest consecutive
    charge_hours block within ±analysis_radius_hours of low_hour. Earliest start wins ties.
    """
    low_hour = low_hour_index_from_hourly_uah_mwh(hourly)
    if low_hour is None:
        return None, None

    window_start = max(0, low_hour - analysis_radius_hours)
    window_end = min(23, low_hour + analysis_radius_hours)
    best_start: Optional[int] = None
    best_sum = float("inf")

    for start in range(window_start, window_end - charge_hours + 2):
        block_sum = 0.0
        valid = True
        for h in range(start, start + charge_hours):
            price = _hourly_price_or_none(hourly[h] if h < len(hourly) else None)
            if price is None:
                valid = False
                break
            block_sum += price
        if not valid:
            continue
        if best_start is None or block_sum < best_sum or (block_sum == best_sum and start < best_start):
            best_sum = block_sum
            best_start = start

    if best_start is None:
        return low_hour, low_hour
    return low_hour, best_start


def kyiv_low_dam_charge_deadline(trade_day: date, charge_start_hour: int, *, charge_hours: int = LOW_DAM_CHARGE_HOURS) -> datetime:
    """Exclusive end of the charge window in Europe/Kyiv."""
    end_hour = charge_start_hour + charge_hours
    if end_hour <= 23:
        return datetime.combine(trade_day, time(end_hour, 0), tzinfo=KYIV)
    next_day = trade_day + timedelta(days=1)
    return datetime.combine(next_day, time(end_hour - 24, 0), tzinfo=KYIV)


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
    For each enabled inverter: if Kyiv hour equals the first hour of the cheapest 3-hour DAM block
    around today's minimum (from DB), and no successful fire row exists for (trade_day, device_sn,
    low_hour), run charge and insert row.
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

    low_idx, charge_start = low_dam_charge_plan_from_hourly(hourly)
    if low_idx is None or charge_start is None:
        logger.debug("Low DAM auto: no DAM hourly data for %s", today.isoformat())
        return
    if kyiv_hour != charge_start:
        return

    charge_deadline = kyiv_low_dam_charge_deadline(today, charge_start)

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
            "Low DAM auto: charge starting device_sn=%s trade_day=%s low_hour=%s charge_start=%s delta_pct=%s deadline_kyiv=%s",
            sn,
            today.isoformat(),
            low_idx,
            charge_start,
            delta_pct,
            charge_deadline.isoformat(),
        )
        try:
            await charge_soc_delta_then_zero_export_ct(
                sn,
                float(delta_pct),
                return_after_start=True,
                deadline=charge_deadline,
            )
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

    _, charge_start = low_dam_charge_plan_from_hourly(hourly)
    if not kyiv_low_dam_discharge_hour_active(now, charge_start):
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
                "Low DAM day discharge: self-consumption applied device_sn=%s floor_pct=%s charge_start=%s",
                sn,
                floor_pct,
                charge_start,
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
