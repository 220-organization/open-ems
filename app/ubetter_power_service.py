"""Persist Ubetter power / SoC samples to PostgreSQL (5-minute UTC buckets, like Deye)."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deye_soc_service import floor_to_5min_utc
from app.models import UbetterPowerSample
from app.oree_dam_service import KYIV
from app.ubetter_api import get_device_summary, list_devices, ubetter_configured

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


async def upsert_ubetter_power_sample(
    session: AsyncSession,
    device_sn: str,
    bucket_start: datetime,
    *,
    soc_percent: Optional[float] = None,
    grid_power_w: Optional[float] = None,
    load_power_w: Optional[float] = None,
    pv_power_w: Optional[float] = None,
    pv_generation_w: Optional[float] = None,
    battery_power_w: Optional[float] = None,
) -> None:
    if (
        soc_percent is None
        and grid_power_w is None
        and load_power_w is None
        and pv_power_w is None
        and pv_generation_w is None
        and battery_power_w is None
    ):
        return
    stmt = pg_insert(UbetterPowerSample).values(
        device_sn=device_sn,
        bucket_start=bucket_start,
        soc_percent=soc_percent,
        grid_power_w=grid_power_w,
        load_power_w=load_power_w,
        pv_power_w=pv_power_w,
        pv_generation_w=pv_generation_w,
        battery_power_w=battery_power_w,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["device_sn", "bucket_start"],
        set_={
            "soc_percent": func.coalesce(stmt.excluded.soc_percent, UbetterPowerSample.soc_percent),
            "grid_power_w": func.coalesce(stmt.excluded.grid_power_w, UbetterPowerSample.grid_power_w),
            "load_power_w": func.coalesce(stmt.excluded.load_power_w, UbetterPowerSample.load_power_w),
            "pv_power_w": func.coalesce(stmt.excluded.pv_power_w, UbetterPowerSample.pv_power_w),
            "pv_generation_w": func.coalesce(
                stmt.excluded.pv_generation_w,
                UbetterPowerSample.pv_generation_w,
            ),
            "battery_power_w": func.coalesce(
                stmt.excluded.battery_power_w,
                UbetterPowerSample.battery_power_w,
            ),
        },
    )
    await session.execute(stmt)


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


async def run_ubetter_power_snapshot(session: AsyncSession) -> int:
    """Fetch live power-flow per device and upsert one row per 5-minute UTC bucket."""
    if not ubetter_configured():
        return 0
    try:
        items = await list_devices()
    except Exception:
        logger.exception("Ubetter power snapshot: list_devices failed")
        return 0
    sns = [str(it.get("sn") or "").strip() for it in items if it.get("sn")]
    if not sns:
        return 0

    bucket = floor_to_5min_utc(datetime.now(timezone.utc))
    n = 0
    for sn in sns:
        try:
            pf = await get_device_summary(sn)
        except Exception:
            logger.debug("Ubetter power snapshot: get_device_summary failed for %s", sn, exc_info=True)
            continue
        if not pf.get("ok"):
            continue

        soc_val: Optional[float] = None
        soc = _optional_float(pf.get("socPercent"))
        if soc is not None and 0.0 <= soc <= 100.0:
            soc_val = soc

        grid_val = _optional_float(pf.get("gridPowerW"))
        load_raw = _optional_float(pf.get("loadPowerW"))
        load_val = max(0.0, load_raw) if load_raw is not None else None
        pv_raw = _optional_float(pf.get("pvPowerW"))
        pv_val = max(0.0, pv_raw) if pv_raw is not None else None
        pv_gen_val = pv_val
        bat_val = _optional_float(pf.get("batteryPowerW"))

        if soc_val is None and grid_val is None and load_val is None and pv_val is None and bat_val is None:
            continue

        await upsert_ubetter_power_sample(
            session,
            sn,
            bucket,
            soc_percent=soc_val,
            grid_power_w=grid_val,
            load_power_w=load_val,
            pv_power_w=pv_val,
            pv_generation_w=pv_gen_val,
            battery_power_w=bat_val,
        )
        n += 1
    return n


async def hourly_device_history_for_kyiv_day(
    session: AsyncSession,
    device_sn: str,
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
    PV kWh/h, load kWh/h — same response shape as Deye soc-history-day.
    """
    sn = (device_sn or "").strip()
    empty = ([None] * 24,) * 5
    if not sn:
        return empty  # type: ignore[return-value]

    start_kyiv, end_kyiv = _kyiv_day_bounds(trade_day)
    start_utc = start_kyiv.astimezone(timezone.utc)
    end_utc = end_kyiv.astimezone(timezone.utc)

    result = await session.execute(
        select(
            UbetterPowerSample.bucket_start,
            UbetterPowerSample.soc_percent,
            UbetterPowerSample.grid_power_w,
            UbetterPowerSample.load_power_w,
            UbetterPowerSample.pv_generation_w,
            UbetterPowerSample.pv_power_w,
            UbetterPowerSample.battery_power_w,
        ).where(
            UbetterPowerSample.device_sn == sn,
            UbetterPowerSample.bucket_start >= start_utc,
            UbetterPowerSample.bucket_start < end_utc,
        )
    )
    rows = result.all()

    soc_buckets: list[list[float]] = [[] for _ in range(24)]
    grid_buckets: list[list[float]] = [[] for _ in range(24)]
    pv_w_buckets: list[list[float]] = [[] for _ in range(24)]
    load_w_buckets: list[list[float]] = [[] for _ in range(24)]

    for bucket_start, soc, grid_w, load_w, pv_gen_w, pv_w, _bat_w in rows:
        local = bucket_start.astimezone(KYIV)
        h = int(local.hour)
        if not (0 <= h <= 23):
            continue
        if soc is not None:
            soc_buckets[h].append(float(soc))
        if grid_w is not None:
            grid_buckets[h].append(float(grid_w))
        eff_pv = pv_gen_w if pv_gen_w is not None else pv_w
        if eff_pv is not None:
            pv_w_buckets[h].append(float(eff_pv))
        if load_w is not None:
            load_w_buckets[h].append(float(load_w))

    soc_out = [_mean_or_none(soc_buckets[i]) for i in range(24)]
    grid_out = [_mean_or_none(grid_buckets[i]) for i in range(24)]
    freq_out: list[Optional[float]] = [None] * 24
    pv_kwh_out = [_mean_power_w_to_kwh_hour(_mean_or_none(pv_w_buckets[i])) for i in range(24)]
    load_kwh_out = [_mean_power_w_to_kwh_hour(_mean_or_none(load_w_buckets[i])) for i in range(24)]
    return soc_out, grid_out, freq_out, pv_kwh_out, load_kwh_out
