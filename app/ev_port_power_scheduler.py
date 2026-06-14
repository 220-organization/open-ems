"""Background task: persist EV port aggregate power every EV_PORT_POWER_SNAPSHOT_INTERVAL_SEC."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.db import async_session_factory
from app.ev_port_power_service import run_ev_port_power_snapshot

logger = logging.getLogger(__name__)


async def ev_port_power_snapshot_loop(stop: asyncio.Event) -> None:
    interval = max(60, settings.EV_PORT_POWER_SNAPSHOT_INTERVAL_SEC)
    while not stop.is_set():
        if settings.EV_PORT_POWER_SNAPSHOT_ENABLED:
            try:
                async with async_session_factory() as session:
                    n = await run_ev_port_power_snapshot(session)
                    await session.commit()
                if n:
                    logger.info("EV port power DB snapshot: %s fleet row(s) upserted", n)
                else:
                    logger.debug("EV port power DB snapshot: no rows upserted")
            except Exception:
                logger.exception("EV port power DB snapshot failed")
        else:
            logger.debug("EV port power snapshot skipped: EV_PORT_POWER_SNAPSHOT_ENABLED=false")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
