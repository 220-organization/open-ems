"""Background ENTSO-E DAM sync at Europe/Brussels hours; target delivery day = tomorrow (Brussels)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta

from app import settings
from app.db import async_session_factory
from app.entsoe_dam_service import (
    BRUSSELS,
    delivery_tomorrow_brussels,
    entsoe_dam_configured,
    entsoe_trade_day_complete_in_db,
    sync_entsoe_all_configured_zones,
)

logger = logging.getLogger(__name__)


def _next_brussels_sync_run(after: datetime, hours: tuple[int, ...], minute: int) -> datetime:
    minute = max(0, min(59, minute))
    hs = sorted({h for h in hours if 0 <= h <= 23})
    if not hs:
        hs = [15]
    base_date = after.astimezone(BRUSSELS).date()
    for offset in range(0, 8):
        d = base_date + timedelta(days=offset)
        for h in hs:
            cand = datetime.combine(d, time(h, minute, 0), tzinfo=BRUSSELS)
            if cand > after:
                return cand
    return after + timedelta(hours=1)


async def entsoe_dam_daily_sync_loop(stop: asyncio.Event) -> None:
    """
    At each configured Brussels hour, pull ENTSO-E for delivery_tomorrow_brussels()
    if any configured zone is still incomplete for that delivery day.
    """
    hours = settings.ENTSOE_DAM_SYNC_HOURS_BRUSSELS
    minute = max(0, min(59, settings.ENTSOE_DAM_DAILY_SYNC_MINUTE_BRUSSELS))

    while not stop.is_set():
        now = datetime.now(BRUSSELS)
        target = _next_brussels_sync_run(now, hours, minute)
        delay = max(0.5, (target - now).total_seconds())
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            return
        if not entsoe_dam_configured():
            logger.debug("ENTSO-E scheduled sync skipped: ENTSOE_SECURITY_TOKEN unset")
            await asyncio.sleep(2)
            continue

        trade_day = delivery_tomorrow_brussels()
        try:
            if settings.ENTSOE_DAM_DAILY_SYNC_SKIP_IF_COMPLETE:
                async with async_session_factory() as session:
                    need = False
                    for ze in settings.ENTSOE_DAM_ZONE_EICS:
                        z = ze.strip()
                        if not z:
                            continue
                        if not await entsoe_trade_day_complete_in_db(session, trade_day, z):
                            need = True
                            break
                    if not need:
                        logger.info(
                            "ENTSO-E DAM sync skipped (Brussels %02d:%02d): all zones complete for %s",
                            target.hour,
                            target.minute,
                            trade_day.isoformat(),
                        )
                        await asyncio.sleep(2)
                        continue

            async with async_session_factory() as session:
                n = await sync_entsoe_all_configured_zones(session, trade_day)
                logger.info(
                    "ENTSO-E DAM sync (Brussels %02d:%02d): %s row(s) for delivery %s (zones: %s)",
                    target.hour,
                    target.minute,
                    n,
                    trade_day.isoformat(),
                    ",".join(z.strip() for z in settings.ENTSOE_DAM_ZONE_EICS if z.strip()) or "(none)",
                )
        except Exception:
            logger.exception("ENTSO-E DAM scheduled sync failed")
        await asyncio.sleep(2)
