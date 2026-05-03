"""Async loop: DAM vs LCOE self-consumption automation."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.deye_api import deye_configured
from app.deye_self_consumption_auto_dam_service import run_self_consumption_auto_dam_tick

logger = logging.getLogger(__name__)


async def deye_self_consumption_auto_dam_loop(stop: asyncio.Event) -> None:
    interval = max(30, settings.DEYE_SELF_CONSUMPTION_AUTO_DAM_INTERVAL_SEC)
    while not stop.is_set():
        if settings.DEYE_SELF_CONSUMPTION_AUTO_DAM_SCHEDULER_ENABLED and deye_configured():
            try:
                await run_self_consumption_auto_dam_tick()
            except Exception:
                logger.exception("Self-consumption auto DAM tick failed")
        else:
            logger.debug(
                "Self-consumption auto DAM: tick skipped (scheduler=%s, deye=%s)",
                settings.DEYE_SELF_CONSUMPTION_AUTO_DAM_SCHEDULER_ENABLED,
                deye_configured(),
            )
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
