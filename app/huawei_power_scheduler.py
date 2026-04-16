"""Background task: persist Huawei PV/grid/load power every HUAWEI_POWER_SNAPSHOT_INTERVAL_SEC."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.db import async_session_factory
from app.huawei_api import huawei_configured
from app.huawei_power_service import run_huawei_power_snapshot

logger = logging.getLogger(__name__)


async def huawei_power_snapshot_loop(stop: asyncio.Event) -> None:
    interval = max(60, settings.HUAWEI_POWER_SNAPSHOT_INTERVAL_SEC)
    while not stop.is_set():
        if huawei_configured():
            try:
                async with async_session_factory() as session:
                    n = await run_huawei_power_snapshot(session)
                    await session.commit()
                if n:
                    logger.info("Huawei power DB snapshot: %s plant row(s) upserted", n)
                else:
                    logger.debug("Huawei power DB snapshot: no rows (no plants or power unavailable)")
            except Exception:
                logger.exception("Huawei power DB snapshot failed")
        else:
            logger.debug("Huawei power snapshot skipped: HUAWEI_* not configured")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
