"""Background DAM sync every day at a fixed wall time in Europe/Kiev."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from app import settings
from app.db import async_session_factory
from app.oree_dam_service import KYIV, oree_dam_configured, sync_dam_prices_to_db

logger = logging.getLogger(__name__)


async def dam_daily_sync_loop(stop: asyncio.Event) -> None:
    """
    Sleep until next run time (Kyiv), then sync OREE → oree_dam_price.
    Repeats forever until stop is set.
    """
    hour = max(0, min(23, settings.OREE_DAM_DAILY_SYNC_HOUR_KYIV))
    minute = max(0, min(59, settings.OREE_DAM_DAILY_SYNC_MINUTE_KYIV))

    while not stop.is_set():
        now = datetime.now(KYIV)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        delay = max(0.5, (target - now).total_seconds())
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            return
        if oree_dam_configured():
            try:
                async with async_session_factory() as session:
                    n = await sync_dam_prices_to_db(session)
                    logger.info(
                        "DAM scheduled sync (Kyiv %02d:%02d): %s row(s) upserted",
                        hour,
                        minute,
                        n,
                    )
            except Exception:
                logger.exception("DAM scheduled sync failed")
        else:
            logger.debug("DAM scheduled sync skipped: OREE_API_KEY unset")
        await asyncio.sleep(2)
