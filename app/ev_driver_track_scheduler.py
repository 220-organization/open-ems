"""Background task: process raw driver GPS into stays/trips and purge old raw rows."""

from __future__ import annotations

import asyncio
import logging

from app import settings
from app.db import async_session_factory
from app.ev_driver_track_service import cleanup_old_raw, process_unprocessed_raw

logger = logging.getLogger(__name__)


async def ev_driver_track_processing_loop(stop: asyncio.Event) -> None:
    interval = max(60, settings.EV_TRACKER_PROCESSING_INTERVAL_SEC)
    while not stop.is_set():
        if settings.EV_TRACKER_PROCESSING_ENABLED:
            try:
                async with async_session_factory() as session:
                    stats = await process_unprocessed_raw(session)
                    deleted = await cleanup_old_raw(session)
                    await session.commit()
                if any(stats.values()) or deleted:
                    logger.info(
                        "EV driver track processing: drivers=%s stays=%s trips=%s dropped=%s deleted_raw=%s",
                        stats.get("drivers", 0),
                        stats.get("stays", 0),
                        stats.get("trips", 0),
                        stats.get("dropped", 0),
                        deleted,
                    )
            except Exception:
                logger.exception("EV driver track processing failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
