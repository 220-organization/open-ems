"""Persist Deye SoC / grid power samples to PostgreSQL and read hourly aggregates (Kyiv calendar day)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deye_api import deye_configured, list_inverter_devices, refresh_device_latest_batches
from app.deye_flow_balance import (
    FLOW_BALANCE_DEVICE_SNS,
    FLOW_BALANCE_PV_FACTOR,
    effective_pv_generation_watts,
)
from app.models import DeyeSocSample
from app.oree_dam_service import KYIV

# Cached True once columns exist. Before that, re-probe each call (migration may run without restart).
_balance_input_columns_ready: bool = False


async def deye_soc_balance_input_columns_ready(session: AsyncSession) -> bool:
    """
    True when deye_soc_sample has load_power_w, pv_power_w, battery_power_w (migration applied).
    While columns are missing, probes every call so Flyway can enable balance without API restart.
    """
    global _balance_input_columns_ready
    if _balance_input_columns_ready:
        return True
    r = await session.execute(
        text(
            "SELECT COUNT(*)::int FROM information_schema.columns "
            "WHERE table_name = 'deye_soc_sample' "
            "AND column_name IN ('load_power_w', 'pv_power_w', 'battery_power_w')"
        )
    )
    n = r.scalar_one()
    ok = int(n or 0) >= 3
    if ok:
        _balance_input_columns_ready = True
    return ok


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
    grid_frequency_hz: Optional[float] = None,
    load_power_w: Optional[float] = None,
    pv_power_w: Optional[float] = None,
    pv_generation_w: Optional[float] = None,
    battery_power_w: Optional[float] = None,
) -> None:
    if (
        soc_percent is None
        and grid_power_w is None
        and grid_frequency_hz is None
        and load_power_w is None
        and pv_power_w is None
        and pv_generation_w is None
        and battery_power_w is None
    ):
        return
    extras = await deye_soc_balance_input_columns_ready(session)
    if extras:
        stmt = pg_insert(DeyeSocSample).values(
            device_sn=device_sn,
            bucket_start=bucket_start,
            soc_percent=soc_percent,
            grid_power_w=grid_power_w,
            grid_frequency_hz=grid_frequency_hz,
            load_power_w=load_power_w,
            pv_power_w=pv_power_w,
            pv_generation_w=pv_generation_w,
            battery_power_w=battery_power_w,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["device_sn", "bucket_start"],
            set_={
                "soc_percent": func.coalesce(stmt.excluded.soc_percent, DeyeSocSample.soc_percent),
                "grid_power_w": func.coalesce(stmt.excluded.grid_power_w, DeyeSocSample.grid_power_w),
                "grid_frequency_hz": func.coalesce(
                    stmt.excluded.grid_frequency_hz,
                    DeyeSocSample.grid_frequency_hz,
                ),
                "load_power_w": func.coalesce(stmt.excluded.load_power_w, DeyeSocSample.load_power_w),
                "pv_power_w": func.coalesce(stmt.excluded.pv_power_w, DeyeSocSample.pv_power_w),
                "pv_generation_w": func.coalesce(stmt.excluded.pv_generation_w, DeyeSocSample.pv_generation_w),
                "battery_power_w": func.coalesce(
                    stmt.excluded.battery_power_w,
                    DeyeSocSample.battery_power_w,
                ),
            },
        )
    else:
        stmt = pg_insert(DeyeSocSample).values(
            device_sn=device_sn,
            bucket_start=bucket_start,
            soc_percent=soc_percent,
            grid_power_w=grid_power_w,
            grid_frequency_hz=grid_frequency_hz,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["device_sn", "bucket_start"],
            set_={
                "soc_percent": func.coalesce(stmt.excluded.soc_percent, DeyeSocSample.soc_percent),
                "grid_power_w": func.coalesce(stmt.excluded.grid_power_w, DeyeSocSample.grid_power_w),
                "grid_frequency_hz": func.coalesce(
                    stmt.excluded.grid_frequency_hz,
                    DeyeSocSample.grid_frequency_hz,
                ),
            },
        )
    await session.execute(stmt)


async def run_deye_soc_snapshot(session: AsyncSession) -> int:
    """
    List all inverters, fetch fresh metrics from Deye, upsert per device per 5-min bucket.
      - soc_percent: 0..100 when available
      - grid_power_w: signed W (positive = grid import, negative = export)
      - load_power_w, pv_power_w, battery_power_w: for hourly grid balance on calibrated SN
      - pv_generation_w: effective PV (W) for ROI/load energy — raw PV × FLOW_BALANCE_PV_FACTOR where needed
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
        soc, bat_w, load_w, pv_w, grid_w, freq_hz = merged.get(
            sn, (None, None, None, None, None, None)
        )
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
        freq_val: Optional[float] = None
        if freq_hz is not None:
            try:
                fv = float(freq_hz)
                if 40.0 <= fv <= 70.0:
                    freq_val = fv
            except (TypeError, ValueError):
                pass
        load_val: Optional[float] = None
        if load_w is not None:
            try:
                load_val = max(0.0, float(load_w))
            except (TypeError, ValueError):
                pass
        pv_val: Optional[float] = None
        pv_gen_val: Optional[float] = None
        if pv_w is not None:
            try:
                pv_val = max(0.0, float(pv_w))
                pv_gen_val = effective_pv_generation_watts(sn, pv_val)
            except (TypeError, ValueError):
                pass
        bat_val: Optional[float] = None
        if bat_w is not None:
            try:
                bat_val = float(bat_w)
            except (TypeError, ValueError):
                pass
        if (
            soc_val is None
            and grid_val is None
            and freq_val is None
            and load_val is None
            and pv_val is None
            and bat_val is None
        ):
            continue
        await upsert_deye_sample(
            session,
            sn,
            bucket,
            soc_val,
            grid_val,
            freq_val,
            load_val,
            pv_val,
            pv_gen_val,
            bat_val,
        )
        n += 1
    return n


def _mean_or_none(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _mean_power_w_to_kwh_hour(mean_w: Optional[float]) -> Optional[float]:
    """Approximate kWh in the hour from mean power (W) over 5-min samples in that hour."""
    if mean_w is None:
        return None
    return float(mean_w) / 1000.0


def _effective_pv_watts_for_sample(
    device_sn: str,
    pv_w: Optional[float],
    pv_generation_w: Optional[float],
) -> Optional[float]:
    if pv_generation_w is not None:
        return float(pv_generation_w)
    if pv_w is None:
        return None
    return float(effective_pv_generation_watts(device_sn, float(pv_w)))


async def hourly_inverter_history_for_kyiv_day(
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
    Five lists of 24 values (chart hours 0..23 mapped to display hours 1..24):

    - mean SoC %, mean grid power (W signed), mean grid frequency (Hz)
    - mean PV energy (kWh) and mean load energy (kWh) per Kyiv hour from 5-min samples
      (kWh ≈ mean power in W / 1000 for that hour).
    """
    sn = (device_sn or "").strip()
    if not sn:
        empty = [None] * 24
        return empty, empty, empty, empty, empty

    start_kyiv, end_kyiv = _kyiv_day_bounds(trade_day)
    start_utc = start_kyiv.astimezone(timezone.utc)
    end_utc = end_kyiv.astimezone(timezone.utc)

    extras = await deye_soc_balance_input_columns_ready(session)
    if extras:
        result = await session.execute(
            select(
                DeyeSocSample.bucket_start,
                DeyeSocSample.soc_percent,
                DeyeSocSample.grid_power_w,
                DeyeSocSample.grid_frequency_hz,
                DeyeSocSample.load_power_w,
                DeyeSocSample.pv_power_w,
                DeyeSocSample.pv_generation_w,
                DeyeSocSample.battery_power_w,
            ).where(
                DeyeSocSample.device_sn == sn,
                DeyeSocSample.bucket_start >= start_utc,
                DeyeSocSample.bucket_start < end_utc,
            )
        )
        rows = result.all()
    else:
        result = await session.execute(
            select(
                DeyeSocSample.bucket_start,
                DeyeSocSample.soc_percent,
                DeyeSocSample.grid_power_w,
                DeyeSocSample.grid_frequency_hz,
            ).where(
                DeyeSocSample.device_sn == sn,
                DeyeSocSample.bucket_start >= start_utc,
                DeyeSocSample.bucket_start < end_utc,
            )
        )
        rows = [(a, b, c, d, None, None, None, None) for (a, b, c, d) in result.all()]

    soc_buckets: list[list[float]] = [[] for _ in range(24)]
    grid_buckets: list[list[float]] = [[] for _ in range(24)]
    freq_buckets: list[list[float]] = [[] for _ in range(24)]
    balance_buckets: list[list[float]] = [[] for _ in range(24)]
    pv_w_buckets: list[list[float]] = [[] for _ in range(24)]
    load_w_buckets: list[list[float]] = [[] for _ in range(24)]
    for bucket_start, soc, grid_w, freq_hz, load_w, pv_w, pv_gen_w, bat_w in rows:
        local = bucket_start.astimezone(KYIV)
        h = int(local.hour)
        if 0 <= h <= 23:
            if soc is not None:
                soc_buckets[h].append(float(soc))
            if grid_w is not None:
                grid_buckets[h].append(float(grid_w))
            if freq_hz is not None:
                freq_buckets[h].append(float(freq_hz))
            if load_w is not None and pv_w is not None and bat_w is not None:
                balance_buckets[h].append(
                    float(load_w)
                    - FLOW_BALANCE_PV_FACTOR * float(pv_w)
                    - float(bat_w)
                )
            eff_pv = _effective_pv_watts_for_sample(sn, pv_w, pv_gen_w)
            if eff_pv is not None:
                pv_w_buckets[h].append(eff_pv)
            if load_w is not None:
                load_w_buckets[h].append(float(load_w))

    soc_out = [_mean_or_none(soc_buckets[i]) for i in range(24)]
    grid_out = [_mean_or_none(grid_buckets[i]) for i in range(24)]
    freq_out = [_mean_or_none(freq_buckets[i]) for i in range(24)]
    balance_out = [_mean_or_none(balance_buckets[i]) for i in range(24)]

    if sn in FLOW_BALANCE_DEVICE_SNS:
        grid_out = [
            balance_out[i] if balance_out[i] is not None else grid_out[i] for i in range(24)
        ]

    if extras:
        pv_kwh_out = [_mean_power_w_to_kwh_hour(_mean_or_none(pv_w_buckets[i])) for i in range(24)]
        load_kwh_out = [_mean_power_w_to_kwh_hour(_mean_or_none(load_w_buckets[i])) for i in range(24)]
    else:
        pv_kwh_out = [None] * 24
        load_kwh_out = [None] * 24

    return soc_out, grid_out, freq_out, pv_kwh_out, load_kwh_out
