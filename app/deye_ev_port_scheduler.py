"""Background loop: EV port — dynamic export tick every DEYE_EV_PORT_EXPORT_INTERVAL_SEC."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.deye_api import deye_configured
from app.deye_ev_port_export_service import run_ev_port_export_tick

logger = logging.getLogger(__name__)


async def deye_ev_port_export_loop(stop: asyncio.Event) -> None:
    interval = max(15, settings.DEYE_EV_PORT_EXPORT_INTERVAL_SEC)
    while not stop.is_set():
        if deye_configured():
            try:
                await run_ev_port_export_tick()
            except Exception:
                logger.exception("EV port export tick failed")
        else:
            logger.debug("EV port export: tick skipped (Deye API not configured)")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
