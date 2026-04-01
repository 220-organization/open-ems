"""Background DAM sync at fixed Europe/Kiev hours; skip OREE when tomorrow is already complete in DB."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta

from app import settings
from app.db import async_session_factory
from app.oree_dam_service import (
    KYIV,
    dam_trade_day_complete_in_db,
    kyiv_tomorrow,
    oree_dam_configured,
    sync_dam_prices_to_db,
)

logger = logging.getLogger(__name__)


def _next_kyiv_sync_run(after: datetime, hours: tuple[int, ...], minute: int) -> datetime:
    """Next scheduled instant strictly after `after` (timezone-aware Kyiv)."""
    minute = max(0, min(59, minute))
    hs = sorted({h for h in hours if 0 <= h <= 23})
    if not hs:
        hs = [15]
    base_date = after.astimezone(KYIV).date()
    for offset in range(0, 8):
        d = base_date + timedelta(days=offset)
        for h in hs:
            cand = datetime.combine(d, time(h, minute, 0), tzinfo=KYIV)
            if cand > after:
                return cand
    return after + timedelta(hours=1)


async def dam_daily_sync_loop(stop: asyncio.Event) -> None:
    """
    At each configured Kyiv hour (default 12,13,14,15), sync OREE → oree_dam_price if Kyiv-tomorrow
    is not yet complete in DB for OREE_COMPARE_ZONE_EIC.
    """
    hours = settings.OREE_DAM_SYNC_HOURS_KYIV
    minute = max(0, min(59, settings.OREE_DAM_DAILY_SYNC_MINUTE_KYIV))

    while not stop.is_set():
        now = datetime.now(KYIV)
        target = _next_kyiv_sync_run(now, hours, minute)
        delay = max(0.5, (target - now).total_seconds())
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            return
        if not oree_dam_configured():
            logger.debug("DAM scheduled sync skipped: OREE_API_KEY unset")
            await asyncio.sleep(2)
            continue
        zone = settings.OREE_COMPARE_ZONE_EIC
        trade_day = kyiv_tomorrow()
        try:
            async with async_session_factory() as session:
                if await dam_trade_day_complete_in_db(session, trade_day, zone):
                    logger.info(
                        "DAM scheduled sync skipped (Kyiv %02d:%02d): %s zone=%s already has 24/24 hours in DB",
                        target.hour,
                        target.minute,
                        trade_day.isoformat(),
                        zone,
                    )
                else:
                    n = await sync_dam_prices_to_db(session)
                    logger.info(
                        "DAM scheduled sync (Kyiv %02d:%02d): %s row(s) upserted (target day %s)",
                        target.hour,
                        target.minute,
                        n,
                        trade_day.isoformat(),
                    )
        except Exception:
            logger.exception("DAM scheduled sync failed")
        await asyncio.sleep(2)
