"""Smart-load automation: PV vs Smart Load compare, Gen port On Grid always on."""

from __future__ import annotations

import logging
import math
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app import settings
from app.db import async_session_factory
from app.deye_api import (
    assert_inverter_owned,
    deye_configured,
    fetch_smart_load_live_metrics,
    get_inverter_station_coordinates,
    set_gen_port_on_grid_always_on,
)
from app.deye_smart_load_state import (
    bump_pv_below_streak,
    clear_device_state,
    clear_pending_probe_check,
    consume_pending_probe_check,
    get_gen_on_grid_always_on,
    kyiv_now,
    mark_hourly_probe_started,
    record_hourly_sample,
    reset_pv_below_streak,
    set_gen_on_grid_always_on as set_gen_state,
    should_run_hourly_probe,
    yesterday_hour_all_pv_below,
)
from app.models import DeyeSmartLoadPref
from app.solar_forecast_open_meteo import (
    fetch_hourly_insolation_by_day,
    fetch_today_tomorrow_insolation_forecast,
)

logger = logging.getLogger(__name__)


def _finite_positive(w: Optional[float]) -> bool:
    if w is None:
        return False
    try:
        x = float(w)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x) and x >= 0


def pv_below_sl(pv_w: Optional[float], sl_w: Optional[float], *, min_sl_w: int) -> Optional[bool]:
    """True when PV < Smart Load; None when comparison not possible."""
    if not _finite_positive(sl_w) or float(sl_w) < float(min_sl_w):
        return None
    if not _finite_positive(pv_w):
        return None
    return float(pv_w) < float(sl_w)


async def get_smart_load_pref(session: AsyncSession, device_sn: str) -> bool:
    sn = (device_sn or "").strip()
    if not sn:
        return False
    row = await session.get(DeyeSmartLoadPref, sn)
    return bool(row.enabled) if row else False


async def upsert_smart_load_pref(session: AsyncSession, device_sn: str, enabled: bool) -> None:
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    stmt = (
        pg_insert(DeyeSmartLoadPref)
        .values(device_sn=sn, enabled=enabled)
        .on_conflict_do_update(
            index_elements=["device_sn"],
            set_={"enabled": enabled, "updated_on": func.now()},
        )
    )
    await session.execute(stmt)


async def set_smart_load_from_ui(session: AsyncSession, device_sn: str, enabled: bool) -> None:
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    if not deye_configured():
        raise RuntimeError("Deye API credentials not configured")
    if enabled:
        await assert_inverter_owned(sn)
    await upsert_smart_load_pref(session, sn, enabled)
    if not enabled:
        clear_device_state(sn)


async def _sync_gen_state_from_device(sn: str) -> Optional[bool]:
    """In-memory gen port state only — avoid customControl read (conflicts with writes)."""
    return get_gen_on_grid_always_on(sn)


async def _apply_gen_on_grid(sn: str, enabled: bool) -> None:
    await set_gen_port_on_grid_always_on(sn, enabled)
    set_gen_state(sn, enabled)


async def _forecast_allows_probe(sn: str, kyiv_hour: int) -> bool:
    lat, lon = await get_inverter_station_coordinates(sn)
    if lat is None or lon is None:
        return True
    daily = await fetch_today_tomorrow_insolation_forecast(lat, lon)
    if daily is not None:
        today_pct = (daily.get("today") or {}).get("insolationPct")
        if today_pct is not None and int(today_pct) < settings.DEYE_SMART_LOAD_FORECAST_SKIP_INSOLATION_PCT:
            return False
    hourly = await fetch_hourly_insolation_by_day(lat, lon)
    if hourly is None:
        return True
    today = hourly.get("today")
    if not isinstance(today, dict):
        return True
    hours = today.get("hours")
    if not isinstance(hours, list):
        return True
    threshold = float(settings.DEYE_SMART_LOAD_FORECAST_SKIP_INSOLATION_PCT)
    for row in hours:
        if not isinstance(row, dict):
            continue
        if int(row.get("hour", -1)) != kyiv_hour:
            continue
        level = row.get("level")
        if level is None:
            return True
        try:
            return float(level) >= threshold
        except (TypeError, ValueError):
            return True
    return True


async def _process_device_tick(sn: str) -> None:
    min_sl = int(settings.DEYE_SMART_LOAD_MIN_SL_W)
    streak_need = int(settings.DEYE_SMART_LOAD_PV_BELOW_STREAK)
    now = kyiv_now()
    kyiv_date = now.date()
    kyiv_hour = now.hour

    pv_w, sl_w, gen_w = await fetch_smart_load_live_metrics(sn)
    below = pv_below_sl(pv_w, sl_w, min_sl_w=min_sl)
    if below is not None:
        record_hourly_sample(sn, now, below)

    if consume_pending_probe_check(sn):
        if below is False:
            current = get_gen_on_grid_always_on(sn)
            if current is not False:
                try:
                    await _apply_gen_on_grid(sn, False)
                    logger.info(
                        "Smart-load probe: solar covers SL — On Grid always on OFF sn=%s pv=%s sl=%s",
                        sn,
                        pv_w,
                        sl_w,
                    )
                except Exception:
                    logger.exception("Smart-load probe: failed to turn OFF gen port sn=%s", sn)
        elif below is True:
            try:
                await _apply_gen_on_grid(sn, False)
                logger.info(
                    "Smart-load probe: solar insufficient — On Grid always on OFF sn=%s pv=%s sl=%s gen=%s",
                    sn,
                    pv_w,
                    sl_w,
                    gen_w,
                )
            except Exception:
                logger.exception("Smart-load probe: failed to turn OFF after insufficient PV sn=%s", sn)

    if below is None:
        return

    if below:
        streak = bump_pv_below_streak(sn)
        logger.debug(
            "Smart-load: PV < SL sn=%s streak=%s pv=%s sl=%s gen=%s",
            sn,
            streak,
            pv_w,
            sl_w,
            gen_w,
        )
        if streak >= streak_need:
            current = await _sync_gen_state_from_device(sn)
            if current is not False:
                try:
                    await _apply_gen_on_grid(sn, False)
                    reset_pv_below_streak(sn)
                    logger.info(
                        "Smart-load: PV < SL %sx — On Grid always on OFF sn=%s pv=%s sl=%s",
                        streak_need,
                        sn,
                        pv_w,
                        sl_w,
                    )
                except Exception:
                    logger.exception("Smart-load: failed to disable On Grid always on sn=%s", sn)
    else:
        reset_pv_below_streak(sn)

    if not settings.DEYE_SMART_LOAD_HOURLY_PROBE_ENABLED:
        return
    if not should_run_hourly_probe(sn, kyiv_date, kyiv_hour):
        return
    if yesterday_hour_all_pv_below(
        sn,
        kyiv_hour,
        min_samples=int(settings.DEYE_SMART_LOAD_YESTERDAY_SKIP_MIN_SAMPLES),
    ):
        mark_hourly_probe_started(sn, kyiv_date, kyiv_hour)
        logger.debug(
            "Smart-load: skip hourly probe (yesterday hour %s all PV < SL) sn=%s",
            kyiv_hour,
            sn,
        )
        return
    if not await _forecast_allows_probe(sn, kyiv_hour):
        mark_hourly_probe_started(sn, kyiv_date, kyiv_hour)
        logger.debug("Smart-load: skip hourly probe (low solar forecast) sn=%s hour=%s", sn, kyiv_hour)
        return
    try:
        await _apply_gen_on_grid(sn, True)
        mark_hourly_probe_started(sn, kyiv_date, kyiv_hour)
        logger.info(
            "Smart-load: hourly probe ON — On Grid always on enabled sn=%s hour=%s pv=%s sl=%s",
            sn,
            kyiv_hour,
            pv_w,
            sl_w,
        )
    except Exception:
        clear_pending_probe_check(sn)
        logger.exception("Smart-load: hourly probe failed sn=%s", sn)


async def run_smart_load_tick() -> None:
    if not deye_configured():
        return
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(DeyeSmartLoadPref.device_sn).where(DeyeSmartLoadPref.enabled.is_(True))
            )
        ).scalars().all()
    sns = [str(s).strip() for s in rows if s]
    for sn in sns:
        if not sn:
            continue
        try:
            await _process_device_tick(sn)
        except Exception:
            logger.exception("Smart-load tick failed sn=%s", sn)
