"""Background task: persist Deye SoC for all inverters every DEYE_SOC_SNAPSHOT_INTERVAL_SEC."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.db import async_session_factory
from app.deye_api import deye_configured
from app.deye_soc_service import run_deye_soc_snapshot

logger = logging.getLogger(__name__)


async def deye_soc_snapshot_loop(stop: asyncio.Event) -> None:
    interval = max(60, settings.DEYE_SOC_SNAPSHOT_INTERVAL_SEC)
    while not stop.is_set():
        if deye_configured():
            try:
                async with async_session_factory() as session:
                    n = await run_deye_soc_snapshot(session)
                    await session.commit()
                if n:
                    logger.info("Deye SoC DB snapshot: %s device row(s) upserted", n)
                else:
                    logger.debug("Deye SoC DB snapshot: no rows (no inverters or SOC unavailable)")
            except Exception:
                logger.exception("Deye SoC DB snapshot failed")
        else:
            logger.debug("Deye SoC snapshot skipped: DEYE_* not configured")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
