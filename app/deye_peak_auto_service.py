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
from app.deye_discharge_export_parse import parse_discharge_export_session_times
from app.deye_sample_metrics import sum_grid_export_kwh_between
from app.models import DeyePeakAutoDischargeFired, DeyePeakAutoDischargePref, DeyeSelfConsumptionPref
from app.oree_dam_service import KYIV, get_hourly_dam_uah_mwh

logger = logging.getLogger(__name__)

# Stored column ``discharge_soc_delta_pct`` holds target SoC % (floor after discharge), not a delta.
DISCHARGE_TARGET_SOC_PCT_ALLOWED: tuple[int, ...] = (5, 10, 20, 50, 80)
_LEGACY_TO_TARGET: dict[int, int] = {2: 80, 10: 50, 20: 20, 100: 5}


def normalize_discharge_soc_delta_pct(pct: int) -> int:
    """Map stored / legacy values to an allowed target SoC % (5, 10, 20, 50, 80)."""
    p = int(pct)
    if p in DISCHARGE_TARGET_SOC_PCT_ALLOWED:
        return p
    if p in _LEGACY_TO_TARGET:
        return _LEGACY_TO_TARGET[p]
    return min(DISCHARGE_TARGET_SOC_PCT_ALLOWED, key=lambda x: abs(x - p))


async def resolve_stored_discharge_delta_points(device_sn: str, stored_target_soc_pct: int) -> float:
    """Resolve stored target SoC % to discharge delta (percentage points) from current cloud SoC."""
    target = float(normalize_discharge_soc_delta_pct(int(stored_target_soc_pct)))
    sn = (device_sn or "").strip()
    soc_map = await fetch_soc_map_refresh([sn])
    cur = soc_map.get(sn)
    if cur is None:
        raise ValueError("SOC not available from device — cannot run discharge")
    c = float(cur)
    delta = c - target
    if delta < 1.0:
        raise ValueError(
            f"SoC {c:.1f}% is already at or below target {target:.0f}% — nothing to discharge by that target"
        )
    return float(min(100.0, max(1.0, round(delta, 2))))


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
    """(enabled, discharge_soc_delta_pct) — defaults: False, 80. Stored value is target SoC % (5..80)."""
    sn = (device_sn or "").strip()
    if not sn:
        return False, 80
    row = await session.get(DeyePeakAutoDischargePref, sn)
    if not row:
        return False, 80
    pct = normalize_discharge_soc_delta_pct(int(row.discharge_soc_delta_pct))
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
    p = normalize_discharge_soc_delta_pct(int(discharge_soc_delta_pct))
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    stmt = (
        pg_insert(DeyePeakAutoDischargePref)
        .values(
            device_sn=sn,
            enabled=enabled,
            discharge_soc_delta_pct=p,
        )
        .on_conflict_do_update(
            index_elements=["device_sn"],
            set_={
                "enabled": enabled,
                "discharge_soc_delta_pct": p,
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
            devices.append((str(r[0]), normalize_discharge_soc_delta_pct(raw)))
        if not devices:
            return
        hourly = await get_hourly_dam_uah_mwh(session, today, zone)

    peak_idx = peak_hour_index_from_hourly_uah_mwh(hourly)
    if peak_idx is None:
        logger.debug("Peak DAM auto: no DAM hourly data for %s", today.isoformat())
        return
    if kyiv_hour != peak_idx:
        return

    for sn, target_soc_pct in devices:
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

        async with async_session_factory() as session:
            sc_row = await session.get(DeyeSelfConsumptionPref, sn)
            self_consumption = bool(sc_row.enabled) if sc_row else False

        logger.info(
            "Peak DAM auto: discharge starting device_sn=%s trade_day=%s peak_hour=%s target_soc_pct=%s self_consumption=%s",
            sn,
            today.isoformat(),
            peak_idx,
            target_soc_pct,
            self_consumption,
        )
        try:
            actual_delta = await resolve_stored_discharge_delta_points(sn, target_soc_pct)
            discharge_result = await discharge_soc_delta_then_zero_export_ct(
                sn, actual_delta, self_consumption=self_consumption
            )
        except Exception:
            logger.exception("Peak DAM auto: discharge failed device_sn=%s", sn)
            continue

        t_start, t_end, hit_target = parse_discharge_export_session_times(discharge_result)
        export_kwh: Optional[float] = None
        if t_start is not None and t_end is not None:
            try:
                async with async_session_factory() as session:
                    export_kwh = await sum_grid_export_kwh_between(session, sn, t_start, t_end)
            except Exception:
                logger.exception("Peak DAM auto: export kWh sum failed device_sn=%s", sn)

        async with async_session_factory() as session:
            session.add(
                DeyePeakAutoDischargeFired(
                    trade_day=today,
                    device_sn=sn,
                    peak_hour=peak_idx,
                    export_session_start_at=t_start,
                    export_session_end_at=t_end,
                    export_session_kwh=export_kwh,
                    peak_discharge_hit_target=hit_target,
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
