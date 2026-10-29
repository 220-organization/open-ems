"""Background task: nightly Deye Cloud hourly kWh for the previous Kyiv day."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta

from app import settings
from app.db import async_session_factory
from app.deye_api import deye_configured, list_inverter_devices
from app.deye_energy_backfill_service import backfill_device_days
from app.oree_dam_service import KYIV

logger = logging.getLogger(__name__)

# Resume a crashed night run until this Kyiv hour, then wait for the next night.
_NIGHT_WINDOW_END_HOUR_KYIV = 6


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


def in_nightly_backfill_window(now: datetime, start_hour: int, end_hour: int = _NIGHT_WINDOW_END_HOUR_KYIV) -> bool:
    """True from the nightly start hour until ``end_hour`` (Kyiv), wrapping past midnight."""
    hour = int(now.astimezone(KYIV).hour)
    start = max(0, min(23, int(start_hour)))
    end = max(0, min(23, int(end_hour)))
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


async def _inverter_serials() -> list[str]:
    devices = await list_inverter_devices()
    return sorted(
        {
            str(row.get("deviceSn") or "").strip()
            for row in devices
            if str(row.get("deviceSn") or "").strip()
        }
    )


async def run_previous_day_backfill(
    stop: asyncio.Event,
    *,
    only_missing: bool,
) -> dict:
    """
    Refresh yesterday from Deye Cloud, one inverter at a time.

    Today is never requested. ``only_missing`` skips serials that already have a row,
    so a restart in the same night does not repeat calls.
    """
    today = datetime.now(KYIV).date()
    yesterday = today - timedelta(days=1)
    sns = await _inverter_serials()
    pause = float(settings.DEYE_HOURLY_ENERGY_DEVICE_INTERVAL_SEC)
    async with async_session_factory() as session:
        return await backfill_device_days(
            session,
            sns,
            [yesterday],
            only_missing=only_missing,
            today=today,
            pause_sec=pause,
            stop=stop,
        )


async def deye_hourly_energy_sync_loop(stop: asyncio.Event) -> None:
    """
    Each night at DEYE_HOURLY_ENERGY_SYNC_HOUR_KYIV, backfill yesterday for every inverter.

    Inverters run one after another with DEYE_HOURLY_ENERGY_DEVICE_INTERVAL_SEC between them
    so the job stays under the Deye Cloud per-minute limit. A restart before 06:00 Kyiv
    continues only the serials still missing yesterday.
    """
    hour = settings.DEYE_HOURLY_ENERGY_SYNC_HOUR_KYIV
    if deye_configured() and in_nightly_backfill_window(datetime.now(KYIV), hour):
        try:
            result = await run_previous_day_backfill(stop, only_missing=True)
            logger.info(
                "Deye hourly energy night resume: devices=%s deviceDays=%s rows=%s failed=%s stopped=%s",
                result.get("devices"),
                result.get("deviceDays"),
                result.get("rowsWritten"),
                result.get("failed"),
                result.get("stopped"),
            )
        except Exception:
            logger.exception("Deye hourly energy night resume failed")

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
            result = await run_previous_day_backfill(stop, only_missing=False)
            logger.info(
                "Deye hourly energy night sync (Kyiv %02d:00, previous day): "
                "devices=%s deviceDays=%s rows=%s failed=%s stopped=%s",
                target.hour,
                result.get("devices"),
                result.get("deviceDays"),
                result.get("rowsWritten"),
                result.get("failed"),
                result.get("stopped"),
            )
        except Exception:
            logger.exception("Deye hourly energy night sync failed")
        await asyncio.sleep(2)
