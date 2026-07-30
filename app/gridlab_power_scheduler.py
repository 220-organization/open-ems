"""Background task: persist GridLab SoC / grid / PV / load every GRIDLAB_POWER_SNAPSHOT_INTERVAL_SEC."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.db import async_session_factory
from app.gridlab_api import gridlab_configured
from app.gridlab_power_service import run_gridlab_power_snapshot

logger = logging.getLogger(__name__)


async def gridlab_power_snapshot_loop(stop: asyncio.Event) -> None:
    interval = max(30, settings.GRIDLAB_POWER_SNAPSHOT_INTERVAL_SEC)
    while not stop.is_set():
        if gridlab_configured():
            try:
                async with async_session_factory() as session:
                    n = await run_gridlab_power_snapshot(session)
                    await session.commit()
                if n:
                    logger.info("GridLab power DB snapshot: %s device row(s) upserted", n)
                else:
                    logger.debug("GridLab power DB snapshot: no rows (fetch failed or stale)")
            except Exception:
                logger.exception("GridLab power DB snapshot failed")
        else:
            logger.debug("GridLab power snapshot skipped: GRIDLAB_* not configured")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
