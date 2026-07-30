"""Background task: daily GridLab hourly history sync + startup backfill when DB empty."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta

from app import settings
from app.db import async_session_factory
from app.gridlab_api import gridlab_configured
from app.gridlab_history_service import run_daily_history_sync, run_startup_backfill_if_empty
from app.oree_dam_service import KYIV

logger = logging.getLogger(__name__)


def _next_kyiv_hour_run(after: datetime, hour: int) -> datetime:
    """Next Kyiv wall-clock instant at ``hour:00`` strictly after ``after``."""
    h = max(0, min(23, hour))
    base_date = after.astimezone(KYIV).date()
    for offset in range(0, 3):
        d = base_date + timedelta(days=offset)
        cand = datetime.combine(d, time(h, 0, 0), tzinfo=KYIV)
        if cand > after:
            return cand
    return after + timedelta(days=1)


async def gridlab_history_sync_loop(stop: asyncio.Event) -> None:
    """
    On startup: backfill GRIDLAB_HISTORY_BACKFILL_DAYS if hourly SoC table is empty.
    Then at GRIDLAB_HISTORY_SYNC_HOUR_KYIV each day: sync yesterday + today.
    """
    if gridlab_configured():
        try:
            async with async_session_factory() as session:
                result = await run_startup_backfill_if_empty(session)
            if result:
                logger.info(
                    "GridLab history startup backfill: soc=%s meter=%s flow=%s",
                    result.get("socHours"),
                    result.get("meterHours"),
                    result.get("flowHours"),
                )
        except Exception:
            logger.exception("GridLab history startup backfill failed")

    hour = settings.GRIDLAB_HISTORY_SYNC_HOUR_KYIV
    while not stop.is_set():
        now = datetime.now(KYIV)
        target = _next_kyiv_hour_run(now, hour)
        delay = max(0.5, (target - now).total_seconds())
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            return
        if not gridlab_configured():
            logger.debug("GridLab history sync skipped: GRIDLAB_* not configured")
            await asyncio.sleep(2)
            continue
        try:
            async with async_session_factory() as session:
                result = await run_daily_history_sync(session)
            logger.info(
                "GridLab history daily sync (Kyiv %02d:00): soc=%s meter=%s flow=%s",
                target.hour,
                result.get("socHours"),
                result.get("meterHours"),
                result.get("flowHours"),
            )
        except Exception:
            logger.exception("GridLab history daily sync failed")
        await asyncio.sleep(2)
