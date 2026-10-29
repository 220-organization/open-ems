"""Background task: daily Deye Cloud hourly kWh backfill for completed Kyiv days."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta

from app import settings
from app.db import async_session_factory
from app.deye_api import deye_configured, list_inverter_devices
from app.deye_energy_backfill_service import backfill_device_days, completed_kyiv_days
from app.oree_dam_service import KYIV

logger = logging.getLogger(__name__)


def _next_kyiv_hour_run(after: datetime, hour: int) -> datetime:
    """Next Kyiv wall-clock instant at ``hour:00`` strictly after ``after``."""
    h = max(0, min(23, hour))
    base_date = after.astimezone(KYIV).date()
    for offset in range(0, 3):
        d = base_date + timedelta(days=offset)
        cand = datetime.combine(d, time(h, 0, 0), tzinfo=KYIV)
        if cand > after:
            return cand
    return after + timedelta(days=1)


async def _inverter_serials() -> list[str]:
    devices = await list_inverter_devices()
    return sorted(
        {
            str(row.get("deviceSn") or "").strip()
            for row in devices
            if str(row.get("deviceSn") or "").strip()
        }
    )


async def run_startup_hourly_energy_catchup() -> dict:
    """Fill recent completed days that have no ``deye_hourly_energy`` row yet."""
    today = datetime.now(KYIV).date()
    days = completed_kyiv_days(today, settings.DEYE_HOURLY_ENERGY_CATCHUP_DAYS)
    sns = await _inverter_serials()
    async with async_session_factory() as session:
        return await backfill_device_days(session, sns, days, only_missing=True, today=today)


async def run_daily_hourly_energy_sync() -> dict:
    """Refresh yesterday from Deye Cloud for every inverter. Today stays on 5-min samples."""
    today = datetime.now(KYIV).date()
    yesterday = today - timedelta(days=1)
    sns = await _inverter_serials()
    async with async_session_factory() as session:
        return await backfill_device_days(
            session, sns, [yesterday], only_missing=False, today=today
        )


async def deye_hourly_energy_sync_loop(stop: asyncio.Event) -> None:
    """
    On startup: backfill the last DEYE_HOURLY_ENERGY_CATCHUP_DAYS completed days when missing.
    Then at DEYE_HOURLY_ENERGY_SYNC_HOUR_KYIV: refresh yesterday for every inverter.
    """
    if deye_configured():
        try:
            result = await run_startup_hourly_energy_catchup()
            logger.info(
                "Deye hourly energy startup catch-up: devices=%s deviceDays=%s rows=%s failed=%s",
                result.get("devices"),
                result.get("deviceDays"),
                result.get("rowsWritten"),
                result.get("failed"),
            )
        except Exception:
            logger.exception("Deye hourly energy startup catch-up failed")

    hour = settings.DEYE_HOURLY_ENERGY_SYNC_HOUR_KYIV
    while not stop.is_set():
        now = datetime.now(KYIV)
        target = _next_kyiv_hour_run(now, hour)
        delay = max(0.5, (target - now).total_seconds())
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            return
        if not deye_configured():
            logger.debug("Deye hourly energy sync skipped: DEYE_* not configured")
            await asyncio.sleep(2)
            continue
        try:
            result = await run_daily_hourly_energy_sync()
            logger.info(
                "Deye hourly energy daily sync (Kyiv %02d:00): devices=%s rows=%s failed=%s",
                target.hour,
                result.get("devices"),
                result.get("rowsWritten"),
                result.get("failed"),
            )
        except Exception:
            logger.exception("Deye hourly energy daily sync failed")
        await asyncio.sleep(2)
