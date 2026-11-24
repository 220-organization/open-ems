"""Persist Ubetter faultList alarms and commands sent to a cabinet."""

from __future__ import annotations

import json
import logging
import uuid
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


_COMMAND_SOURCE = "command"
_SLOT_MODE = {0: "idle", 1: "charge", 2: "discharge"}
_STRATEGY_BLOCKS = {
    0: "manual",
    1: "backup",
    3: "peakValley",
    4: "fixedTime",
    5: "selfConsumption",
    6: "aiAuto",
    7: "transformerExpand",
}


def format_command_event_title(strategy: dict[str, Any]) -> str:
    """One line for the events list. Matches the command-result summary."""
    code = strategy.get("strategy")
    name = _STRATEGY_BLOCKS.get(code) if isinstance(code, int) else None
    block = strategy.get(name) if name and isinstance(strategy.get(name), dict) else {}
    if not block and any(key in strategy for key in ("chargeSoc", "chargePower", "chargeCtrl")):
        block = strategy
    parts = [f"strategy={code if code is not None else '?'}"]
    ctrl = block.get("chargeCtrl")
    if ctrl is not None:
        parts.append(f"chargeCtrl={ctrl} ({_SLOT_MODE.get(ctrl, ctrl)})")
    if block.get("chargeSoc") is not None:
        parts.append(f"chargeSoc={block['chargeSoc']}%")
    if block.get("dischargeSoc") is not None:
        parts.append(f"dischargeSoc={block['dischargeSoc']}%")
    if block.get("chargePower") is not None:
        parts.append(f"chargePower={block['chargePower']} kW")
    if block.get("dischargePower") is not None:
        parts.append(f"dischargePower={block['dischargePower']} kW")
    slots = strategy.get("slots") if isinstance(strategy.get("slots"), list) else []
    if len(slots) == 1 and isinstance(slots[0], dict):
        slot = slots[0]
        mode = _SLOT_MODE.get(slot.get("mode"), slot.get("mode"))
        power = f" {slot['power']} kW" if slot.get("power") is not None else ""
        parts.append(f"slots={slot.get('startTime')}-{slot.get('endTime')} {mode}{power}")
    elif len(slots) > 1:
        parts.append(f"slots={len(slots)}")
    return "PUT run-strategy → " + " · ".join(parts)


def event_row_to_api(row: UbetterEvent) -> dict[str, Any]:
    """Same shape as a Deye alert item so the events list can render either source."""
    title = (row.alarm_name_en or row.alarm_name or "").strip()
    start = int(row.occurred_at.timestamp()) if row.occurred_at is not None else None
    end = int(row.cleared_at.timestamp()) if row.cleared_at is not None else None
    is_command = (row.alarm_source or "") == _COMMAND_SOURCE
    return {
        "id": row.alarm_id,
        "name": row.alarm_name or title,
        "title": title,
        "level": row.alarm_level,
        "startTime": start,
        "endTime": end,
        "active": False if is_command else bool(row.is_current),
        "kind": "command" if is_command else "alarm",
        "detail": row.detail if is_command else None,
    }


async def record_ubetter_command(
    session: AsyncSession,
    device_sn: str,
    *,
    command: dict[str, Any],
    verified: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Append one sent run-strategy command. Does not replace cloud alarms."""
    sn = (device_sn or "").strip()
    strategy = command.get("strategy") if isinstance(command, dict) else None
    if not sn or not isinstance(strategy, dict):
        return None
    now = datetime.now(timezone.utc)
    title = format_command_event_title(strategy)
    payload: dict[str, Any] = {
        "command": {
            "ok": command.get("ok"),
            "configured": command.get("configured"),
            "sn": sn,
            "strategy": strategy,
        }
    }
    verified_strategy = verified.get("strategy") if isinstance(verified, dict) else None
    if isinstance(verified_strategy, dict):
        payload["verified"] = {
            "ok": verified.get("ok"),
            "configured": verified.get("configured"),
            "sn": verified.get("sn") or sn,
            "strategy": verified_strategy,
        }
    detail = json.dumps(payload, indent=2, ensure_ascii=False)
    if len(detail) > 20000:
        detail = detail[:20000]
    alarm_id = "cmd-" + uuid.uuid4().hex
    await session.execute(
        pg_insert(UbetterEvent).values(
            device_sn=sn,
            alarm_id=alarm_id,
            alarm_name=title,
            alarm_name_en=title,
            alarm_source=_COMMAND_SOURCE,
            is_fault=False,
            is_current=False,
            occurred_at=now,
            detail=detail,
            last_seen_at=now,
        )
    )
    return alarm_id


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
            or_(UbetterEvent.alarm_source.is_(None), UbetterEvent.alarm_source != _COMMAND_SOURCE),
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
