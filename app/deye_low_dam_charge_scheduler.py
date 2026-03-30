"""Async loop: run low-DAM auto charge tick on an interval."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.deye_api import deye_configured
from app.deye_low_dam_charge_service import run_low_dam_charge_tick

logger = logging.getLogger(__name__)


async def deye_low_dam_charge_loop(stop: asyncio.Event) -> None:
    interval = max(20, settings.DEYE_LOW_DAM_CHARGE_INTERVAL_SEC)
    while not stop.is_set():
        if settings.DEYE_LOW_DAM_CHARGE_SCHEDULER_ENABLED and deye_configured():
            try:
                await run_low_dam_charge_tick()
            except Exception:
                logger.exception("Low DAM auto charge tick failed")
        else:
            logger.debug(
                "Low DAM auto charge: tick skipped (scheduler=%s, deye=%s)",
                settings.DEYE_LOW_DAM_CHARGE_SCHEDULER_ENABLED,
                deye_configured(),
            )
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
