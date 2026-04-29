"""
Huawei station energy totals — DB cache layer over getKpiStationDay/Month/Year.

UI reads day/month/year totals from `huawei_station_energy_totals`.
Background scheduler refreshes; UI lazy-refresh kicks in only on miss / stale row.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.db import async_session_factory
from app.huawei_api import (
    HuaweiAuthError,
    HuaweiNorthboundError,
    HuaweiRateLimitNoCacheError,
    get_station_energy_kpi,
    huawei_configured,
    list_stations,
)
from app.huawei_power_service import get_station_hourly_chart_from_db
from app.models import HuaweiStationEnergyTotals

logger = logging.getLogger(__name__)

VALID_PERIODS: tuple[str, ...] = ("day", "month", "year")


def parse_date_iso(date_iso: str) -> Optional[date]:
    s = (date_iso or "").strip()
    if len(s) != 10:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def period_key_for(d: date, period: str) -> str:
    """'YYYY-MM-DD' for day, 'YYYY-MM' for month, 'YYYY' for year."""
    if period == "day":
        return d.isoformat()
    if period == "month":
        return f"{d.year:04d}-{d.month:02d}"
    return f"{d.year:04d}"


def ttl_for_period(period: str) -> int:
    if period == "day":
        return int(settings.HUAWEI_STATION_ENERGY_DAY_TTL_SEC)
    if period == "month":
        return int(settings.HUAWEI_STATION_ENERGY_MONTH_TTL_SEC)
    return int(settings.HUAWEI_STATION_ENERGY_YEAR_TTL_SEC)


def _row_to_payload(row: HuaweiStationEnergyTotals) -> dict[str, Any]:
    """Convert DB row to the same JSON shape returned by `get_station_energy_kpi`."""
    cons = row.consumption_kwh
    # Backfill consumption for legacy cache rows saved before huawei_api computed
    # the fallback (matches the formula in `_extract_energy_row`).
    if cons is None:
        if row.self_consumption_kwh is not None and row.grid_import_kwh is not None:
            cons = float(row.self_consumption_kwh) + float(row.grid_import_kwh)
        elif (
            row.pv_kwh is not None
            and row.grid_export_kwh is not None
            and row.grid_import_kwh is not None
        ):
            cons = max(0.0, float(row.pv_kwh) - float(row.grid_export_kwh)) + float(row.grid_import_kwh)
    return {
        "stationCode": row.station_code,
        "pvKwh": row.pv_kwh,
        "consumptionKwh": cons,
        "gridImportKwh": row.grid_import_kwh,
        "gridExportKwh": row.grid_export_kwh,
        "selfConsumptionKwh": row.self_consumption_kwh,
        "radiationKwhM2": row.radiation_kwh_m2,
        "theoryKwh": row.theory_kwh,
        "perpowerRatioKwhKwp": row.perpower_ratio,
    }


def _values_from_item(it: dict[str, Any]) -> dict[str, Any]:
    """Extract DB columns from a single item returned by `get_station_energy_kpi`."""
    return {
        "pv_kwh": it.get("pvKwh"),
        "consumption_kwh": it.get("consumptionKwh"),
        "grid_import_kwh": it.get("gridImportKwh"),
        "grid_export_kwh": it.get("gridExportKwh"),
        "self_consumption_kwh": it.get("selfConsumptionKwh"),
        "radiation_kwh_m2": it.get("radiationKwhM2"),
        "theory_kwh": it.get("theoryKwh"),
        "perpower_ratio": it.get("perpowerRatioKwhKwp"),
    }


async def read_totals_row(
    session: AsyncSession, station_code: str, period: str, period_key: str
) -> Optional[HuaweiStationEnergyTotals]:
    stmt = select(HuaweiStationEnergyTotals).where(
        HuaweiStationEnergyTotals.station_code == station_code,
        HuaweiStationEnergyTotals.period == period,
        HuaweiStationEnergyTotals.period_key == period_key,
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def upsert_totals_row(
    session: AsyncSession,
    station_code: str,
    period: str,
    period_key: str,
    item: dict[str, Any],
) -> None:
    values = {
        "station_code": station_code,
        "period": period,
        "period_key": period_key,
        "saved_at": datetime.now(timezone.utc),
        **_values_from_item(item),
    }
    stmt = pg_insert(HuaweiStationEnergyTotals).values(**values)
    update_set = {
        "saved_at": stmt.excluded.saved_at,
        "pv_kwh": stmt.excluded.pv_kwh,
        "consumption_kwh": stmt.excluded.consumption_kwh,
        "grid_import_kwh": stmt.excluded.grid_import_kwh,
        "grid_export_kwh": stmt.excluded.grid_export_kwh,
        "self_consumption_kwh": stmt.excluded.self_consumption_kwh,
        "radiation_kwh_m2": stmt.excluded.radiation_kwh_m2,
        "theory_kwh": stmt.excluded.theory_kwh,
        "perpower_ratio": stmt.excluded.perpower_ratio,
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["station_code", "period", "period_key"],
        set_=update_set,
    )
    await session.execute(stmt)


async def refresh_from_api(
    session: AsyncSession, station_code: str, period: str, date_iso: str
) -> Optional[dict[str, Any]]:
    """
    Hit Huawei API for one (station, period, date), upsert the result, and return the JSON-shaped item.
    Returns None on rate-limit / error (caller decides whether to fall back to a stale DB row).
    """
    try:
        body = await get_station_energy_kpi(station_code, period, date_iso)
    except HuaweiAuthError:
        logger.warning("Huawei totals refresh: login failed (%s/%s/%s)", station_code, period, date_iso)
        return None
    except HuaweiRateLimitNoCacheError:
        logger.warning("Huawei totals refresh: rate-limited (%s/%s/%s)", station_code, period, date_iso)
        return None
    except HuaweiNorthboundError as exc:
        logger.warning(
            "Huawei totals refresh: Northbound error %s (%s/%s/%s)",
            exc.fail_code,
            station_code,
            period,
            date_iso,
        )
        return None
    if not body or not body.get("ok"):
        return None
    items = body.get("items") or []
    if not items:
        return None
    item = items[0]
    d = parse_date_iso(date_iso)
    if d is None:
        return item
    pkey = period_key_for(d, period)
    await upsert_totals_row(session, station_code, period, pkey, item)
    return item


async def get_or_refresh_totals(
    session: AsyncSession, station_code: str, period: str, date_iso: str
) -> dict[str, Any]:
    """
    Return totals payload for one station/period/date.

    1. Read from DB.
    2. If missing or older than TTL → call API, upsert, return fresh.
    3. On API failure with stale row in DB → return stale row + ``stale: True``.
    """
    if period not in VALID_PERIODS:
        return {"ok": False, "reason": "invalid_period"}
    d = parse_date_iso(date_iso)
    if d is None:
        return {"ok": False, "reason": "invalid_date"}

    # For day view, use the same DB source as DAM bars (`huawei_power_sample`) to avoid
    # drift between "FusionSolar totals" card and Open EMS chart totals.
    if period == "day":
        day_body = await get_station_hourly_chart_from_db(session, station_code, date_iso)
        if day_body.get("ok") and isinstance(day_body.get("totals"), dict):
            t = day_body["totals"]
            item = {
                "stationCode": station_code,
                "pvKwh": t.get("generationKwh"),
                "consumptionKwh": t.get("consumptionKwh"),
                "gridImportKwh": t.get("gridImportKwh"),
                "gridExportKwh": t.get("gridExportKwh"),
                "selfConsumptionKwh": None,
                "radiationKwhM2": None,
                "theoryKwh": None,
                "perpowerRatioKwhKwp": None,
            }
            return {
                "ok": True,
                "period": "day",
                "periodKey": d.isoformat(),
                "source": "huawei_power_sample",
                "cacheAgeSec": 0.0,
                "items": [item],
            }

    pkey = period_key_for(d, period)
    row = await read_totals_row(session, station_code, period, pkey)
    now = time.time()
    ttl = ttl_for_period(period)

    if row is not None:
        age_sec = max(0.0, now - row.saved_at.timestamp())
        if age_sec <= ttl:
            return {
                "ok": True,
                "period": period,
                "periodKey": pkey,
                "source": "db",
                "cacheAgeSec": round(age_sec, 1),
                "items": [_row_to_payload(row)],
            }
        # Stale — try to refresh; if refresh fails, return the stale row marked accordingly.
        if huawei_configured():
            fresh = await refresh_from_api(session, station_code, period, date_iso)
            if fresh is not None:
                await session.commit()
                return {
                    "ok": True,
                    "period": period,
                    "periodKey": pkey,
                    "source": "api",
                    "cacheAgeSec": 0.0,
                    "items": [fresh],
                }
        return {
            "ok": True,
            "period": period,
            "periodKey": pkey,
            "source": "db",
            "stale": True,
            "cacheAgeSec": round(age_sec, 1),
            "items": [_row_to_payload(row)],
        }

    # No DB row yet — must call API once.
    if not huawei_configured():
        return {"ok": False, "reason": "not_configured", "configured": False}
    fresh = await refresh_from_api(session, station_code, period, date_iso)
    if fresh is None:
        return {
            "ok": False,
            "configured": True,
            "reason": "no_data_yet",
            "periodKey": pkey,
        }
    await session.commit()
    return {
        "ok": True,
        "period": period,
        "periodKey": pkey,
        "source": "api",
        "cacheAgeSec": 0.0,
        "items": [fresh],
    }


async def run_huawei_station_energy_snapshot() -> int:
    """
    Background task: refresh day/month/year totals for the current Kyiv calendar date,
    for every plant returned by ``list_stations``. Writes to ``huawei_station_energy_totals``.

    Returns the number of (station, period) refreshes that succeeded.
    """
    if not huawei_configured():
        return 0
    try:
        plants = await list_stations()
    except HuaweiRateLimitNoCacheError:
        logger.warning("Huawei station energy snapshot: rate-limited at list_stations; skipping cycle")
        return 0
    except Exception as exc:
        logger.warning("Huawei station energy snapshot: list_stations failed — %s", exc)
        return 0

    if not plants:
        return 0

    from zoneinfo import ZoneInfo

    today_kyiv = datetime.now(ZoneInfo("Europe/Kyiv")).date().isoformat()
    n_ok = 0
    async with async_session_factory() as session:
        for plant in plants:
            station_code = str(plant.get("stationCode") or "").strip()
            if not station_code:
                continue
            for period in VALID_PERIODS:
                try:
                    item = await refresh_from_api(session, station_code, period, today_kyiv)
                    if item is not None:
                        n_ok += 1
                except Exception as exc:
                    logger.warning(
                        "Huawei station energy snapshot: refresh %s/%s failed — %s",
                        station_code,
                        period,
                        exc,
                    )
        await session.commit()
    return n_ok
