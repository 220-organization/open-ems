"""Background task: refresh Huawei station energy day/month/year totals into Postgres."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.huawei_api import huawei_configured
from app.huawei_station_energy_service import run_huawei_station_energy_snapshot

logger = logging.getLogger(__name__)


async def huawei_station_energy_loop(stop: asyncio.Event) -> None:
    interval = max(120, settings.HUAWEI_STATION_ENERGY_SNAPSHOT_INTERVAL_SEC)
    while not stop.is_set():
        if huawei_configured():
            try:
                n = await run_huawei_station_energy_snapshot()
                if n:
                    logger.info("Huawei station energy snapshot: %s row(s) refreshed", n)
                else:
                    logger.debug("Huawei station energy snapshot: no rows refreshed")
            except Exception:
                logger.exception("Huawei station energy snapshot failed")
        else:
            logger.debug("Huawei station energy snapshot skipped: HUAWEI_* not configured")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
