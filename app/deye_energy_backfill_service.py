"""Backfill hourly kWh from Deye Cloud into ``deye_hourly_energy``.

Frame shape (granularity=1) is integrated per Kyiv hour, then scaled so the day sums
match Deye daily counters (granularity=2). Open EMS totals then match Deye Cloud.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deye_api import (
    _grid_power_signed_watts_from_data_list,
    _load_power_watts_from_data_list,
    _pv_power_watts_from_data_list,
    clear_station_history_cache_for_cluster,
    deye_configured,
    fetch_device_day_frames,
    fetch_device_day_totals,
    station_cluster_device_sns,
)
from app.models import DeyeHourlyEnergy
from app.oree_dam_service import KYIV

logger = logging.getLogger(__name__)

# Cap inter-frame gaps when integrating power (seconds).
_MAX_GAP_SEC = 15 * 60
_DEYE_CONCURRENCY = 2

ProgressCb = Callable[[int, int], Any]


def period_dates_kyiv(period: str, anchor_day: date) -> list[date]:
    """Calendar days in the period up to today (Europe/Kyiv)."""
    today_kyiv = datetime.now(KYIV).date()
    if period == "day":
        return [anchor_day] if anchor_day <= today_kyiv else []
    if period == "month":
        cursor = anchor_day.replace(day=1)
        out: list[date] = []
        while cursor.month == anchor_day.month and cursor.year == anchor_day.year:
            if cursor > today_kyiv:
                break
            out.append(cursor)
            cursor += timedelta(days=1)
        return out
    cursor = anchor_day.replace(month=1, day=1)
    out = []
    while cursor.year == anchor_day.year:
        if cursor > today_kyiv:
            break
        out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _empty_hourly() -> dict[str, list[Optional[float]]]:
    return {
        "consumptionKwh": [None] * 24,
        "generationKwh": [None] * 24,
        "importKwh": [None] * 24,
        "exportKwh": [None] * 24,
    }


def _add_to_hour(bucket: list[Optional[float]], hour: int, value: float) -> None:
    if not (0 <= hour <= 23):
        return
    if value < 0:
        value = 0.0
    if bucket[hour] is None:
        bucket[hour] = value
    else:
        bucket[hour] = float(bucket[hour]) + value


def _energy_from_power_interval(
    w0: Optional[float],
    w1: Optional[float],
    dt_sec: float,
) -> Optional[float]:
    """Trapezoid kWh for one interval; returns None when both ends are missing."""
    if dt_sec <= 0:
        return None
    if w0 is None and w1 is None:
        return None
    a = 0.0 if w0 is None else float(w0)
    b = 0.0 if w1 is None else float(w1)
    mean_w = (a + b) / 2.0
    return mean_w * (dt_sec / 3600.0) / 1000.0


def _split_interval_across_kyiv_hours(
    t0: datetime,
    t1: datetime,
    kwh: float,
) -> list[tuple[int, float]]:
    """Split energy between two UTC instants across Kyiv local hours (same calendar day)."""
    if kwh <= 0 or t1 <= t0:
        return []
    total_sec = (t1 - t0).total_seconds()
    if total_sec <= 0:
        return []
    out: list[tuple[int, float]] = []
    cursor = t0
    remaining = kwh
    while cursor < t1 and remaining > 1e-12:
        local = cursor.astimezone(KYIV)
        hour = int(local.hour)
        next_hour_local = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        next_hour_utc = next_hour_local.astimezone(timezone.utc)
        segment_end = min(t1, next_hour_utc)
        seg_sec = (segment_end - cursor).total_seconds()
        if seg_sec <= 0:
            break
        share = kwh * (seg_sec / total_sec)
        out.append((hour, share))
        remaining -= share
        cursor = segment_end
    return out


def hourly_kwh_from_frames(
    frames: list[tuple[datetime, list[dict[str, Any]]]],
) -> dict[str, list[Optional[float]]]:
    """
    Integrate frame power into Kyiv-hour kWh buckets.

    Positive grid power → import; negative → export. Gaps longer than 15 minutes are capped.
    """
    hourly = _empty_hourly()
    if len(frames) < 1:
        return hourly
    # Single frame: treat as 5-minute sample centred on that instant.
    if len(frames) == 1:
        ts, items = frames[0]
        load_w = _load_power_watts_from_data_list(items)
        pv_w = _pv_power_watts_from_data_list(items)
        grid_w = _grid_power_signed_watts_from_data_list(items)
        # Assume 5 minutes of constant power.
        dt = 300.0
        h = int(ts.astimezone(KYIV).hour)
        if load_w is not None:
            _add_to_hour(hourly["consumptionKwh"], h, max(0.0, float(load_w)) * dt / 3600.0 / 1000.0)
        if pv_w is not None:
            _add_to_hour(hourly["generationKwh"], h, max(0.0, float(pv_w)) * dt / 3600.0 / 1000.0)
        if grid_w is not None:
            g = float(grid_w)
            if g > 0:
                _add_to_hour(hourly["importKwh"], h, g * dt / 3600.0 / 1000.0)
            elif g < 0:
                _add_to_hour(hourly["exportKwh"], h, abs(g) * dt / 3600.0 / 1000.0)
        return hourly

    for i in range(len(frames) - 1):
        t0, items0 = frames[i]
        t1, items1 = frames[i + 1]
        raw_dt = (t1 - t0).total_seconds()
        if raw_dt <= 0:
            continue
        dt = min(raw_dt, float(_MAX_GAP_SEC))
        # Scale endpoint for capped gaps: integrate over [t0, t0+dt] not full [t0,t1].
        t_end = t0 + timedelta(seconds=dt) if dt < raw_dt else t1

        load0 = _load_power_watts_from_data_list(items0)
        load1 = _load_power_watts_from_data_list(items1)
        pv0 = _pv_power_watts_from_data_list(items0)
        pv1 = _pv_power_watts_from_data_list(items1)
        grid0 = _grid_power_signed_watts_from_data_list(items0)
        grid1 = _grid_power_signed_watts_from_data_list(items1)

        load_kwh = _energy_from_power_interval(
            None if load0 is None else max(0.0, float(load0)),
            None if load1 is None else max(0.0, float(load1)),
            dt,
        )
        pv_kwh = _energy_from_power_interval(
            None if pv0 is None else max(0.0, float(pv0)),
            None if pv1 is None else max(0.0, float(pv1)),
            dt,
        )
        # Grid: integrate signed, then split import/export by sign of mean.
        grid_kwh_net = _energy_from_power_interval(
            None if grid0 is None else float(grid0),
            None if grid1 is None else float(grid1),
            dt,
        )

        if load_kwh is not None and load_kwh > 0:
            for hour, share in _split_interval_across_kyiv_hours(t0, t_end, load_kwh):
                _add_to_hour(hourly["consumptionKwh"], hour, share)
        if pv_kwh is not None and pv_kwh > 0:
            for hour, share in _split_interval_across_kyiv_hours(t0, t_end, pv_kwh):
                _add_to_hour(hourly["generationKwh"], hour, share)
        if grid_kwh_net is not None and abs(grid_kwh_net) > 1e-12:
            if grid_kwh_net > 0:
                for hour, share in _split_interval_across_kyiv_hours(t0, t_end, grid_kwh_net):
                    _add_to_hour(hourly["importKwh"], hour, share)
            else:
                for hour, share in _split_interval_across_kyiv_hours(t0, t_end, abs(grid_kwh_net)):
                    _add_to_hour(hourly["exportKwh"], hour, share)

    return hourly


def scale_to_day_totals(
    hourly: dict[str, list[Optional[float]]],
    totals: dict[str, Optional[float]],
) -> dict[str, list[Optional[float]]]:
    """
    Scale each series so the day sum equals the Deye daily total.

    If the shape is all zeros but the total is non-zero, spread evenly over hours that
    already have any non-null series value (or all 24 hours as a last resort).
    """
    out = {
        "consumptionKwh": list(hourly.get("consumptionKwh") or [None] * 24),
        "generationKwh": list(hourly.get("generationKwh") or [None] * 24),
        "importKwh": list(hourly.get("importKwh") or [None] * 24),
        "exportKwh": list(hourly.get("exportKwh") or [None] * 24),
    }
    field_map = {
        "consumptionKwh": "consumptionKwh",
        "generationKwh": "generationKwh",
        "importKwh": "importKwh",
        "exportKwh": "exportKwh",
    }

    # Hours that had any frame-derived energy (for even spread fallback).
    active_hours = [
        h
        for h in range(24)
        if any(
            (out[f][h] is not None and float(out[f][h]) > 0)
            for f in ("consumptionKwh", "generationKwh", "importKwh", "exportKwh")
        )
    ]

    for field, total_key in field_map.items():
        target = totals.get(total_key)
        if target is None:
            continue
        try:
            target_f = float(target)
        except (TypeError, ValueError):
            continue
        if not (target_f >= 0) or not (target_f == target_f):  # NaN check
            continue
        series = out[field]
        shape_sum = 0.0
        has_any = False
        for h in range(24):
            if series[h] is None:
                continue
            has_any = True
            shape_sum += max(0.0, float(series[h]))

        if target_f == 0.0:
            # Always write 24 zeros so sample-based Open EMS hours cannot leak through.
            for h in range(24):
                series[h] = 0.0
            continue

        if shape_sum > 1e-9:
            scale = target_f / shape_sum
            for h in range(24):
                if series[h] is None:
                    series[h] = 0.0
                else:
                    series[h] = max(0.0, float(series[h])) * scale
            continue

        # Flat shape: spread evenly across active (or all) hours; others stay 0.
        hours = active_hours if active_hours else list(range(24))
        each = target_f / len(hours)
        for h in range(24):
            series[h] = each if h in hours else 0.0

    return out


def _kyiv_hour_start_utc(trade_day: date, hour: int) -> datetime:
    local = datetime.combine(trade_day, time(hour=hour, minute=0), tzinfo=KYIV)
    return local.astimezone(timezone.utc)


async def upsert_hourly_energy_day(
    session: AsyncSession,
    device_sn: str,
    trade_day: date,
    hourly: dict[str, list[Optional[float]]],
) -> int:
    """Upsert up to 24 hourly rows for one device/day. Returns rows written."""
    sn = (device_sn or "").strip()
    if not sn:
        return 0
    n = 0
    now = datetime.now(timezone.utc)
    for h in range(24):
        cons = hourly["consumptionKwh"][h]
        gen = hourly["generationKwh"][h]
        imp = hourly["importKwh"][h]
        exp = hourly["exportKwh"][h]
        if cons is None and gen is None and imp is None and exp is None:
            continue
        hour_start = _kyiv_hour_start_utc(trade_day, h)
        stmt = pg_insert(DeyeHourlyEnergy).values(
            device_sn=sn,
            hour_start=hour_start,
            consumption_kwh=None if cons is None else float(cons),
            generation_kwh=None if gen is None else float(gen),
            import_kwh=None if imp is None else float(imp),
            export_kwh=None if exp is None else float(exp),
            source="deye_cloud",
            updated_on=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["device_sn", "hour_start"],
            set_={
                "consumption_kwh": stmt.excluded.consumption_kwh,
                "generation_kwh": stmt.excluded.generation_kwh,
                "import_kwh": stmt.excluded.import_kwh,
                "export_kwh": stmt.excluded.export_kwh,
                "source": stmt.excluded.source,
                "updated_on": stmt.excluded.updated_on,
            },
        )
        await session.execute(stmt)
        n += 1
    return n


async def _backfill_one_device_day(
    session: AsyncSession,
    device_sn: str,
    trade_day: date,
    sem: asyncio.Semaphore,
) -> int:
    day_iso = trade_day.isoformat()
    async with sem:
        frames = await fetch_device_day_frames(device_sn, day_iso)
        totals = await fetch_device_day_totals(device_sn, day_iso)
    hourly = scale_to_day_totals(hourly_kwh_from_frames(frames), totals)
    # If no frames and no totals, skip write.
    if (
        all(v is None for v in totals.values())
        and all(
            all(x is None for x in hourly[f])
            for f in ("consumptionKwh", "generationKwh", "importKwh", "exportKwh")
        )
    ):
        return 0
    return await upsert_hourly_energy_day(session, device_sn, trade_day, hourly)


async def backfill_device_period(
    session: AsyncSession,
    device_sn: str,
    period: str,
    anchor_iso: str,
    progress_cb: Optional[ProgressCb] = None,
) -> dict[str, Any]:
    """
    Backfill hourly energy for every day in the period for the station cluster.

    Commits after each calendar day. Limited Deye concurrency via semaphore.
    """
    if not deye_configured():
        raise RuntimeError("Deye API credentials not configured")
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("deviceSn required")
    try:
        anchor_day = date.fromisoformat((anchor_iso or "").strip()[:10])
    except ValueError as exc:
        raise ValueError("Invalid date; use YYYY-MM-DD") from exc
    if period not in ("day", "month", "year"):
        raise ValueError("period must be day, month, or year")

    cluster = await station_cluster_device_sns(sn)
    days = period_dates_kyiv(period, anchor_day)
    days_total = len(days)
    days_done = 0
    rows_written = 0
    if progress_cb:
        progress_cb(days_done, days_total)

    sem = asyncio.Semaphore(_DEYE_CONCURRENCY)
    for trade_day in days:
        for cluster_sn in cluster:
            try:
                n = await _backfill_one_device_day(session, cluster_sn, trade_day, sem)
                rows_written += n
            except Exception:
                logger.exception(
                    "deye energy backfill failed sn=%s day=%s",
                    cluster_sn,
                    trade_day.isoformat(),
                )
                raise
        await session.commit()
        days_done += 1
        if progress_cb:
            progress_cb(days_done, days_total)

    clear_station_history_cache_for_cluster(cluster, period, anchor_iso)
    return {
        "deviceSn": sn,
        "clusterDeviceSns": cluster,
        "period": period,
        "date": anchor_iso[:10],
        "daysTotal": days_total,
        "daysDone": days_done,
        "rowsWritten": rows_written,
    }
