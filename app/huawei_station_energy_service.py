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

from sqlalchemy import func, select
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
    huawei_kpi_blocked,
    huawei_login_blocked,
    index_kpi_rows,
    list_stations,
    normalize_station_energy_kwh,
)
from app.huawei_power_service import (
    get_station_hourly_chart_from_db,
    get_station_period_totals_from_db,
)
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
    normalized = normalize_station_energy_kwh(
        pv_kwh=row.pv_kwh,
        consumption_kwh=row.consumption_kwh,
        grid_import_kwh=row.grid_import_kwh,
        grid_export_kwh=row.grid_export_kwh,
        self_consumption_kwh=row.self_consumption_kwh,
    )
    return {
        "stationCode": row.station_code,
        **normalized,
        "radiationKwhM2": row.radiation_kwh_m2,
        "theoryKwh": row.theory_kwh,
        "perpowerRatioKwhKwp": row.perpower_ratio,
    }


def _sample_grid_import_kwh(totals: dict[str, Any]) -> float:
    try:
        return float(totals.get("gridImportKwh") or 0.0)
    except (TypeError, ValueError):
        return 0.0


async def _sum_daily_grid_import_kwh_from_cache(
    session: AsyncSession, station_code: str, d: date, period: str
) -> Optional[float]:
    """
    Sum FusionSolar daily KPI grid import (``huawei_station_energy_totals`` period=day) for a month or year.
    Background snapshot fills these from getKpiStationDay buyEnergy — often non-zero when 5‑min samples show 0.
    """
    if period == "month":
        like_pat = f"{d.year:04d}-{d.month:02d}-%"
    elif period == "year":
        like_pat = f"{d.year:04d}-%"
    else:
        return None
    stmt = select(func.coalesce(func.sum(HuaweiStationEnergyTotals.grid_import_kwh), 0.0)).where(
        HuaweiStationEnergyTotals.station_code == station_code,
        HuaweiStationEnergyTotals.period == "day",
        HuaweiStationEnergyTotals.period_key.like(like_pat),
        HuaweiStationEnergyTotals.grid_import_kwh.is_not(None),
    )
    res = await session.execute(stmt)
    total = float(res.scalar_one() or 0.0)
    return total if total > 1e-6 else None


async def _period_grid_import_from_kpi_cache(
    session: AsyncSession,
    station_code: str,
    period: str,
    period_key: str,
    date_iso: str,
) -> Optional[float]:
    """Grid import from cached or freshly fetched FusionSolar month/year KPI (buyEnergy)."""
    row = await read_totals_row(session, station_code, period, period_key)
    if row is not None and row.grid_import_kwh is not None:
        v = float(row.grid_import_kwh)
        if v > 1e-6:
            return v
    if not huawei_configured():
        return None
    item = await refresh_from_api(session, station_code, period, date_iso)
    if item is None:
        return None
    g = item.get("gridImportKwh")
    if g is None:
        return None
    try:
        v = float(g)
    except (TypeError, ValueError):
        return None
    return v if v > 1e-6 else None


async def _enrich_period_grid_import(
    session: AsyncSession,
    station_code: str,
    period: str,
    date_iso: str,
    period_key: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    """
    Month/year totals from ``huawei_power_sample`` often show 0 import when snapshots used the
    live PV≈load display heuristic. Prefer summed daily FusionSolar KPI, then month/year KPI.
    """
    if period not in ("month", "year"):
        return item
    if _sample_grid_import_kwh(item) > 1e-6:
        return item
    d = parse_date_iso(date_iso)
    if d is None:
        return item
    alt = await _sum_daily_grid_import_kwh_from_cache(session, station_code, d, period)
    if alt is None:
        alt = await _period_grid_import_from_kpi_cache(
            session, station_code, period, period_key, date_iso
        )
    if alt is None:
        return item
    out = dict(item)
    out["gridImportKwh"] = round(alt, 4)
    return out


def _item_from_power_sample_totals(station_code: str, totals: dict[str, Any]) -> dict[str, Any]:
    """Map huawei_power_sample totals to the station-energy KPI item shape."""
    return {
        "stationCode": station_code,
        "pvKwh": totals.get("generationKwh"),
        "consumptionKwh": totals.get("consumptionKwh"),
        "gridImportKwh": totals.get("gridImportKwh"),
        "gridExportKwh": totals.get("gridExportKwh"),
        "selfConsumptionKwh": None,
        "radiationKwhM2": None,
        "theoryKwh": None,
        "perpowerRatioKwhKwp": None,
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


async def _month_kpi_copied(
    session: AsyncSession, station_code: str, pv_kwh: Optional[float]
) -> bool:
    """True when the same month PV total was stored for several different months.

    getKpiStationMonth returns every month of the year. Older refreshes kept
    only the first row and wrote it onto whichever month was requested.
    """
    if pv_kwh is None:
        return False
    stmt = (
        select(func.count())
        .select_from(HuaweiStationEnergyTotals)
        .where(
            HuaweiStationEnergyTotals.station_code == station_code,
            HuaweiStationEnergyTotals.period == "month",
            HuaweiStationEnergyTotals.pv_kwh.is_not(None),
            func.abs(HuaweiStationEnergyTotals.pv_kwh - float(pv_kwh)) < 0.05,
        )
    )
    count = int((await session.execute(stmt)).scalar_one() or 0)
    return count >= 3


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


async def _refresh_from_api_detailed(
    session: AsyncSession, station_code: str, period: str, date_iso: str
) -> tuple[Optional[dict[str, Any]], bool]:
    """KPI item plus whether FusionSolar refused the call for frequency (failCode 407)."""
    if huawei_login_blocked() or huawei_kpi_blocked():
        logger.info(
            "Huawei totals refresh: cooldown, skip (%s/%s/%s)",
            station_code,
            period,
            date_iso,
        )
        return None, True
    try:
        body = await get_station_energy_kpi(station_code, period, date_iso)
    except HuaweiAuthError:
        logger.warning("Huawei totals refresh: login failed (%s/%s/%s)", station_code, period, date_iso)
        return None, False
    except HuaweiRateLimitNoCacheError:
        logger.warning("Huawei totals refresh: rate-limited (%s/%s/%s)", station_code, period, date_iso)
        return None, True
    except HuaweiNorthboundError as exc:
        limited = exc.fail_code == 407
        logger.warning(
            "Huawei totals refresh: Northbound error %s (%s/%s/%s)",
            exc.fail_code,
            station_code,
            period,
            date_iso,
        )
        return None, limited
    if isinstance(body, dict) and body.get("northboundRateLimited"):
        return None, True
    if not body or not body.get("ok"):
        return None, False
    items = body.get("items") or []
    if not items:
        return None, False
    d = parse_date_iso(date_iso)
    if d is None:
        return None, False
    pkey = period_key_for(d, period)
    # One Northbound call returns every day of the month, or every month of the
    # year. Store each row under its collectTime. Writing items[0] onto the
    # requested key made every month show the same totals.
    keyed = index_kpi_rows(items, period, pkey)
    matched: Optional[dict[str, Any]] = None
    for key, item in keyed:
        await upsert_totals_row(session, station_code, period, key, item)
        if key == pkey:
            matched = item
    return matched, False


async def refresh_from_api(
    session: AsyncSession, station_code: str, period: str, date_iso: str
) -> Optional[dict[str, Any]]:
    """
    Hit Huawei API for one (station, period, date), upsert the result, and return the JSON-shaped item.
    Returns None on rate-limit / error (caller decides whether to fall back to a stale DB row).
    """
    item, _rate_limited = await _refresh_from_api_detailed(session, station_code, period, date_iso)
    return item


def energy_origin_kwh(item: Optional[dict[str, Any]]) -> Optional[dict[str, Optional[float]]]:
    """Map a station-energy item to consumption / PV / grid-import kWh."""
    if not isinstance(item, dict):
        return None

    def num(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed != parsed:
            return None
        return parsed

    generation = item.get("pvKwh")
    if generation is None and "generationKwh" in item:
        generation = item.get("generationKwh")
    grid_import = item.get("gridImportKwh")
    if grid_import is None and "importKwh" in item:
        grid_import = item.get("importKwh")
    origin = {
        "consumptionKwh": num(item.get("consumptionKwh")),
        "generationKwh": num(generation),
        "importKwh": num(grid_import),
    }
    if all(value is None for value in origin.values()):
        return None
    return origin


async def _load_open_ems_energy_item(
    session: AsyncSession, station_code: str, period: str, date_iso: str
) -> Optional[dict[str, Any]]:
    """kWh integrated from ``huawei_power_sample``. None when that day has no samples."""
    if period == "day":
        sample_body = await get_station_hourly_chart_from_db(session, station_code, date_iso)
    else:
        sample_body = await get_station_period_totals_from_db(session, station_code, period, date_iso)
    if not sample_body.get("ok") or sample_body.get("empty"):
        return None
    totals = sample_body.get("totals") or {}
    if not isinstance(totals, dict):
        return None
    return _item_from_power_sample_totals(station_code, totals)


async def _load_huawei_cloud_energy_item(
    session: AsyncSession,
    station_code: str,
    period: str,
    date_iso: str,
    day: date,
) -> tuple[Optional[dict[str, Any]], bool, bool, str, float]:
    """FusionSolar getKpiStation* item via the DB cache.

    Returns ``(item, error, rate_limited, source, cache_age_sec)``.
    ``error`` is a hard failure. ``rate_limited`` is failCode 407: keep the last
    row when one exists, and do not report it as a load error.
    """
    pkey = period_key_for(day, period)
    row = await read_totals_row(session, station_code, period, pkey)
    now = time.time()
    if row is not None:
        # Serve the cache on the request path. A stale refresh waits on the
        # Northbound lock (62s gap) and nginx closes the UI request at 60s.
        # The snapshot task still refreshes today's rows in the background.
        age_sec = max(0.0, now - row.saved_at.timestamp())
        if period == "month" and await _month_kpi_copied(session, station_code, row.pv_kwh):
            return None, False, False, "db", round(age_sec, 1)
        return _row_to_payload(row), False, False, "db", round(age_sec, 1)
    if not huawei_configured():
        return None, False, False, "db", 0.0
    fresh, rate_limited = await _refresh_from_api_detailed(session, station_code, period, date_iso)
    if fresh is None:
        return None, not rate_limited, rate_limited, "api", 0.0
    await session.commit()
    return fresh, False, False, "api", 0.0


async def get_or_refresh_totals(
    session: AsyncSession, station_code: str, period: str, date_iso: str
) -> dict[str, Any]:
    """
    Return both energy origins for one station/period/date.

    ``openEms`` is integrated from ``huawei_power_sample``.
    ``huaweiCloud`` is FusionSolar getKpiStationDay/Month/Year, cached in
    ``huawei_station_energy_totals`` and refreshed when the row is stale.

    ``items`` stays the previous single card: samples when present (month/year
    import may still be filled from the KPI cache), otherwise the cloud row.
    """
    if period not in VALID_PERIODS:
        return {"ok": False, "reason": "invalid_period"}
    d = parse_date_iso(date_iso)
    if d is None:
        return {"ok": False, "reason": "invalid_date"}

    pkey = period_key_for(d, period)
    open_item = await _load_open_ems_energy_item(session, station_code, period, date_iso)
    cloud_item, cloud_error, cloud_rate_limited, cloud_source, cloud_age = (
        await _load_huawei_cloud_energy_item(session, station_code, period, date_iso, d)
    )
    # Copied month KPI rows are not that month. Show the measured month total
    # until a FusionSolar refresh stores each month under its own collectTime.
    if (
        period == "month"
        and cloud_item is None
        and open_item is not None
        and not cloud_error
        and not cloud_rate_limited
    ):
        cloud_item = open_item
    open_origin = energy_origin_kwh(open_item)
    cloud_origin = energy_origin_kwh(cloud_item)

    if open_origin is None and cloud_origin is None and not cloud_error and not cloud_rate_limited:
        if not huawei_configured():
            return {"ok": False, "reason": "not_configured", "configured": False}
        return {
            "ok": False,
            "configured": True,
            "reason": "no_data_yet",
            "periodKey": pkey,
        }

    stale = False
    if open_item is not None:
        display = await _enrich_period_grid_import(
            session, station_code, period, date_iso, pkey, dict(open_item)
        )
        source = "huawei_power_sample"
        if period in ("month", "year") and _sample_grid_import_kwh(open_item) <= 1e-6:
            grid_import = display.get("gridImportKwh")
            if grid_import is not None and float(grid_import) > 1e-6:
                source = "huawei_power_sample+fusionsolar_kpi"
        items: list[dict[str, Any]] = [display]
        cache_age = 0.0
    elif cloud_item is not None:
        items = [cloud_item]
        source = cloud_source
        cache_age = cloud_age
        stale = cloud_source == "db" and cloud_age > ttl_for_period(period)
    else:
        items = []
        source = cloud_source
        cache_age = cloud_age

    body: dict[str, Any] = {
        "ok": True,
        "period": period,
        "periodKey": pkey,
        "source": source,
        "cacheAgeSec": cache_age,
        "items": items,
        "openEms": open_origin,
        "huaweiCloud": cloud_origin,
        "huaweiCloudError": cloud_error,
        "huaweiCloudRateLimited": cloud_rate_limited,
        "retryAfterSec": int(settings.HUAWEI_NORTHBOUND_COOLDOWN_AFTER_407_SEC)
        if cloud_rate_limited
        else None,
    }
    if stale:
        body["stale"] = True
    return body


async def run_huawei_station_energy_snapshot() -> int:
    """
    Background task: refresh day/month/year totals for the current Kyiv calendar date,
    for every plant returned by ``list_stations``. Writes to ``huawei_station_energy_totals``.

    Returns the number of (station, period) refreshes that succeeded.
    """
    if not huawei_configured() or huawei_kpi_blocked():
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
                    item, limited = await _refresh_from_api_detailed(
                        session, station_code, period, today_kyiv
                    )
                except Exception as exc:
                    logger.warning(
                        "Huawei station energy snapshot: refresh %s/%s failed — %s",
                        station_code,
                        period,
                        exc,
                    )
                    continue
                if limited:
                    logger.warning("Huawei station energy snapshot: rate-limited, stopping cycle")
                    await session.commit()
                    return n_ok
                if item is not None:
                    n_ok += 1
        await session.commit()
    return n_ok
