"""Persist Huawei real power samples to PostgreSQL and build hourly kWh charts (Kyiv calendar day)."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.huawei_api import (
    HuaweiRateLimitNoCacheError,
    get_power_flow,
    huawei_configured,
    list_stations,
)
from app.models import HuaweiPowerSample
from app.oree_dam_service import KYIV

logger = logging.getLogger(__name__)

# kWh per 5-minute bucket: P_w * (5/60) / 1000 (same factor as deye_soc_sample export sums)
_KWH_PER_BUCKET_DIVISOR = 12000.0
_BUCKET_ALIGN_SEC = 300


def floor_to_5min_utc(when: datetime) -> datetime:
    """UTC instant aligned to the start of its 5-minute wall bucket."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    utc = when.astimezone(timezone.utc)
    epoch = int(utc.timestamp())
    floored = epoch - (epoch % _BUCKET_ALIGN_SEC)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def _kyiv_day_bounds(trade_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(trade_day, time.min, tzinfo=KYIV)
    end = start + timedelta(days=1)
    return start, end


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


async def upsert_huawei_power_sample(
    session: AsyncSession,
    station_code: str,
    bucket_start: datetime,
    pv_power_w: Optional[float],
    grid_power_w: Optional[float],
    load_power_w: Optional[float],
) -> None:
    if pv_power_w is None and grid_power_w is None and load_power_w is None:
        return
    stmt = pg_insert(HuaweiPowerSample).values(
        station_code=station_code,
        bucket_start=bucket_start,
        pv_power_w=pv_power_w,
        grid_power_w=grid_power_w,
        load_power_w=load_power_w,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["station_code", "bucket_start"],
        set_={
            "pv_power_w": func.coalesce(stmt.excluded.pv_power_w, HuaweiPowerSample.pv_power_w),
            "grid_power_w": func.coalesce(stmt.excluded.grid_power_w, HuaweiPowerSample.grid_power_w),
            "load_power_w": func.coalesce(stmt.excluded.load_power_w, HuaweiPowerSample.load_power_w),
        },
    )
    await session.execute(stmt)


async def run_huawei_power_snapshot(session: AsyncSession) -> int:
    """
    For each plant in getStationList, call get_power_flow and upsert one row per 5-minute UTC bucket.
    """
    if not huawei_configured():
        return 0
    try:
        stations = await list_stations()
    except HuaweiRateLimitNoCacheError:
        logger.warning("Huawei power snapshot: station list unavailable (rate limit / no cache)")
        return 0
    except Exception:
        logger.exception("Huawei power snapshot: list_stations failed")
        return 0
    if not stations:
        return 0

    bucket = floor_to_5min_utc(datetime.now(timezone.utc))
    n = 0
    for row in stations:
        code = str(row.get("stationCode") or "").strip()
        if not code:
            continue
        try:
            pf = await get_power_flow(code)
        except Exception:
            logger.debug("Huawei power snapshot: get_power_flow failed for %s", code, exc_info=True)
            continue
        if not pf.get("ok"):
            continue
        pv = pf.get("pvPowerW")
        grid = pf.get("gridPowerW")
        load = pf.get("loadPowerW")
        pv_v: Optional[float] = None
        grid_v: Optional[float] = None
        load_v: Optional[float] = None
        if pv is not None:
            try:
                pv_v = max(0.0, float(pv))
            except (TypeError, ValueError):
                pass
        if grid is not None:
            try:
                grid_v = float(grid)
            except (TypeError, ValueError):
                pass
        if load is not None:
            try:
                load_v = max(0.0, float(load))
            except (TypeError, ValueError):
                pass
        if pv_v is None and grid_v is None and load_v is None:
            continue
        await upsert_huawei_power_sample(session, code, bucket, pv_v, grid_v, load_v)
        n += 1
    return n


def _add_sample_to_hourly(
    imp_h: list[float],
    exp_h: list[float],
    gen_h: list[float],
    cons_h: list[float],
    hour: int,
    pv_w: Optional[float],
    grid_w: Optional[float],
    load_w: Optional[float],
) -> None:
    if not (0 <= hour <= 23):
        return
    if grid_w is not None:
        g = float(grid_w)
        imp_h[hour] += max(0.0, g) / _KWH_PER_BUCKET_DIVISOR
        exp_h[hour] += max(0.0, -g) / _KWH_PER_BUCKET_DIVISOR
    if pv_w is not None:
        gen_h[hour] += max(0.0, float(pv_w)) / _KWH_PER_BUCKET_DIVISOR
    if load_w is not None:
        cons_h[hour] += max(0.0, float(load_w)) / _KWH_PER_BUCKET_DIVISOR


async def get_station_hourly_chart_from_db(
    session: AsyncSession,
    station_code: str,
    date_iso: str,
) -> dict[str, Any]:
    """Hourly kWh for one Kyiv day from huawei_power_sample (import/up, export/down, gen/up, load/down)."""
    st = (station_code or "").strip()
    d = _parse_date_iso(date_iso)
    if not st:
        return {"ok": False, "configured": bool(huawei_configured()), "reason": "missing_station"}
    if d is None:
        return {"ok": False, "configured": bool(huawei_configured()), "reason": "bad_date"}
    if not huawei_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}

    start_kyiv, end_kyiv = _kyiv_day_bounds(d)
    start_utc = start_kyiv.astimezone(timezone.utc)
    end_utc = end_kyiv.astimezone(timezone.utc)

    result = await session.execute(
        select(
            HuaweiPowerSample.bucket_start,
            HuaweiPowerSample.pv_power_w,
            HuaweiPowerSample.grid_power_w,
            HuaweiPowerSample.load_power_w,
        ).where(
            HuaweiPowerSample.station_code == st,
            HuaweiPowerSample.bucket_start >= start_utc,
            HuaweiPowerSample.bucket_start < end_utc,
        )
    )
    rows = result.all()

    imp_h = [0.0] * 24
    exp_h = [0.0] * 24
    gen_h = [0.0] * 24
    cons_h = [0.0] * 24
    for bucket_start, pv_w, grid_w, load_w in rows:
        local = bucket_start.astimezone(KYIV)
        h = int(local.hour)
        _add_sample_to_hourly(imp_h, exp_h, gen_h, cons_h, h, pv_w, grid_w, load_w)

    hours = []
    for h in range(24):
        ek = -exp_h[h] if exp_h[h] else 0.0
        ck = -cons_h[h] if cons_h[h] else 0.0
        hours.append(
            {
                "hour": h + 1,
                "gridImportKwh": round(imp_h[h], 4),
                "gridExportKwh": round(ek, 4),
                "generationKwh": round(gen_h[h], 4),
                "consumptionKwh": round(ck, 4),
            }
        )

    out: dict[str, Any] = {
        "ok": True,
        "configured": True,
        "stationCode": st,
        "date": date_iso,
        "timezone": "Europe/Kyiv",
        "source": "huawei_power_sample",
        "sampleIntervalMinutes": 5,
        "northboundRateLimited": False,
        "hours": hours,
        "totals": {
            "gridImportKwh": round(sum(imp_h), 4),
            "gridExportKwh": round(sum(exp_h), 4),
            "generationKwh": round(sum(gen_h), 4),
            "consumptionKwh": round(sum(cons_h), 4),
        },
    }
    if not rows:
        out["empty"] = True
    return out