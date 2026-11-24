"""Persist commands sent to a Deye inverter and serve them with the alarm list."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeyeCommandEvent

logger = logging.getLogger(__name__)


def _num(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _kw_from_watts(value: Any) -> Optional[str]:
    text = _num(value)
    if text is None:
        return None
    return _num(float(value) / 1000.0)


def _on_off(value: Any) -> str:
    return "on" if value else "off"


def deye_command_title(action: str, result: dict[str, Any]) -> str:
    """One English line for the inverter events list."""
    if action == "discharge":
        start = _num(result.get("startSoc"))
        target = _num(result.get("targetSoc"))
        return f"Discharge now · SoC {start or '?'}% → {target or '?'}%"
    if action == "charge":
        start = _num(result.get("startSoc"))
        target = _num(result.get("targetSoc"))
        return f"Charge now · SoC {start or '?'}% → {target or '?'}%"
    if action == "power-limits":
        parts = ["Power limits"]
        solar = _kw_from_watts(result.get("maxSolarPowerW"))
        charge = _kw_from_watts(result.get("maxChargePowerW"))
        discharge = _kw_from_watts(result.get("maxDischargePowerW"))
        if solar is not None:
            parts.append(f"solar {solar} kW")
        if charge is not None:
            parts.append(f"charge {charge} kW")
        if discharge is not None:
            parts.append(f"discharge {discharge} kW")
        return " · ".join(parts)
    if action == "peak-auto-discharge":
        pct = _num(result.get("dischargeSocDeltaPct"))
        return f"Peak DAM discharge {_on_off(result.get('enabled'))} · till SoC {pct or '?'}%"
    if action == "low-dam-charge":
        pct = _num(result.get("chargeSocDeltaPct"))
        return f"Low DAM charge {_on_off(result.get('enabled'))} · +{pct or '?'}%"
    if action == "night-charge":
        pct = _num(result.get("chargeSocDeltaPct"))
        return f"Night charge {_on_off(result.get('nightChargeEnabled'))} · +{pct or '?'}%"
    if action == "self-consumption":
        return f"Self-consumption {_on_off(result.get('enabled'))}"
    if action == "smart-load":
        enabled = result.get("smartLoadEnabled", result.get("enabled"))
        return f"Smart load {_on_off(enabled)}"
    if action == "gen-port":
        return f"Gen port On Grid always on: {_on_off(result.get('genOnGridAlwaysOn'))}"
    return action or "Deye command"


def _detail_text(result: dict[str, Any]) -> str:
    safe = {key: value for key, value in result.items() if key.lower() != "pin"}
    text = json.dumps(safe, indent=2, ensure_ascii=False, default=str)
    if len(text) > 20000:
        return text[:20000]
    return text


async def record_deye_command(
    session: AsyncSession,
    device_sn: str,
    *,
    action: str,
    result: dict[str, Any],
) -> Optional[str]:
    """Append one accepted Deye command. Does not replace cloud alarms."""
    sn = (device_sn or "").strip()
    if not sn or not isinstance(result, dict) or result.get("ok") is False:
        return None
    now = datetime.now(timezone.utc)
    event_id = "cmd-" + uuid.uuid4().hex
    session.add(
        DeyeCommandEvent(
            id=event_id,
            device_sn=sn,
            title=deye_command_title(action, result),
            detail=_detail_text(result),
            occurred_at=now,
        )
    )
    await session.flush()
    return event_id


async def list_deye_commands(
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
    rows = await session.execute(
        select(DeyeCommandEvent)
        .where(
            DeyeCommandEvent.device_sn == sn,
            DeyeCommandEvent.occurred_at >= since,
        )
        .order_by(DeyeCommandEvent.occurred_at.desc())
        .limit(100)
    )
    items: list[dict[str, Any]] = []
    for row in rows.scalars().all():
        start = int(row.occurred_at.timestamp()) if row.occurred_at is not None else None
        items.append(
            {
                "id": row.id,
                "name": row.title,
                "title": row.title,
                "startTime": start,
                "endTime": None,
                "active": False,
                "kind": "command",
                "detail": row.detail,
            }
        )
    return items
