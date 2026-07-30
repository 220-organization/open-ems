"""Persist GridLab BESS power / SoC samples and normalize live power-flow for UI."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.deye_soc_service import floor_to_5min_utc
from app.gridlab_api import get_meters, get_status, gridlab_configured
from app.models import GridLabMeterReading, GridLabPowerSample
from app.oree_dam_service import KYIV

logger = logging.getLogger(__name__)


def _kyiv_day_bounds(trade_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(trade_day, time.min, tzinfo=KYIV)
    end = start + timedelta(days=1)
    return start, end


def _mean_or_none(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _mean_power_w_to_kwh_hour(mean_w: Optional[float]) -> Optional[float]:
    if mean_w is None:
        return None
    return float(mean_w) / 1000.0


def _optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _kw_to_w(power_kw: Optional[float]) -> Optional[float]:
    if power_kw is None:
        return None
    return float(power_kw) * 1000.0


def is_stale_sample(
    *,
    stale_flag: Any = None,
    data_age_seconds: Any = None,
    max_age_sec: Optional[int] = None,
) -> bool:
    """True when GridLab marks the sample stale or age exceeds configured max."""
    max_age = max_age_sec if max_age_sec is not None else settings.GRIDLAB_STALE_MAX_AGE_SEC
    if stale_flag is True:
        return True
    age = _optional_float(data_age_seconds)
    if age is not None and age > float(max_age):
        return True
    return False


def find_meter_by_id(
    meters: list[dict[str, Any]], meter_id: int, *, allow_virtual: bool = False
) -> Optional[dict[str, Any]]:
    """Return the meter with the given id, skipping virtual rows unless allowed."""
    for m in meters:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        try:
            if int(mid) != int(meter_id):
                continue
        except (TypeError, ValueError):
            continue
        if m.get("is_virtual") is True and not allow_virtual:
            return None
        return m
    return None


def find_first_physical_by_role(
    meters: list[dict[str, Any]], role: str
) -> Optional[dict[str, Any]]:
    """Fallback: first non-virtual meter with the given role."""
    role_l = (role or "").strip().lower()
    for m in meters:
        if not isinstance(m, dict):
            continue
        if m.get("is_virtual") is True:
            continue
        if str(m.get("role") or "").strip().lower() == role_l:
            return m
    return None


def select_site_meters(
    meters: list[dict[str, Any]],
    *,
    pcc_id: Optional[int] = None,
    pv_id: Optional[int] = None,
    load_id: Optional[int] = None,
    ev_ids: Optional[tuple[int, ...]] = None,
) -> dict[str, Any]:
    """
    Pick PCC / PV / LOAD / EV meters by explicit IDs (preferred).
    Falls back to first physical meter of each role when ID is missing.
    Never sums all meters of a role (device 16 topology overlaps).
    """
    pcc_wanted = int(pcc_id if pcc_id is not None else settings.GRIDLAB_PCC_METER_ID)
    pv_wanted = int(pv_id if pv_id is not None else settings.GRIDLAB_PV_METER_ID)
    load_wanted = int(load_id if load_id is not None else settings.GRIDLAB_LOAD_METER_ID)
    ev_wanted = tuple(ev_ids if ev_ids is not None else settings.GRIDLAB_EV_METER_IDS)

    pcc = find_meter_by_id(meters, pcc_wanted) or find_first_physical_by_role(meters, "pcc")
    pv = find_meter_by_id(meters, pv_wanted) or find_first_physical_by_role(meters, "production")
    load = find_meter_by_id(meters, load_wanted) or find_first_physical_by_role(meters, "load")
    ev_list: list[dict[str, Any]] = []
    for eid in ev_wanted:
        m = find_meter_by_id(meters, eid)
        if m is not None:
            ev_list.append(m)

    return {
        "pcc": pcc,
        "pv": pv,
        "load": load,
        "ev": ev_list,
        "selectedIds": {
            "pcc": int(pcc["id"]) if pcc and pcc.get("id") is not None else None,
            "pv": int(pv["id"]) if pv and pv.get("id") is not None else None,
            "load": int(load["id"]) if load and load.get("id") is not None else None,
            "ev": [int(m["id"]) for m in ev_list if m.get("id") is not None],
        },
    }


def sum_ev_power_kw(ev_meters: list[dict[str, Any]]) -> Optional[float]:
    """Sum EV charger powers; None if no meter contributed a numeric power."""
    total = 0.0
    any_val = False
    for m in ev_meters:
        if is_stale_sample(stale_flag=m.get("stale"), data_age_seconds=m.get("data_age_seconds")):
            continue
        pw = _optional_float(m.get("power_kw"))
        if pw is None:
            continue
        total += pw
        any_val = True
    return total if any_val else None


def map_live_power_flow(
    status: dict[str, Any],
    meters_payload: dict[str, Any],
    *,
    persist_fresh_only: bool = False,
) -> dict[str, Any]:
    """
    Normalize GridLab status + meters into Open EMS power-flow shape.

    Sign conventions (same as Deye/Ubetter UI):
      - batteryPowerW > 0 = discharge, < 0 = charge
      - gridPowerW > 0 = import from grid, < 0 = export
      - pvPowerW / loadPowerW / evPowerW >= 0

    When ``persist_fresh_only`` is True, stale samples become None (for DB upsert).
    Live UI always receives values with ``stale`` / ``dataAgeSeconds`` flags.
    """
    meters_raw = meters_payload.get("meters") if isinstance(meters_payload, dict) else None
    meters_list = meters_raw if isinstance(meters_raw, list) else []
    selected = select_site_meters(meters_list)

    status_stale = is_stale_sample(
        stale_flag=status.get("stale"), data_age_seconds=status.get("data_age_seconds")
    )
    soc = _optional_float(status.get("soc_percent"))
    bat_kw = _optional_float(status.get("power_kw"))

    def _meter_power(m: Optional[dict[str, Any]]) -> tuple[Optional[float], bool]:
        if m is None:
            return None, True
        stale = is_stale_sample(
            stale_flag=m.get("stale"), data_age_seconds=m.get("data_age_seconds")
        )
        return _optional_float(m.get("power_kw")), stale

    pcc_kw, pcc_stale = _meter_power(selected["pcc"])
    pv_kw, pv_stale = _meter_power(selected["pv"])
    load_kw, load_stale = _meter_power(selected["load"])
    ev_kw = sum_ev_power_kw(selected["ev"])

    any_stale = bool(status_stale or pcc_stale or pv_stale or load_stale)
    ages = [
        a
        for a in (
            _optional_float(status.get("data_age_seconds")),
            _optional_float((selected["pcc"] or {}).get("data_age_seconds")),
            _optional_float((selected["pv"] or {}).get("data_age_seconds")),
            _optional_float((selected["load"] or {}).get("data_age_seconds")),
        )
        if a is not None
    ]
    data_age = max(ages) if ages else None

    def _maybe_drop(val: Optional[float], stale: bool) -> Optional[float]:
        if persist_fresh_only and stale:
            return None
        return val

    soc_out = _maybe_drop(soc, status_stale)
    if soc_out is not None and not (0.0 <= soc_out <= 100.0):
        soc_out = None

    bat_w = _kw_to_w(_maybe_drop(bat_kw, status_stale))
    grid_w = _kw_to_w(_maybe_drop(pcc_kw, pcc_stale))
    pv_w_raw = _maybe_drop(pv_kw, pv_stale)
    load_w_raw = _maybe_drop(load_kw, load_stale)
    # Production / load powers are non-negative in UI; keep None if missing.
    pv_w = max(0.0, pv_w_raw * 1000.0) if pv_w_raw is not None else None
    load_w = max(0.0, load_w_raw * 1000.0) if load_w_raw is not None else None
    ev_w = _kw_to_w(ev_kw)

    is_online = status.get("is_online")
    if not isinstance(is_online, bool):
        is_online = None

    return {
        "ok": True,
        "configured": True,
        "deviceId": int(status.get("device_id") or settings.GRIDLAB_DEVICE_ID),
        "name": str(status.get("name") or "").strip() or None,
        "socPercent": soc_out if persist_fresh_only else (soc if soc is not None and 0.0 <= soc <= 100.0 else None),
        "batteryPowerW": bat_w if persist_fresh_only else _kw_to_w(bat_kw),
        "gridPowerW": grid_w if persist_fresh_only else _kw_to_w(pcc_kw),
        "pvPowerW": pv_w if persist_fresh_only else (
            max(0.0, pv_kw * 1000.0) if pv_kw is not None else None
        ),
        "loadPowerW": load_w if persist_fresh_only else (
            max(0.0, load_kw * 1000.0) if load_kw is not None else None
        ),
        "evPowerW": ev_w,
        "isOnline": is_online,
        "stale": any_stale,
        "dataAgeSeconds": data_age,
        "timestamp": status.get("timestamp"),
        "selectedMeterIds": selected["selectedIds"],
        "meters": meters_list,
    }


async def upsert_gridlab_power_sample(
    session: AsyncSession,
    device_id: int,
    bucket_start: datetime,
    *,
    soc_percent: Optional[float] = None,
    battery_power_w: Optional[float] = None,
    grid_power_w: Optional[float] = None,
    pv_power_w: Optional[float] = None,
    load_power_w: Optional[float] = None,
    ev_power_w: Optional[float] = None,
    is_online: Optional[bool] = None,
) -> None:
    if (
        soc_percent is None
        and battery_power_w is None
        and grid_power_w is None
        and pv_power_w is None
        and load_power_w is None
        and ev_power_w is None
        and is_online is None
    ):
        return
    stmt = pg_insert(GridLabPowerSample).values(
        device_id=device_id,
        bucket_start=bucket_start,
        soc_percent=soc_percent,
        battery_power_w=battery_power_w,
        grid_power_w=grid_power_w,
        pv_power_w=pv_power_w,
        load_power_w=load_power_w,
        ev_power_w=ev_power_w,
        is_online=is_online,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["device_id", "bucket_start"],
        set_={
            "soc_percent": func.coalesce(stmt.excluded.soc_percent, GridLabPowerSample.soc_percent),
            "battery_power_w": func.coalesce(
                stmt.excluded.battery_power_w, GridLabPowerSample.battery_power_w
            ),
            "grid_power_w": func.coalesce(
                stmt.excluded.grid_power_w, GridLabPowerSample.grid_power_w
            ),
            "pv_power_w": func.coalesce(stmt.excluded.pv_power_w, GridLabPowerSample.pv_power_w),
            "load_power_w": func.coalesce(
                stmt.excluded.load_power_w, GridLabPowerSample.load_power_w
            ),
            "ev_power_w": func.coalesce(stmt.excluded.ev_power_w, GridLabPowerSample.ev_power_w),
            "is_online": func.coalesce(stmt.excluded.is_online, GridLabPowerSample.is_online),
        },
    )
    await session.execute(stmt)


async def upsert_gridlab_meter_reading(
    session: AsyncSession,
    device_id: int,
    meter_id: int,
    bucket_start: datetime,
    *,
    power_kw: Optional[float] = None,
    kwh_import: Optional[float] = None,
    kwh_export: Optional[float] = None,
) -> None:
    if power_kw is None and kwh_import is None and kwh_export is None:
        return
    stmt = pg_insert(GridLabMeterReading).values(
        device_id=device_id,
        meter_id=meter_id,
        bucket_start=bucket_start,
        power_kw=power_kw,
        kwh_import=kwh_import,
        kwh_export=kwh_export,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["device_id", "meter_id", "bucket_start"],
        set_={
            "power_kw": func.coalesce(stmt.excluded.power_kw, GridLabMeterReading.power_kw),
            "kwh_import": func.coalesce(
                stmt.excluded.kwh_import, GridLabMeterReading.kwh_import
            ),
            "kwh_export": func.coalesce(
                stmt.excluded.kwh_export, GridLabMeterReading.kwh_export
            ),
        },
    )
    await session.execute(stmt)


async def build_live_power_flow(*, use_cache: bool = True) -> dict[str, Any]:
    """Fetch status + meters and return normalized live power-flow (for UI)."""
    if not gridlab_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}
    status = await get_status(use_cache=use_cache)
    meters = await get_meters(use_cache=use_cache)
    return map_live_power_flow(status, meters, persist_fresh_only=False)


async def run_gridlab_power_snapshot(session: AsyncSession) -> int:
    """Fetch live status/meters and upsert one 5-minute UTC bucket (+ meter readings)."""
    if not gridlab_configured():
        return 0
    try:
        status = await get_status(use_cache=False)
        meters_payload = await get_meters(use_cache=False)
    except Exception:
        logger.exception("GridLab power snapshot: fetch failed")
        return 0

    live = map_live_power_flow(status, meters_payload, persist_fresh_only=True)
    device_id = int(live.get("deviceId") or settings.GRIDLAB_DEVICE_ID)
    bucket = floor_to_5min_utc(datetime.now(timezone.utc))

    await upsert_gridlab_power_sample(
        session,
        device_id,
        bucket,
        soc_percent=live.get("socPercent"),
        battery_power_w=live.get("batteryPowerW"),
        grid_power_w=live.get("gridPowerW"),
        pv_power_w=live.get("pvPowerW"),
        load_power_w=live.get("loadPowerW"),
        ev_power_w=live.get("evPowerW"),
        is_online=live.get("isOnline"),
    )

    meters_list = live.get("meters") if isinstance(live.get("meters"), list) else []
    n_meters = 0
    for m in meters_list:
        if not isinstance(m, dict) or m.get("is_virtual") is True:
            continue
        if is_stale_sample(stale_flag=m.get("stale"), data_age_seconds=m.get("data_age_seconds")):
            continue
        mid = m.get("id")
        try:
            meter_id = int(mid)
        except (TypeError, ValueError):
            continue
        await upsert_gridlab_meter_reading(
            session,
            device_id,
            meter_id,
            bucket,
            power_kw=_optional_float(m.get("power_kw")),
            kwh_import=_optional_float(m.get("kwh_import")),
            kwh_export=_optional_float(m.get("kwh_export")),
        )
        n_meters += 1

    logger.debug(
        "GridLab power snapshot: device=%s meters=%s bucket=%s",
        device_id,
        n_meters,
        bucket.isoformat(),
    )
    return 1


async def hourly_device_history_for_kyiv_day(
    session: AsyncSession,
    device_id: int,
    trade_day: date,
) -> tuple[
    list[Optional[float]],
    list[Optional[float]],
    list[Optional[float]],
    list[Optional[float]],
    list[Optional[float]],
]:
    """
    Five lists of 24 Kyiv-hour values: SoC %, grid W, frequency placeholder (None),
    PV kWh/h, load kWh/h — same response shape as Ubetter/Deye soc-history-day.
    """
    empty = ([None] * 24,) * 5
    if device_id <= 0:
        return empty  # type: ignore[return-value]

    start_kyiv, end_kyiv = _kyiv_day_bounds(trade_day)
    start_utc = start_kyiv.astimezone(timezone.utc)
    end_utc = end_kyiv.astimezone(timezone.utc)

    result = await session.execute(
        select(
            GridLabPowerSample.bucket_start,
            GridLabPowerSample.soc_percent,
            GridLabPowerSample.grid_power_w,
            GridLabPowerSample.load_power_w,
            GridLabPowerSample.pv_power_w,
            GridLabPowerSample.battery_power_w,
        ).where(
            GridLabPowerSample.device_id == device_id,
            GridLabPowerSample.bucket_start >= start_utc,
            GridLabPowerSample.bucket_start < end_utc,
        )
    )
    rows = result.all()

    soc_buckets: list[list[float]] = [[] for _ in range(24)]
    grid_buckets: list[list[float]] = [[] for _ in range(24)]
    pv_w_buckets: list[list[float]] = [[] for _ in range(24)]
    load_w_buckets: list[list[float]] = [[] for _ in range(24)]

    for bucket_start, soc, grid_w, load_w, pv_w, _bat_w in rows:
        local = bucket_start.astimezone(KYIV)
        h = int(local.hour)
        if not (0 <= h <= 23):
            continue
        if soc is not None:
            soc_buckets[h].append(float(soc))
        if grid_w is not None:
            grid_buckets[h].append(float(grid_w))
        if pv_w is not None:
            pv_w_buckets[h].append(float(pv_w))
        if load_w is not None:
            load_w_buckets[h].append(float(load_w))

    soc_out = [_mean_or_none(soc_buckets[i]) for i in range(24)]
    grid_out = [_mean_or_none(grid_buckets[i]) for i in range(24)]
    freq_out: list[Optional[float]] = [None] * 24
    pv_kwh_out = [_mean_power_w_to_kwh_hour(_mean_or_none(pv_w_buckets[i])) for i in range(24)]
    load_kwh_out = [
        _mean_power_w_to_kwh_hour(_mean_or_none(load_w_buckets[i])) for i in range(24)
    ]
    return soc_out, grid_out, freq_out, pv_kwh_out, load_kwh_out
