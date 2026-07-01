"""Async loop: smart-load PV vs Smart Load automation."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.deye_api import deye_configured
from app.deye_smart_load_service import run_smart_load_tick

logger = logging.getLogger(__name__)


async def deye_smart_load_loop(stop: asyncio.Event) -> None:
    interval = max(60, settings.DEYE_SMART_LOAD_INTERVAL_SEC)
    while not stop.is_set():
        if settings.DEYE_SMART_LOAD_SCHEDULER_ENABLED and deye_configured():
            try:
                await run_smart_load_tick()
            except Exception:
                logger.exception("Smart-load auto tick failed")
        else:
            logger.debug(
                "Smart-load auto: tick skipped (scheduler=%s, deye=%s)",
                settings.DEYE_SMART_LOAD_SCHEDULER_ENABLED,
                deye_configured(),
            )
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
