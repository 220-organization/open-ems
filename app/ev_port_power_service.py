"""Persist EV port aggregate power (B2B station/all) to PostgreSQL and build hourly grid-import charts."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.huawei_power_service import floor_to_5min_utc
from app.models import EvPortPowerSample
from app.oree_dam_service import KYIV
from app.settings import B2B_API_BASE_URL

logger = logging.getLogger(__name__)

_DEVICE_STATION_ALL_PATH = "/api/device/v2/station/all"
_KWH_PER_BUCKET_DIVISOR = 12000.0
_EV_ACDC_VALUES = ("dc", "ac")


def sum_ev_power_w_from_station_rows(raw: Any) -> tuple[float, int]:
    """Sum job.powerWt for stations with a non-null job (skip idle ports)."""
    if not isinstance(raw, list):
        return (0.0, 0)
    total = 0.0
    sessions = 0
    for row in raw:
        if not isinstance(row, dict):
            continue
        job = row.get("job")
        if job is None:
            continue
        if not isinstance(job, dict):
            continue
        pw = job.get("powerWt")
        if pw is None:
            continue
        try:
            w = float(pw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(w) or w <= 0:
            continue
        total += w
        sessions += 1
    return (total, sessions)


def _parse_date_iso(date_iso: str) -> Optional[date]:
    s = (date_iso or "").strip()
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return None
    try:
        y = int(s[0:4])
        m = int(s[5:7])
        d = int(s[8:10])
        return date(y, m, d)
    except ValueError:
        return None


def _kyiv_day_bounds(trade_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(trade_day, time.min, tzinfo=KYIV)
    end = start + timedelta(days=1)
    return start, end


def _normalize_acdc(acdc: str) -> Optional[str]:
    kind = (acdc or "").strip().lower()
    return kind if kind in _EV_ACDC_VALUES else None


async def fetch_ev_ports_power_w(acdc: str) -> tuple[Optional[float], int]:
    """Fetch live aggregate EV power (W) and active session count from B2B station/all."""
    kind = _normalize_acdc(acdc)
    if kind is None:
        return (None, 0)
    url = f"{B2B_API_BASE_URL}{_DEVICE_STATION_ALL_PATH}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params={"acdc": kind})
    except httpx.RequestError as exc:
        logger.warning("EV port power snapshot (%s): transport error: %s", kind, exc)
        return (None, 0)
    if response.status_code >= 400:
        logger.warning(
            "EV port power snapshot (%s): HTTP %s %s",
            kind,
            response.status_code,
            (response.text or "")[:300],
        )
        return (None, 0)
    try:
        raw = response.json()
    except ValueError:
        raw = None
    power_w, sessions = sum_ev_power_w_from_station_rows(raw)
    return (power_w, sessions)


async def upsert_ev_port_power_sample(
    session: AsyncSession,
    acdc: str,
    bucket_start: datetime,
    power_w: Optional[float],
    active_sessions: Optional[int],
) -> None:
    kind = _normalize_acdc(acdc)
    if kind is None:
        return
    stmt = pg_insert(EvPortPowerSample).values(
        acdc=kind,
        bucket_start=bucket_start,
        power_w=power_w,
        active_sessions=active_sessions,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[EvPortPowerSample.acdc, EvPortPowerSample.bucket_start],
        set_={
            "power_w": stmt.excluded.power_w,
            "active_sessions": stmt.excluded.active_sessions,
        },
    )
    await session.execute(stmt)


async def run_ev_port_power_snapshot(session: AsyncSession) -> int:
    """Fetch DC and AC fleet power and upsert both into the current 5-minute UTC bucket."""
    bucket = floor_to_5min_utc(datetime.now(timezone.utc))
    n = 0
    for kind in _EV_ACDC_VALUES:
        power_w, sessions = await fetch_ev_ports_power_w(kind)
        if power_w is None and sessions == 0:
            power_v: Optional[float] = 0.0
            sessions_v: Optional[int] = 0
        else:
            power_v = max(0.0, float(power_w or 0.0))
            sessions_v = int(sessions)
        await upsert_ev_port_power_sample(session, kind, bucket, power_v, sessions_v)
        n += 1
    return n


async def get_ev_port_hourly_chart_from_db(
    session: AsyncSession,
    acdc: str,
    date_iso: str,
) -> dict[str, Any]:
    """Hourly grid import kWh for one Kyiv day from ev_port_power_sample."""
    kind = _normalize_acdc(acdc)
    d = _parse_date_iso(date_iso)
    if kind is None:
        return {"ok": False, "configured": True, "reason": "invalid_acdc"}
    if d is None:
        return {"ok": False, "configured": True, "reason": "bad_date"}

    start_kyiv, end_kyiv = _kyiv_day_bounds(d)
    start_utc = start_kyiv.astimezone(timezone.utc)
    end_utc = end_kyiv.astimezone(timezone.utc)

    result = await session.execute(
        select(EvPortPowerSample.bucket_start, EvPortPowerSample.power_w).where(
            EvPortPowerSample.acdc == kind,
            EvPortPowerSample.bucket_start >= start_utc,
            EvPortPowerSample.bucket_start < end_utc,
        )
    )
    rows = result.all()

    imp_h = [0.0] * 24
    for bucket_start, power_w in rows:
        if power_w is None:
            continue
        local = bucket_start.astimezone(KYIV)
        h = int(local.hour)
        if 0 <= h <= 23:
            imp_h[h] += max(0.0, float(power_w)) / _KWH_PER_BUCKET_DIVISOR

    hours = []
    for h in range(24):
        hours.append(
            {
                "hour": h + 1,
                "gridImportKwh": round(imp_h[h], 4),
                "gridExportKwh": 0.0,
                "generationKwh": 0.0,
                "consumptionKwh": 0.0,
            }
        )
    totals = {
        "gridImportKwh": round(sum(imp_h), 4),
        "gridExportKwh": 0.0,
        "generationKwh": 0.0,
        "consumptionKwh": 0.0,
    }

    out: dict[str, Any] = {
        "ok": True,
        "configured": True,
        "acdc": kind,
        "date": date_iso,
        "timezone": "Europe/Kyiv",
        "source": "ev_port_power_sample",
        "sampleIntervalMinutes": 5,
        "hours": hours,
        "totals": totals,
    }
    if not rows:
        out["empty"] = True
    return out
