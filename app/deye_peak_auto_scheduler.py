"""Background loop: peak-DAM auto discharge tick every DEYE_PEAK_AUTO_DISCHARGE_INTERVAL_SEC."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.deye_api import deye_configured
from app.deye_peak_auto_service import run_peak_auto_discharge_tick

logger = logging.getLogger(__name__)


async def deye_peak_auto_discharge_loop(stop: asyncio.Event) -> None:
    interval = max(20, settings.DEYE_PEAK_AUTO_DISCHARGE_INTERVAL_SEC)
    while not stop.is_set():
        if (
            settings.DEYE_PEAK_AUTO_DISCHARGE_SCHEDULER_ENABLED
            and deye_configured()
        ):
            try:
                await run_peak_auto_discharge_tick()
            except Exception:
                logger.exception("Peak DAM auto discharge tick failed")
        else:
            logger.debug(
                "Peak DAM auto: tick skipped (scheduler=%s, deye=%s)",
                settings.DEYE_PEAK_AUTO_DISCHARGE_SCHEDULER_ENABLED,
                deye_configured(),
            )
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
