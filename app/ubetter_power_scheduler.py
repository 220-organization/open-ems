"""Background task: persist Ubetter SoC / grid / PV / load every UBETTER_POWER_SNAPSHOT_INTERVAL_SEC."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.db import async_session_factory
from app.ubetter_api import ubetter_configured
from app.ubetter_power_service import run_ubetter_power_snapshot

logger = logging.getLogger(__name__)


async def ubetter_power_snapshot_loop(stop: asyncio.Event) -> None:
    interval = max(60, settings.UBETTER_POWER_SNAPSHOT_INTERVAL_SEC)
    while not stop.is_set():
        if ubetter_configured():
            try:
                async with async_session_factory() as session:
                    n = await run_ubetter_power_snapshot(session)
                    await session.commit()
                if n:
                    logger.info("Ubetter power DB snapshot: %s device row(s) upserted", n)
                else:
                    logger.debug("Ubetter power DB snapshot: no rows (no devices or power unavailable)")
            except Exception:
                logger.exception("Ubetter power DB snapshot failed")
        else:
            logger.debug("Ubetter power snapshot skipped: UBETTER_* not configured")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
