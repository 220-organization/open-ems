"""Persist Ubetter faultList alarms and serve them to the power-flow events panel."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, null, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UbetterEvent
from app.ubetter_api import fetch_device_alarms, list_devices, ubetter_configured

logger = logging.getLogger(__name__)


def _occurred_at(start_time: Optional[int]) -> Optional[datetime]:
    if start_time is None or start_time <= 0:
        return None
    return datetime.fromtimestamp(int(start_time), tz=timezone.utc)


def event_row_to_api(row: UbetterEvent) -> dict[str, Any]:
    """Same shape as a Deye alert item so the events list can render either source."""
    title = (row.alarm_name_en or row.alarm_name or "").strip()
    start = int(row.occurred_at.timestamp()) if row.occurred_at is not None else None
    end = int(row.cleared_at.timestamp()) if row.cleared_at is not None else None
    return {
        "id": row.alarm_id,
        "name": row.alarm_name or title,
        "title": title,
        "level": row.alarm_level,
        "startTime": start,
        "endTime": end,
        "active": bool(row.is_current),
    }


async def sync_device_alarms(
    session: AsyncSession,
    device_sn: str,
    alarms: list[dict[str, Any]],
    *,
    clear_missing: bool,
) -> int:
    """Upsert the latest faultList. Clear alarms that disappeared only when the list was present."""
    sn = (device_sn or "").strip()
    if not sn:
        return 0
    now = datetime.now(timezone.utc)
    seen: list[str] = []
    for alarm in alarms:
        alarm_id = str(alarm.get("id") or "").strip()
        if not alarm_id:
            continue
        seen.append(alarm_id)
        active = alarm.get("active") is True
        values = {
            "device_sn": sn,
            "alarm_id": alarm_id,
            "alarm_name": alarm.get("name") or None,
            "alarm_name_en": alarm.get("title") or None,
            "alarm_source": alarm.get("source"),
            "alarm_level": alarm.get("level"),
            "event_status": alarm.get("eventStatus"),
            "is_fault": alarm.get("isFault"),
            "is_current": active,
            "occurred_at": _occurred_at(alarm.get("startTime")),
            "cleared_at": None if active else now,
            "component_category_en": alarm.get("componentCategoryEn"),
            "component_model_en": alarm.get("componentModelEn"),
            "fault_position": alarm.get("faultPosition"),
            "last_seen_at": now,
        }
        stmt = pg_insert(UbetterEvent).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["device_sn", "alarm_id"],
            set_={
                "alarm_name": func.coalesce(stmt.excluded.alarm_name, UbetterEvent.alarm_name),
                "alarm_name_en": func.coalesce(stmt.excluded.alarm_name_en, UbetterEvent.alarm_name_en),
                "alarm_source": func.coalesce(stmt.excluded.alarm_source, UbetterEvent.alarm_source),
                "alarm_level": func.coalesce(stmt.excluded.alarm_level, UbetterEvent.alarm_level),
                "event_status": func.coalesce(stmt.excluded.event_status, UbetterEvent.event_status),
                "is_fault": func.coalesce(stmt.excluded.is_fault, UbetterEvent.is_fault),
                "is_current": stmt.excluded.is_current,
                "occurred_at": func.coalesce(stmt.excluded.occurred_at, UbetterEvent.occurred_at),
                "cleared_at": null() if active else func.coalesce(UbetterEvent.cleared_at, now),
                "component_category_en": func.coalesce(
                    stmt.excluded.component_category_en,
                    UbetterEvent.component_category_en,
                ),
                "component_model_en": func.coalesce(
                    stmt.excluded.component_model_en,
                    UbetterEvent.component_model_en,
                ),
                "fault_position": func.coalesce(stmt.excluded.fault_position, UbetterEvent.fault_position),
                "last_seen_at": now,
            },
        )
        await session.execute(stmt)

    if clear_missing:
        stale = update(UbetterEvent).where(
            UbetterEvent.device_sn == sn,
            UbetterEvent.is_current.is_(True),
        )
        if seen:
            stale = stale.where(UbetterEvent.alarm_id.notin_(seen))
        await session.execute(
            stale.values(is_current=False, cleared_at=func.coalesce(UbetterEvent.cleared_at, now))
        )
    return len(seen)


async def list_stored_events(
    session: AsyncSession,
    device_sn: str,
    *,
    hours: int,
) -> list[dict[str, Any]]:
    sn = (device_sn or "").strip()
    if not sn:
        return []
    window_h = max(1, min(int(hours), 24 * 30))
    since = datetime.now(timezone.utc) - timedelta(hours=window_h)
    result = await session.execute(
        select(UbetterEvent)
        .where(
            UbetterEvent.device_sn == sn,
            or_(
                UbetterEvent.occurred_at >= since,
                UbetterEvent.is_current.is_(True),
                UbetterEvent.last_seen_at >= since,
            ),
        )
        .order_by(UbetterEvent.occurred_at.desc().nullslast(), UbetterEvent.last_seen_at.desc())
        .limit(100)
    )
    return [event_row_to_api(row) for row in result.scalars().all()]


async def sync_device_alarms_from_cloud(session: AsyncSession, device_sn: str) -> bool:
    """Fetch faultList and store it. False when the cloud omitted the list (nothing cleared)."""
    alarms, present = await fetch_device_alarms(device_sn)
    if not present:
        return False
    await sync_device_alarms(session, device_sn, alarms, clear_missing=True)
    return True


async def run_ubetter_event_snapshot(session: AsyncSession) -> int:
    """Poll every configured cabinet and keep its alarm log."""
    if not ubetter_configured():
        return 0
    try:
        items = await list_devices()
    except Exception:
        logger.exception("Ubetter event snapshot: list_devices failed")
        return 0
    n = 0
    for item in items:
        sn = str(item.get("sn") or "").strip()
        if not sn:
            continue
        try:
            if await sync_device_alarms_from_cloud(session, sn):
                n += 1
        except Exception:
            logger.debug("Ubetter event snapshot failed for %s", sn, exc_info=True)
    return n
