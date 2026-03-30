"""Persist Deye SoC / grid power samples to PostgreSQL and read hourly aggregates (Kyiv calendar day)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deye_api import deye_configured, list_inverter_devices, refresh_device_latest_batches
from app.models import DeyeSocSample
from app.oree_dam_service import KYIV


def floor_to_5min_utc(when: datetime) -> datetime:
    """UTC instant aligned to the start of its 5-minute wall bucket."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    utc = when.astimezone(timezone.utc)
    epoch = int(utc.timestamp())
    floored = epoch - (epoch % 300)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def _kyiv_day_bounds(trade_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(trade_day, time.min, tzinfo=KYIV)
    end = start + timedelta(days=1)
    return start, end


async def upsert_deye_sample(
    session: AsyncSession,
    device_sn: str,
    bucket_start: datetime,
    soc_percent: Optional[float],
    grid_power_w: Optional[float],
) -> None:
    if soc_percent is None and grid_power_w is None:
        return
    stmt = pg_insert(DeyeSocSample).values(
        device_sn=device_sn,
        bucket_start=bucket_start,
        soc_percent=soc_percent,
        grid_power_w=grid_power_w,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["device_sn", "bucket_start"],
        set_={
            "soc_percent": func.coalesce(stmt.excluded.soc_percent, DeyeSocSample.soc_percent),
            "grid_power_w": func.coalesce(stmt.excluded.grid_power_w, DeyeSocSample.grid_power_w),
        },
    )
    await session.execute(stmt)


async def run_deye_soc_snapshot(session: AsyncSession) -> int:
    """
    List all inverters, fetch fresh metrics from Deye, upsert per device per 5-min bucket.
      - soc_percent: 0..100 when available
      - grid_power_w: signed W (positive = grid import, negative = export)
    """
    if not deye_configured():
        return 0
    items = await list_inverter_devices()
    sns = [str(it.get("deviceSn") or "").strip() for it in items if it.get("deviceSn")]
    if not sns:
        return 0
    merged = await refresh_device_latest_batches(sns)
    bucket = floor_to_5min_utc(datetime.now(timezone.utc))
    n = 0
    for sn in sns:
        soc, _, _, _, grid_w = merged.get(sn, (None, None, None, None, None))
        soc_val: Optional[float] = None
        if soc is not None:
            try:
                fv = float(soc)
                if 0 <= fv <= 100:
                    soc_val = fv
            except (TypeError, ValueError):
                pass
        grid_val: Optional[float] = None
        if grid_w is not None:
            try:
                grid_val = float(grid_w)
            except (TypeError, ValueError):
                pass
        if soc_val is None and grid_val is None:
            continue
        await upsert_deye_sample(session, sn, bucket, soc_val, grid_val)
        n += 1
    return n


def _mean_or_none(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


async def hourly_inverter_history_for_kyiv_day(
    session: AsyncSession,
    device_sn: str,
    trade_day: date,
) -> tuple[list[Optional[float]], list[Optional[float]]]:
    """
    Two lists of 24 values (chart hours 1..24): mean SoC % and mean grid power (W signed) per Kyiv hour.
    """
    sn = (device_sn or "").strip()
    if not sn:
        return [None] * 24, [None] * 24

    start_kyiv, end_kyiv = _kyiv_day_bounds(trade_day)
    start_utc = start_kyiv.astimezone(timezone.utc)
    end_utc = end_kyiv.astimezone(timezone.utc)

    result = await session.execute(
        select(
            DeyeSocSample.bucket_start,
            DeyeSocSample.soc_percent,
            DeyeSocSample.grid_power_w,
        ).where(
            DeyeSocSample.device_sn == sn,
            DeyeSocSample.bucket_start >= start_utc,
            DeyeSocSample.bucket_start < end_utc,
        )
    )
    rows = result.all()
    soc_buckets: list[list[float]] = [[] for _ in range(24)]
    grid_buckets: list[list[float]] = [[] for _ in range(24)]
    for bucket_start, soc, grid_w in rows:
        local = bucket_start.astimezone(KYIV)
        h = int(local.hour)
        if 0 <= h <= 23:
            if soc is not None:
                soc_buckets[h].append(float(soc))
            if grid_w is not None:
                grid_buckets[h].append(float(grid_w))

    soc_out = [_mean_or_none(soc_buckets[i]) for i in range(24)]
    grid_out = [_mean_or_none(grid_buckets[i]) for i in range(24)]
    return soc_out, grid_out
