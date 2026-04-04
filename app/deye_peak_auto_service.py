"""Backend: auto discharge at Kyiv clock hour of maximum DAM price (DB), once per (day, device, peak hour)."""

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
    deye_configured,
    discharge_soc_delta_then_zero_export_ct,
    fetch_soc_map_refresh,
)
from app.models import DeyePeakAutoDischargeFired, DeyePeakAutoDischargePref
from app.oree_dam_service import KYIV, get_hourly_dam_uah_mwh

logger = logging.getLogger(__name__)

_DISCHARGE_DELTA_MIN = 2
_DISCHARGE_DELTA_MAX = 40
# 100 = full discharge to ~0% (resolved to current SoC in percentage points at execution).
DISCHARGE_SOC_DELTA_PCT_ALLOWED: tuple[int, ...] = (2, 10, 20, 100)
DISCHARGE_SOC_DELTA_FULL_SENTINEL: int = 100


def normalize_discharge_soc_delta_pct(pct: int) -> int:
    """Map legacy stored values to the nearest allowed discrete percentage (2/10/20/100)."""
    if pct in DISCHARGE_SOC_DELTA_PCT_ALLOWED:
        return pct
    discrete = (2, 10, 20)
    return min(discrete, key=lambda x: abs(x - pct))


async def resolve_stored_discharge_delta_points(device_sn: str, stored_pct: int) -> float:
    """DB preference to API delta: 2/10/20 as-is; 100 = drop by current SoC (full discharge)."""
    if int(stored_pct) != DISCHARGE_SOC_DELTA_FULL_SENTINEL:
        return float(stored_pct)
    sn = (device_sn or "").strip()
    soc_map = await fetch_soc_map_refresh([sn])
    cur = soc_map.get(sn)
    if cur is None:
        raise ValueError("SOC not available from device — cannot run full discharge")
    c = float(cur)
    return float(min(100.0, max(1.0, round(c, 2))))


def peak_hour_index_from_hourly_uah_mwh(hourly: list[Optional[float]]) -> Optional[int]:
    """Index 0..23 aligned with chart-day / Europe-Kyiv hour; earliest index wins ties."""
    best_i = -1
    best_v = float("-inf")
    for i, v in enumerate(hourly):
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x != x:  # NaN
            continue
        if best_i < 0 or x > best_v:
            best_v = x
            best_i = i
    return best_i if best_i >= 0 else None


async def get_peak_auto_pref(session: AsyncSession, device_sn: str) -> tuple[bool, int]:
    """(enabled, discharge_soc_delta_pct) — defaults: False, 2. Allowed: 2, 10, 20, 100 (full)."""
    sn = (device_sn or "").strip()
    if not sn:
        return False, _DISCHARGE_DELTA_MIN
    row = await session.get(DeyePeakAutoDischargePref, sn)
    if not row:
        return False, _DISCHARGE_DELTA_MIN
    pct = int(row.discharge_soc_delta_pct)
    if pct == DISCHARGE_SOC_DELTA_FULL_SENTINEL:
        return bool(row.enabled), DISCHARGE_SOC_DELTA_FULL_SENTINEL
    pct = max(_DISCHARGE_DELTA_MIN, min(_DISCHARGE_DELTA_MAX, pct))
    pct = normalize_discharge_soc_delta_pct(pct)
    return bool(row.enabled), pct


async def get_discharge_soc_delta_stored(session: AsyncSession, device_sn: str) -> int:
    _, pct = await get_peak_auto_pref(session, device_sn)
    return pct


async def upsert_peak_auto_pref(
    session: AsyncSession,
    device_sn: str,
    enabled: bool,
    discharge_soc_delta_pct: int,
) -> None:
    if discharge_soc_delta_pct not in DISCHARGE_SOC_DELTA_PCT_ALLOWED:
        allowed = ", ".join(str(x) for x in DISCHARGE_SOC_DELTA_PCT_ALLOWED)
        raise ValueError(f"discharge_soc_delta_pct must be one of: {allowed}")
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    stmt = (
        pg_insert(DeyePeakAutoDischargePref)
        .values(
            device_sn=sn,
            enabled=enabled,
            discharge_soc_delta_pct=discharge_soc_delta_pct,
        )
        .on_conflict_do_update(
            index_elements=["device_sn"],
            set_={
                "enabled": enabled,
                "discharge_soc_delta_pct": discharge_soc_delta_pct,
                "updated_on": func.now(),
            },
        )
    )
    await session.execute(stmt)


async def run_peak_auto_discharge_tick() -> None:
    """
    For each enabled inverter: if Kyiv hour equals DAM peak hour for today (from DB), and no
    successful fire row exists for (trade_day, device_sn, peak_hour), run discharge and insert row.
    Failed discharge does not insert — next tick retries within the same hour.
    """
    if not settings.DEYE_PEAK_AUTO_DISCHARGE_SCHEDULER_ENABLED:
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
                DeyePeakAutoDischargePref.device_sn,
                DeyePeakAutoDischargePref.discharge_soc_delta_pct,
            ).where(DeyePeakAutoDischargePref.enabled.is_(True))
        )
        devices: list[tuple[str, int]] = []
        for r in res.all():
            if not r[0]:
                continue
            raw = int(r[1])
            if raw == DISCHARGE_SOC_DELTA_FULL_SENTINEL:
                devices.append((str(r[0]), DISCHARGE_SOC_DELTA_FULL_SENTINEL))
            else:
                devices.append(
                    (
                        str(r[0]),
                        normalize_discharge_soc_delta_pct(
                            max(_DISCHARGE_DELTA_MIN, min(_DISCHARGE_DELTA_MAX, raw))
                        ),
                    )
                )
        if not devices:
            return
        hourly = await get_hourly_dam_uah_mwh(session, today, zone)

    peak_idx = peak_hour_index_from_hourly_uah_mwh(hourly)
    if peak_idx is None:
        logger.debug("Peak DAM auto: no DAM hourly data for %s", today.isoformat())
        return
    if kyiv_hour != peak_idx:
        return

    for sn, delta_pct in devices:
        async with async_session_factory() as session:
            q = await session.execute(
                select(DeyePeakAutoDischargeFired).where(
                    DeyePeakAutoDischargeFired.trade_day == today,
                    DeyePeakAutoDischargeFired.device_sn == sn,
                    DeyePeakAutoDischargeFired.peak_hour == peak_idx,
                )
            )
            if q.scalar_one_or_none() is not None:
                continue

        logger.info(
            "Peak DAM auto: discharge starting device_sn=%s trade_day=%s peak_hour=%s stored_delta=%s",
            sn,
            today.isoformat(),
            peak_idx,
            delta_pct,
        )
        try:
            actual_delta = await resolve_stored_discharge_delta_points(sn, delta_pct)
            await discharge_soc_delta_then_zero_export_ct(sn, actual_delta)
        except Exception:
            logger.exception("Peak DAM auto: discharge failed device_sn=%s", sn)
            continue

        async with async_session_factory() as session:
            session.add(
                DeyePeakAutoDischargeFired(
                    trade_day=today,
                    device_sn=sn,
                    peak_hour=peak_idx,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.warning("Peak DAM auto: duplicate success row device_sn=%s", sn)
            else:
                logger.info("Peak DAM auto: success recorded device_sn=%s", sn)


async def set_peak_auto_from_ui(
    session: AsyncSession,
    device_sn: str,
    enabled: bool,
    discharge_soc_delta_pct: int,
) -> None:
    """Validate ownership when enabling; upsert pref including SoC delta %."""
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    if enabled:
        await assert_inverter_owned(sn)
    await upsert_peak_auto_pref(session, sn, enabled, discharge_soc_delta_pct)
